"""
IPTV Manager  —  Flask web application
Ejecutar:  python app.py
Abrir:     http://localhost:5000
"""
import copy
import json
import os
import re
from collections import Counter

from flask import Flask, jsonify, render_template, request, send_file

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
M3U_FILE = os.path.join(BASE_DIR, "lista_iptv.m3u")
ACE_BASE = "http://192.168.1.169:8081/ace/getstream?id="
EPG_URL  = (
    "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/"
    "refs/heads/master/guiatv.xml,"
    "https://epgshare01.online/epgshare01/epg_ripper_NL1.xml.gz"
)

STATUSES     = ["MAIN", "BACKUP", "TEST", "DISABLED"]
QUALITY_SET  = {"FHD", "HD", "SD", "4K"}
STATUS_ORDER = {s: i for i, s in enumerate(STATUSES)}

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


def write_m3u(channels: list, output_path: str) -> dict:
    """Write clean structured M3U. Returns status counts."""
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

        parts = [channel]
        if quality: parts.append(quality)
        if source:  parts.append(source)
        if ps:      parts.append(ps)

        extinf = (f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" '
                  f'group-title="{group}",{" | ".join(parts)}')
        url = f"{ACE_BASE}{peer}"

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
    path = (request.json or {}).get("path", _m3u_path)
    stats = write_m3u(_channels, path)
    _m3u_path = path
    return jsonify({"ok": True, "stats": stats, "path": path})


@app.route("/api/export")
def api_export():
    tmp = os.path.join(BASE_DIR, "_export_tmp.m3u")
    write_m3u(_channels, tmp)
    return send_file(tmp, as_attachment=True,
                     download_name="lista_iptv_clean.m3u",
                     mimetype="audio/x-mpegurl")


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
