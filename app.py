"""
IPTV Manager  —  Flask web application
Ejecutar:  python app.py
Abrir:     http://localhost:5000
"""
import base64
import copy
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(__file__)
# En Docker se puede montar /data para persistencia; fuera de Docker usa BASE_DIR
DATA_DIR    = os.environ.get("IPTV_DATA_DIR", BASE_DIR)
M3U_FILE    = os.path.join(DATA_DIR, "lista_iptv.m3u")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
EPG_URL     = (
    "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/"
    "refs/heads/master/guiatv.xml,"
    "https://epgshare01.online/epgshare01/epg_ripper_NL1.xml.gz"
)

STATUSES     = ["MAIN", "BACKUP", "TEST", "DISABLED"]
QUALITY_SET  = {"FHD", "HD", "SD", "4K"}
STATUS_ORDER = {s: i for i, s in enumerate(STATUSES)}

_DEFAULT_CFG = {
    "ace_host": "192.168.1.169",
    "ace_port": "8081",
    "ace_path": "/ace/getstream?id=",
    "nas_path": "",        # Ruta SMB/NAS donde copiar el M3U al guardar
    "jellyfin_mode": False,  # Si True, exporta solo el nombre limpio del canal
}

def _load_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return {**_DEFAULT_CFG, **json.load(f)}
        except Exception:
            pass
    return dict(_DEFAULT_CFG)

def _save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

def ace_base(cfg: dict | None = None) -> str:
    c = cfg or _load_config()
    return f"http://{c['ace_host']}:{c['ace_port']}{c['ace_path']}"

# ── State ─────────────────────────────────────────────────────────────────────
_channels: list  = []
_m3u_path: str   = M3U_FILE

app = Flask(__name__)


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _attr(line: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', line)
    return m.group(1) if m else ""


def parse_display_name(raw: str):
    """Handles both 'CANAL | Q | SRC | peer4' and 'CANAL Q peer4 --> SRC'."""
    if " | " in raw:
        parts = [p.strip() for p in raw.split(" | ")]
        peer_s = parts.pop() if parts and re.fullmatch(r"[0-9a-fA-F]{4}", parts[-1]) else ""
        quality = ""
        src_parts = []
        channel = parts[0] if parts else raw
        for p in parts[1:]:
            if not quality and p.upper() in QUALITY_SET:
                quality = p.upper()
            else:
                src_parts.append(p)
        return channel, quality, peer_s, " | ".join(src_parts)

    if " --> " not in raw:
        return raw.strip(), "", "", ""
    left, source = raw.rsplit(" --> ", 1)
    tokens = left.split()
    ps = tokens.pop() if tokens and re.fullmatch(r"[0-9a-fA-F]{4}", tokens[-1]) else ""
    q  = tokens.pop().upper() if tokens and tokens[-1].upper() in QUALITY_SET else ""
    return " ".join(tokens), q, ps, source.strip()


def peer_short(full: str) -> str:
    return full[-4:] if len(full) >= 4 else full


# ── M3U I/O ───────────────────────────────────────────────────────────────────

def load_m3u(path: str) -> list:
    global _channels, _m3u_path
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    channels: list = []
    seen: set = set()
    pending_status: str | None = None

    for i, line in enumerate(lines):
        # Parse Estado: from clean-format comment above #EXTINF
        if line.startswith("#") and "Estado:" in line and not line.startswith("#EXTINF"):
            m = re.search(r"Estado:\s*(\w+)", line)
            if m:
                pending_status = m.group(1).upper()
            continue

        if not line.startswith("#EXTINF"):
            continue

        extinf = line
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        url_raw = lines[j] if j < len(lines) else ""

        # Detect DISABLED (commented URL)
        is_disabled = url_raw.startswith("# ") or url_raw.startswith("#http")
        url = url_raw.lstrip("# ") if is_disabled else url_raw
        peer_full = url.split("?id=", 1)[-1].strip() if "?id=" in url else ""

        raw = re.search(r",\s*(.+)$", extinf)
        raw = raw.group(1).strip() if raw else ""
        channel, quality, _, source = parse_display_name(raw)

        group = _attr(extinf, "group-title")
        key   = (group, channel)

        if pending_status:
            status = pending_status
            pending_status = None
        elif is_disabled:
            status = "DISABLED"
        else:
            status = "MAIN" if key not in seen else "BACKUP"
        seen.add(key)

        channels.append({
            "id":       len(channels),
            "group":    group,
            "channel":  channel,
            "quality":  quality,
            "source":   source,
            "peer_full": peer_full,
            "tvg_id":   _attr(extinf, "tvg-id"),
            "tvg_logo": _attr(extinf, "tvg-logo"),
            "status":   status,
            "notes":    "",
        })

    _channels = channels
    _m3u_path = path
    return channels


def write_m3u(channels: list, output_path: str,
              jellyfin_mode: bool = False) -> dict:
    """Write clean structured M3U. Returns status counts.

    jellyfin_mode=True → display name is just the channel name (sin
    calidad/fuente/peer), ideal para Jellyfin/Emby que muestran el nombre tal cual.
    """
    def _key(c):
        return (
            c.get("group", ""),
            c.get("channel", ""),
            STATUS_ORDER.get(c.get("status", "BACKUP"), 99),
        )

    chans = sorted(channels, key=_key)
    out = [f'#EXTM3U url-tvg="{EPG_URL}" refresh="3600"',
           "#EXTVLCOPT:network-caching=1000", ""]

    cur_group = cur_channel = None
    for ch in chans:
        status   = ch.get("status", "MAIN").upper()
        group    = ch.get("group", "")
        channel  = ch.get("channel", "")
        quality  = ch.get("quality", "")
        source   = ch.get("source", "")
        peer     = ch.get("peer_full", "").strip()
        tvg_id   = ch.get("tvg_id", "")
        tvg_logo = ch.get("tvg_logo", "")
        notes    = ch.get("notes", "")

        if group != cur_group:
            cur_group = group
            cur_channel = None
            out += ["", "#" * 52, f"# CATEGORÍA: {group}", "#" * 52, ""]

        if channel != cur_channel:
            cur_channel = channel
            out += [
                f"# {'─'*10} Canal: {channel} {'─'*10}",
                f"# TVG-ID : {tvg_id}",
                f"# Logo   : {tvg_logo}",
                "",
            ]

        ps   = peer_short(peer)
        meta = []
        if source:  meta.append(f"Fuente: {source}")
        if quality: meta.append(f"Calidad: {quality}")
        if ps:      meta.append(f"Peer: {ps}")
        meta.append(f"Estado: {status}")
        if notes:   meta.append(f"Notas: {notes}")
        out.append("# " + "  |  ".join(meta))

        if jellyfin_mode:
            display = f"{channel} | {ps}" if ps else channel
        else:
            parts = [channel]
            if quality: parts.append(quality)
            if source:  parts.append(source)
            if ps:      parts.append(ps)
            display = " | ".join(parts)

        extinf = (f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" '
                  f'group-title="{group}",{display}')
        url = f"{ace_base()}{peer}"

        if status == "DISABLED":
            out += ["# DISABLED", f"# {extinf}", f"# {url}", ""]
        else:
            out += [extinf, url, ""]

    out.append("")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    return {s: sum(1 for c in chans if c.get("status", "").upper() == s)
            for s in STATUSES}


def _reindex():
    for i, ch in enumerate(_channels):
        ch["id"] = i


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", m3u_path=_m3u_path)


@app.route("/api/channels")
def api_channels():
    return jsonify(_channels)


@app.route("/api/channel/<int:idx>", methods=["PUT"])
def api_update(idx: int):
    global _channels
    if not (0 <= idx < len(_channels)):
        return jsonify({"ok": False, "error": "Not found"}), 404
    data = request.json or {}
    EDITABLE = ["channel", "group", "quality", "source",
                "peer_full", "tvg_id", "tvg_logo", "status", "notes"]
    for k in EDITABLE:
        if k in data:
            _channels[idx][k] = data[k]
    return jsonify({"ok": True, "channel": _channels[idx]})


@app.route("/api/channel/<int:idx>", methods=["DELETE"])
def api_delete(idx: int):
    global _channels
    if not (0 <= idx < len(_channels)):
        return jsonify({"ok": False}), 404
    _channels.pop(idx)
    _reindex()
    return jsonify({"ok": True})


@app.route("/api/reorder", methods=["POST"])
def api_reorder():
    """Reordena _channels según el array de IDs recibido."""
    global _channels
    order = request.json.get("order", [])
    id_map = {ch["id"]: ch for ch in _channels}
    reordered = [id_map[i] for i in order if i in id_map]
    seen = set(order)
    for ch in _channels:
        if ch["id"] not in seen:
            reordered.append(ch)
    _channels = reordered
    _reindex()
    return jsonify({"ok": True})


@app.route("/api/channel/new", methods=["POST"])
def api_new():
    global _channels
    data = request.json or {}
    EDITABLE = ["channel", "group", "quality", "source",
                "peer_full", "tvg_id", "tvg_logo", "status", "notes"]
    ch = {k: data.get(k, "") for k in EDITABLE}
    ch["id"] = len(_channels)
    if not ch.get("status"):
        ch["status"] = "BACKUP"
    _channels.append(ch)
    return jsonify({"ok": True, "channel": ch})


@app.route("/api/channel/<int:idx>/duplicate", methods=["POST"])
def api_duplicate(idx: int):
    global _channels
    if not (0 <= idx < len(_channels)):
        return jsonify({"ok": False}), 404
    dup = copy.deepcopy(_channels[idx])
    dup["status"] = "BACKUP"
    _channels.insert(idx + 1, dup)
    _reindex()
    return jsonify({"ok": True, "channel": _channels[idx + 1]})


@app.route("/api/save", methods=["POST"])
def api_save():
    global _m3u_path
    path  = (request.json or {}).get("path", _m3u_path)
    cfg   = _load_config()
    jmode = cfg.get("jellyfin_mode", False)
    stats = write_m3u(_channels, path, jellyfin_mode=False)
    _m3u_path = path

    nas_result = None
    nas_path = cfg.get("nas_path", "").strip()
    if nas_path:
        try:
            write_m3u(_channels, nas_path, jellyfin_mode=jmode)
            nas_result = {"ok": True, "path": nas_path}
        except Exception as e:
            nas_result = {"ok": False, "path": nas_path, "error": str(e)}

    return jsonify({"ok": True, "stats": stats, "path": path, "nas": nas_result})


@app.route("/api/export")
def api_export():
    tmp = os.path.join(BASE_DIR, "_export_tmp.m3u")
    write_m3u(_channels, tmp)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return send_file(tmp, as_attachment=True,
                     download_name=f"lista_iptv_{stamp}.m3u",
                     mimetype="audio/x-mpegurl")


@app.route("/live.m3u")
def live_m3u():
    """Endpoint M3U en vivo — apúntale cualquier cliente IPTV.

    Parámetros opcionales:
      ?host=192.168.1.x  → IP del servidor Acexy (por defecto la del config)
      ?port=8081         → Puerto del servidor Acexy (por defecto el del config)
      ?jellyfin=1        → nombres limpios (solo canal | peer)
      ?status=MAIN       → filtrar por estado (MAIN, BACKUP, TEST; omite DISABLED siempre)
      ?group=Fútbol      → filtrar por grupo (exacto)
    """
    cfg     = _load_config()
    host    = request.args.get("host", "").strip() or cfg.get("ace_host", "")
    port    = request.args.get("port", "").strip() or cfg.get("ace_port", "")
    path    = cfg.get("ace_path", "/ace/getstream?id=")
    base    = f"http://{host}:{port}{path}"

    jmode   = request.args.get("jellyfin", "") == "1" or cfg.get("jellyfin_mode", False)
    only_st = request.args.get("status", "").upper()
    only_gr = request.args.get("group", "")

    # Filtrar canales
    chans = [c for c in _channels if c.get("status", "").upper() != "DISABLED"]
    if only_st:
        chans = [c for c in chans if c.get("status", "").upper() == only_st]
    if only_gr:
        chans = [c for c in chans if c.get("group", "") == only_gr]

    lines = [f'#EXTM3U url-tvg="{EPG_URL}" refresh="3600"', ""]
    for ch in chans:
        peer     = ch.get("peer_full", "").strip()
        channel  = ch.get("channel", "")
        quality  = ch.get("quality", "")
        source   = ch.get("source", "")
        group    = ch.get("group", "")
        tvg_id   = ch.get("tvg_id", "")
        tvg_logo = ch.get("tvg_logo", "")
        ps       = peer_short(peer)

        if jmode:
            display = f"{channel} | {ps}" if ps else channel
        else:
            parts = [channel]
            if quality: parts.append(quality)
            if source:  parts.append(source)
            if ps:      parts.append(ps)
            display = " | ".join(parts)

        lines.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" '
            f'group-title="{group}",{display}'
        )
        lines.append(f"{base}{peer}")
        lines.append("")

    content = "\n".join(lines)
    return Response(content, content_type="audio/x-mpegurl; charset=utf-8")


@app.route("/api/load", methods=["POST"])
def api_load():
    path = (request.json or {}).get("path", M3U_FILE)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": f"No existe: {path}"}), 404
    channels = load_m3u(path)
    return jsonify({"ok": True, "count": len(channels)})


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Lanza import_from_web.py como subproceso y devuelve los canales nuevos."""
    import subprocess
    import sys

    script = os.path.join(BASE_DIR, "import_from_web.py")
    if not os.path.isfile(script):
        return jsonify({"ok": False, "error": "import_from_web.py no encontrado"}), 500

    try:
        proc = subprocess.run(
            [sys.executable, script, "--json"],
            capture_output=True,          # bytes, sin text mode
            cwd=BASE_DIR, timeout=90,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Timeout descargando la web (90s)"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip() or "error desconocido"
        return jsonify({"ok": False, "error": err}), 500

    # Decodificar stdout como bytes → str, quitar BOM si lo hay
    stdout_text = proc.stdout.decode("utf-8", errors="replace").strip().lstrip('\ufeff')

    # Extraer el bloque JSON: desde el primer '{' hasta el último '}'
    start = stdout_text.find('{')
    end   = stdout_text.rfind('}')
    if start == -1 or end == -1:
        return jsonify({"ok": False, "error": f"Sin JSON en salida:\n{stdout_text[:400]}"}), 500
    try:
        result = json.loads(stdout_text[start:end + 1])
    except Exception as e:
        snippet = stdout_text[start:start + 400]
        return jsonify({"ok": False, "error": f"JSON inválido ({e}):\n{snippet}"}), 500

    # Añadir canales nuevos a memoria
    known_peers = {ch.get("peer_full", "") for ch in _channels}
    added = []
    for ch in result.get("new_channels", []):
        if ch.get("peer_full") not in known_peers:
            ch["id"] = len(_channels)
            _channels.append(ch)
            known_peers.add(ch["peer_full"])
            added.append(ch)

    return jsonify({
        "ok":      True,
        "found":   result.get("found", 0),
        "added":   len(added),
        "skipped": result.get("skipped", 0),
        "new":     [{"channel": c["channel"], "group": c["group"],
                     "quality": c.get("quality", ""),
                     "source":  c.get("source", ""),
                     "peer":    c["peer_full"][-4:]} for c in added],
    })


def _test_url(url: str, timeout: int = 5) -> dict:
    """Intenta conectar a la URL y devuelve {status, latency_ms, detail}."""
    t0 = time.time()
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "VLC/3.0")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ms = int((time.time() - t0) * 1000)
            return {"status": "online", "latency_ms": ms, "detail": str(r.status)}
    except urllib.error.HTTPError as e:
        ms = int((time.time() - t0) * 1000)
        # 302 redirect = AceStream está sirviendo el stream → online
        if e.code in (301, 302, 206):
            return {"status": "online", "latency_ms": ms, "detail": f"HTTP {e.code}"}
        return {"status": "error", "latency_ms": ms, "detail": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        ms = int((time.time() - t0) * 1000)
        reason = str(e.reason)
        if "timed out" in reason.lower():
            return {"status": "timeout", "latency_ms": ms, "detail": "timeout"}
        return {"status": "offline", "latency_ms": ms, "detail": reason[:80]}
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        return {"status": "offline", "latency_ms": ms, "detail": str(e)[:80]}


@app.route("/api/play/<int:idx>")
def api_play(idx: int):
    """Devuelve un .m3u de un solo canal para abrir en VLC."""
    if not (0 <= idx < len(_channels)):
        return "Not found", 404
    ch      = _channels[idx]
    peer    = ch.get("peer_full", "").strip()
    name    = ch.get("channel", f"Canal {idx}")
    quality = ch.get("quality", "")
    source  = ch.get("source", "")
    group   = ch.get("group", "")
    tvg_id  = ch.get("tvg_id", "")
    logo    = ch.get("tvg_logo", "")
    parts   = [name]
    if quality: parts.append(quality)
    if source:  parts.append(source)
    if peer:    parts.append(peer[-4:])
    display = " | ".join(parts)
    url     = f"{ace_base()}{peer}"
    m3u = (
        f"#EXTM3U\n"
        f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{group}",{display}\n'
        f"{url}\n"
    )
    filename = f"{name.replace(' ', '_')}_{peer[-4:] if peer else 'nostream'}.m3u"
    return m3u, 200, {
        "Content-Type":        "audio/x-mpegurl; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }


def _acexy_connect(url: str, timeout: int = 60):
    """Abre conexión a Acexy/AceStream con reintentos.

    Acexy devuelve 500 mientras el stream está arrancando (puede tardar varios
    segundos). Reintentamos hasta `timeout` segundos. También sigue redirects
    302, sustituyendo 127.0.0.1 por el host remoto de Acexy.
    Devuelve (http.client.HTTPResponse, http.client.HTTPConnection) o (None, None).
    """
    original_host = urllib.parse.urlparse(url).hostname
    current_url   = url
    deadline      = time.time() + timeout

    while time.time() < deadline:
        p    = urllib.parse.urlparse(current_url)
        host = p.hostname
        port = p.port or 80
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")

        conn = http.client.HTTPConnection(host, port, timeout=10)
        try:
            conn.request("GET", path, headers={"User-Agent": "VLC/3.0"})
            r = conn.getresponse()
        except Exception as e:
            conn.close()
            app.logger.warning("acexy_connect error %s: %s", current_url, e)
            time.sleep(2)
            continue

        if r.status in (200, 206):
            return r, conn

        if r.status in (301, 302, 307, 308):
            location = r.getheader("Location", "")
            r.read(); conn.close()
            if not location:
                return None, None
            # AceStream redirige a 127.0.0.1 (localhost de la máquina remota)
            # → sustituimos por el host de Acexy para que Flask lo alcance.
            pl = urllib.parse.urlparse(location)
            if pl.hostname in ("127.0.0.1", "localhost", "0.0.0.0"):
                location = urllib.parse.urlunparse(
                    pl._replace(netloc=f"{original_host}:{pl.port or 80}")
                )
            current_url = location
            time.sleep(0.5)
            continue

        # 500 u otro error: stream arrancando, reintentamos
        body = r.read(256).decode("utf-8", errors="replace").strip()
        conn.close()
        app.logger.info("acexy_connect %s → %s (%s), reintentando…",
                        current_url, r.status, body[:80])
        time.sleep(2)

    return None, None


@app.route("/api/stream/<int:idx>")
def api_stream(idx: int):
    """Proxy MPEG-TS en streaming para el reproductor integrado (evita CORS)."""
    if not (0 <= idx < len(_channels)):
        return "Not found", 404
    ch   = _channels[idx]
    peer = ch.get("peer_full", "").strip()
    if not peer:
        return "No peer configured", 400

    r, conn = _acexy_connect(ace_base() + peer, timeout=30)
    if r is None:
        return "No se pudo conectar con Acexy/AceStream", 502

    content_type = r.getheader("Content-Type", "video/mp2t")

    def generate():
        try:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                r.close()
                conn.close()
            except Exception:
                pass

    return Response(
        stream_with_context(generate()),
        content_type=content_type,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/stream/debug/<int:idx>")
def api_stream_debug(idx: int):
    """Diagnóstico: muestra qué devuelve Acexy paso a paso."""
    if not (0 <= idx < len(_channels)):
        return jsonify({"error": "not found"}), 404
    ch   = _channels[idx]
    peer = ch.get("peer_full", "").strip()
    if not peer:
        return jsonify({"error": "no peer"}), 400

    start_url = ace_base() + peer
    log       = []
    url       = start_url
    original_host = urllib.parse.urlparse(url).hostname

    for step in range(6):
        p    = urllib.parse.urlparse(url)
        host = p.hostname
        port = p.port or 80
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        entry = {"step": step, "url": url, "host": host, "port": port}

        try:
            conn = http.client.HTTPConnection(host, port, timeout=10)
            conn.request("GET", path, headers={"User-Agent": "VLC/3.0"})
            r    = conn.getresponse()
            entry["status"]   = r.status
            entry["reason"]   = r.reason
            entry["headers"]  = dict(r.getheaders())
            location = r.getheader("Location", "")
            entry["location"] = location

            if r.status in (200, 206):
                first = r.read(128)
                entry["first_bytes"] = first.hex()
                entry["first_text"]  = first[:64].decode("latin-1", errors="replace")
                r.close(); conn.close()
                log.append(entry)
                break

            r.read(); conn.close()
            log.append(entry)

            if r.status in (301, 302, 307, 308) and location:
                pl = urllib.parse.urlparse(location)
                if pl.hostname in ("127.0.0.1", "localhost", "0.0.0.0"):
                    location = urllib.parse.urlunparse(
                        pl._replace(netloc=f"{original_host}:{pl.port or 80}")
                    )
                    entry["location_fixed"] = location
                url = location
                time.sleep(0.3)
                continue
            break

        except Exception as e:
            entry["exception"] = str(e)
            log.append(entry)
            break

    return jsonify({"start_url": start_url, "steps": log})



@app.route("/api/hls/<int:idx>")
def api_hls_manifest(idx: int):
    """Proxy del manifiesto HLS de AceStream — evita CORS en el navegador."""
    if not (0 <= idx < len(_channels)):
        return "Not found", 404
    ch   = _channels[idx]
    peer = ch.get("peer_full", "").strip()
    if not peer:
        return "No peer configured", 400

    cfg     = _load_config()
    hls_url = f"http://{cfg['ace_host']}:{cfg['ace_port']}/ace/manifest.m3u8?id={peer}"
    return _proxy_m3u8(hls_url)


@app.route("/api/hls/seg")
def api_hls_seg():
    """Proxy de segmentos/chunkists HLS — evita CORS en el navegador."""
    enc = request.args.get("u", "")
    if not enc:
        return "Missing url param", 400
    try:
        url = base64.urlsafe_b64decode(enc.encode()).decode()
    except Exception:
        return "Bad url encoding", 400
    return _proxy_hls_resource(url)


def _proxy_m3u8(url: str):
    """Descarga un manifiesto M3U8 y reescribe todas las URLs para pasar por Flask."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VLC/3.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            content  = r.read().decode("utf-8")
            final_url = r.url  # puede haber redirect
    except Exception as e:
        return Response(f"# Error fetching manifest: {e}", 502,
                        content_type="application/vnd.apple.mpegurl")

    base = final_url.rsplit("/", 1)[0] + "/"
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            abs_url = stripped if stripped.startswith("http") else base + stripped
            enc = base64.urlsafe_b64encode(abs_url.encode()).decode()
            lines.append(f"/api/hls/seg?u={enc}")
        else:
            lines.append(line)

    return Response("\n".join(lines), 200,
                    content_type="application/vnd.apple.mpegurl",
                    headers={"Cache-Control": "no-cache"})


def _proxy_hls_resource(url: str):
    """Descarga un chunklist o segmento TS y lo sirve al navegador."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VLC/3.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
            ct   = r.headers.get("Content-Type", "application/octet-stream")
            final_url = r.url
    except Exception as e:
        return Response(f"Error: {e}", 502)

    # Si es un sub-manifiesto (chunklist) también hay que reescribir sus URLs
    if "mpegurl" in ct.lower() or url.split("?")[0].endswith(".m3u8"):
        return _proxy_m3u8(final_url if final_url != url else url)

    return Response(data, 200, content_type=ct,
                    headers={"Cache-Control": "no-cache"})


@app.route("/api/test/ping")
def api_test_ping():
    """Comprueba si el proxy AceStream local está alcanzable."""
    cfg  = _load_config()
    base = f"http://{cfg['ace_host']}:{cfg['ace_port']}/"
    result = _test_url(base, timeout=3)
    return jsonify({"ok": True, "host": cfg["ace_host"],
                    "port": cfg["ace_port"], **result})


@app.route("/api/test/<int:idx>")
def api_test_channel(idx: int):
    """Prueba el stream de un canal concreto."""
    if not (0 <= idx < len(_channels)):
        return jsonify({"ok": False, "status": "not_found"}), 404
    ch   = _channels[idx]
    peer = ch.get("peer_full", "").strip()
    if not peer:
        return jsonify({"ok": False, "status": "no_peer", "latency_ms": 0})
    url    = f"{ace_base()}{peer}"
    result = _test_url(url, timeout=6)
    return jsonify({"ok": True, "id": idx, **result})


@app.route("/api/test/batch", methods=["POST"])
def api_test_batch():
    """Prueba un lote de IDs en paralelo. Body: {ids: [0,1,2,...]}"""
    ids = (request.json or {}).get("ids", [])
    if not ids:
        return jsonify({"ok": False, "error": "No ids"}), 400

    def test_one(idx):
        if not (0 <= idx < len(_channels)):
            return {"id": idx, "status": "not_found", "latency_ms": 0}
        ch   = _channels[idx]
        peer = ch.get("peer_full", "").strip()
        if not peer:
            return {"id": idx, "status": "no_peer", "latency_ms": 0}
        url = f"{ace_base()}{peer}"
        return {"id": idx, **_test_url(url, timeout=6)}

    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(test_one, i): i for i in ids}
        for f in as_completed(futures):
            results.append(f.result())

    return jsonify({"ok": True, "results": results})


@app.route("/api/config", methods=["GET"])
def api_config_get():
    return jsonify(_load_config())


@app.route("/api/config", methods=["POST"])
def api_config_set():
    data = request.json or {}
    cfg  = _load_config()
    for key in ("ace_host", "ace_port", "ace_path", "nas_path"):
        if key in data:
            cfg[key] = str(data[key]).strip()
    if "jellyfin_mode" in data:
        cfg["jellyfin_mode"] = bool(data["jellyfin_mode"])
    _save_config(cfg)
    return jsonify({"ok": True, "config": cfg, "ace_base": ace_base(cfg)})


@app.route("/api/stats")
def api_stats():
    counts  = Counter(ch.get("status", "") for ch in _channels)
    gcounts = Counter(ch.get("group", "")  for ch in _channels)
    return jsonify({
        "total":         len(_channels),
        "status_counts": dict(counts),
        "group_counts":  {g: c for g, c in sorted(gcounts.items())},
        "path":          _m3u_path,
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if os.path.isfile(M3U_FILE):
        load_m3u(M3U_FILE)
        print(f"OK  Cargados {len(_channels)} canales desde {M3U_FILE}")

    print("\n  IPTV Manager arrancando en http://localhost:5000\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
