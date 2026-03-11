"""
import_from_web.py — Importa canales de la web NEW ERA al M3U
Uso:
  python import_from_web.py           # añade canales nuevos
  python import_from_web.py --dry-run # solo muestra qué añadiría
  python import_from_web.py --json    # modo silencioso, devuelve JSON (lo usa app.py)
"""
import re
import sys
import json
import urllib.request
import os

# ── Config ────────────────────────────────────────────────────────────────────
IPFS_URL  = (
    "https://ipfs.io/ipns/"
    "k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004/"
    "?tab=canales"
)
M3U_FILE  = os.path.join(os.path.dirname(__file__), "lista_iptv.m3u")
APP_API   = "http://localhost:5000"
ACE_BASE  = "http://192.168.1.169:8081/ace/getstream?id="
QUALITY_SET = {"FHD", "HD", "SD", "4K"}

# Grupos que ya existen en el M3U y cómo mapear los de la web a ellos
# Los grupos nuevos (NBA, UFC) se crean solos al añadirlos
GROUP_MAP = {
    "1RFEF":             "1RFEF",
    "DAZN":              "DAZN",
    "DEPORTES":          "DEPORTES",
    "EUROSPORT":         "EUROSPORT",
    "EVENTOS":           "EVENTOS",
    "FORMULA 1":         "FORMULA 1",
    "FUTBOL INT":        "FUTBOL INT",
    "HYPERMOTION":       "HYPERMOTION",
    "LA LIGA":           "LA LIGA",
    "LIGA DE CAMPEONES": "LIGA DE CAMPEONES",
    "LIGA ENDESA":       "LIGA ENDESA",
    "MOTOR":             "MOTOR",
    "MOVISTAR":          "MOVISTAR",
    "MOVISTAR DEPORTES": "MOVISTAR DEPORTES",
    "NBA":               "NBA",        # NUEVO grupo
    "SPORT TV":          "SPORT TV",
    "TDT":               "TDT",
    "TENNIS":            "TENNIS",
    "UFC":               "UFC",        # NUEVO grupo
    "OTROS":             "OTROS",
}

DRY_RUN   = "--dry-run" in sys.argv
JSON_MODE = "--json"    in sys.argv


# ── Scraping ──────────────────────────────────────────────────────────────────

def fetch_html(url: str) -> str:
    print(f"Descargando {url} ...", file=sys.stderr if JSON_MODE else sys.stdout)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_channels_from_html(html: str) -> list[dict]:
    """
    La página guarda los canales como JSON dentro de un <script id="__NEXT_DATA__">
    o como texto plano. Intentamos JSON primero; si no, usamos regex sobre el HTML.
    """
    channels = []

    # ── Intento 1: JSON embebido (Next.js / React) ────────────────────────────
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            channels = _extract_from_next_json(data)
            if channels:
                print(f"  [JSON] Encontrados {len(channels)} canales en __NEXT_DATA__", file=sys.stderr)
                return channels
        except Exception:
            pass

    # ── Intento 2: bloques JSON sueltos ──────────────────────────────────────
    for candidate in re.findall(r'\{[^{}]{200,}\}', html):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, list):
                found = _try_list(obj)
                if found:
                    channels.extend(found)
        except Exception:
            pass
    if channels:
        channels = _dedup_by_peer(channels)
        print(f"  [JSON] Encontrados {len(channels)} canales en bloques JSON", file=sys.stderr)
        return channels

    # ── Intento 3: regex sobre HTML/texto plano ───────────────────────────────
    channels = _parse_with_regex(html)
    print(f"  [REGEX] Encontrados {len(channels)} canales", file=sys.stderr)
    return channels


def _extract_from_next_json(data: dict) -> list[dict]:
    """Navega el árbol Next.js buscando arrays de canales."""
    found = []
    _walk(data, found)
    return _dedup_by_peer(found)


def _walk(obj, found: list, depth: int = 0):
    if depth > 15:
        return
    if isinstance(obj, list):
        result = _try_list(obj)
        if result:
            found.extend(result)
            return
        for item in obj:
            _walk(item, found, depth + 1)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, found, depth + 1)


def _try_list(lst: list) -> list[dict]:
    """Intenta interpretar un array como lista de canales."""
    if not lst or not isinstance(lst[0], dict):
        return []
    sample = lst[0]
    # Busca campos típicos de un canal AceStream
    peer_key    = _find_key(sample, ["id", "peer", "hash", "aceId", "acestream_id"])
    name_key    = _find_key(sample, ["name", "title", "canal", "channel", "nombre"])
    category_key= _find_key(sample, ["category", "group", "categoria", "grupo"])
    source_key  = _find_key(sample, ["source", "fuente", "tag", "etiqueta"])
    quality_key = _find_key(sample, ["quality", "calidad", "resolution"])

    if not (peer_key and name_key):
        return []

    result = []
    for item in lst:
        if not isinstance(item, dict):
            continue
        peer = str(item.get(peer_key, "")).strip()
        name = str(item.get(name_key, "")).strip()
        if not peer or not name or len(peer) < 20:
            continue
        cat = str(item.get(category_key, "DEPORTES")).strip().upper() if category_key else "DEPORTES"
        src = str(item.get(source_key, "")).strip() if source_key else ""
        q   = str(item.get(quality_key, "")).strip().upper() if quality_key else ""
        result.append({"group": cat, "channel": name, "quality": q,
                        "source": src, "peer_full": peer})
    return result


def _find_key(d: dict, candidates: list) -> str | None:
    dl = {k.lower(): k for k in d}
    for c in candidates:
        if c.lower() in dl:
            return dl[c.lower()]
    return None


def _parse_with_regex(html: str) -> list[dict]:
    """
    Extrae canales buscando hashes hex de 40 chars y retrocediendo para
    encontrar nombre + categoría en el HTML circundante.
    """
    # Limpiamos el HTML a texto plano
    text = re.sub(r'<[^>]+>', '\n', html)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    PEER_RE  = re.compile(r'^[0-9a-fA-F]{40}$')
    JUNK     = {"copiar id reproducir", "copiar", "reproducir", "id"}

    channels  = []
    seen_hash = set()
    current_cat = "DEPORTES"

    # Detectar categoría por líneas todo en mayúsculas
    CAT_NAMES = {
        "1RFEF", "DAZN", "DEPORTES", "EUROSPORT", "EVENTOS", "FORMULA 1",
        "FUTBOL INT", "HYPERMOTION", "LA LIGA", "LIGA DE CAMPEONES",
        "LIGA ENDESA", "MOTOR", "MOVISTAR", "MOVISTAR DEPORTES", "NBA",
        "SPORT TV", "TDT", "TENNIS", "UFC", "OTROS",
    }

    for i, line in enumerate(lines):
        # Actualizar categoría
        upper = line.upper().strip("#").strip()
        if upper in CAT_NAMES:
            current_cat = upper
            continue

        if not PEER_RE.match(line):
            continue
        peer = line
        if peer in seen_hash:
            continue
        seen_hash.add(peer)

        # Buscar nombre mirando hacia atrás (hasta 6 líneas)
        raw_name = ""
        quality  = ""
        source   = ""
        for back in range(1, 7):
            prev = lines[i - back] if i - back >= 0 else ""
            if prev.lower() in JUNK or PEER_RE.match(prev):
                continue
            # ¿Es una calidad?
            if prev.upper() in QUALITY_SET and not quality:
                quality = prev.upper()
                continue
            # ¿Parece un nombre de canal?
            if len(prev) > 4 and not prev.isdigit():
                raw_name = prev
                break

        if not raw_name:
            continue

        # Parsear nombre: "DAZN 1 FHD --> NEW ERA"
        channel = raw_name
        if " --> " in raw_name:
            left, source = raw_name.rsplit(" --> ", 1)
            source = source.strip()
            tokens = left.split()
            if tokens and tokens[-1].upper() in QUALITY_SET:
                quality = tokens.pop().upper()
            channel = " ".join(tokens).strip()

        mapped_group = GROUP_MAP.get(current_cat, current_cat)
        channels.append({
            "group":     mapped_group,
            "channel":   channel,
            "quality":   quality,
            "source":    source,
            "peer_full": peer,
        })

    return channels


def _dedup_by_peer(channels: list[dict]) -> list[dict]:
    seen  = set()
    out   = []
    for ch in channels:
        p = ch.get("peer_full", "")
        if p and p not in seen:
            seen.add(p)
            out.append(ch)
    return out


# ── Comparar con M3U existente ────────────────────────────────────────────────

def existing_peers(m3u_path: str) -> set[str]:
    peers = set()
    if not os.path.isfile(m3u_path):
        return peers
    with open(m3u_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("# ")
            if "?id=" in line:
                peers.add(line.split("?id=", 1)[-1].strip())
    return peers


# ── Añadir al M3U via API ─────────────────────────────────────────────────────

def add_via_api(channels: list[dict]) -> int:
    import urllib.parse
    added = 0
    for ch in channels:
        payload = json.dumps({
            "channel":  ch["channel"],
            "group":    ch["group"],
            "quality":  ch["quality"],
            "source":   ch["source"],
            "peer_full":ch["peer_full"],
            "status":   "BACKUP",
            "tvg_id":   "",
            "tvg_logo": "",
            "notes":    "importado web NEW ERA",
        }).encode()
        req = urllib.request.Request(
            f"{APP_API}/channel/new",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                result = json.loads(r.read())
                if result.get("ok"):
                    added += 1
        except Exception as e:
            print(f"  [!] Error añadiendo {ch['channel']}: {e}")
    return added


def append_to_m3u_directly(channels: list[dict], m3u_path: str) -> int:
    """Añade canales directamente al M3U sin pasar por la API."""
    lines = []
    for ch in channels:
        peer = ch["peer_full"].strip()
        ps   = peer[-4:] if len(peer) >= 4 else peer
        parts = [ch["channel"]]
        if ch["quality"]: parts.append(ch["quality"])
        if ch["source"]:  parts.append(ch["source"])
        if ps:            parts.append(ps)
        name = " | ".join(parts)
        lines += [
            f"# Fuente: {ch['source']}  |  Calidad: {ch['quality']}  |  Peer: {ps}  |  Estado: BACKUP",
            f"# Notas: importado web NEW ERA",
            f'#EXTINF:-1 tvg-id="" tvg-logo="" group-title="{ch["group"]}",{name}',
            f"{ACE_BASE}{peer}",
            "",
        ]
    with open(m3u_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return len(channels)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # ── Modo JSON: salida limpia para app.py ──────────────────────────────────
    if JSON_MODE:
        def _out(obj):
            """Escribe JSON al buffer de bytes del stdout, sin pasar por encoding Windows."""
            data = (json.dumps(obj) + "\n").encode("utf-8")
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()

        try:
            html = fetch_html(IPFS_URL)
        except Exception as e:
            _out({"ok": False, "error": str(e)})
            sys.exit(1)
        web_channels = parse_channels_from_html(html)
        known        = existing_peers(M3U_FILE)
        new_channels = [ch for ch in web_channels if ch["peer_full"] not in known]
        for ch in new_channels:
            ch.setdefault("status",   "BACKUP")
            ch.setdefault("tvg_id",   "")
            ch.setdefault("tvg_logo", "")
            ch.setdefault("notes",    "sync web NEW ERA")
        _out({
            "ok":           True,
            "found":        len(web_channels),
            "skipped":      len(web_channels) - len(new_channels),
            "new_channels": new_channels,
        })
        return

    # ── Modo normal / dry-run ─────────────────────────────────────────────────
    sys.stdout.reconfigure(encoding="utf-8")

    try:
        html = fetch_html(IPFS_URL)
    except Exception as e:
        print(f"ERROR descargando pagina: {e}")
        sys.exit(1)

    web_channels = parse_channels_from_html(html)
    if not web_channels:
        print("No se encontraron canales en la pagina. Revisa la URL o el formato.")
        sys.exit(1)

    known        = existing_peers(M3U_FILE)
    new_channels = [ch for ch in web_channels if ch["peer_full"] not in known]
    dup_channels = [ch for ch in web_channels if ch["peer_full"] in known]

    print(f"\nPeers conocidos en M3U: {len(known)}")
    print(f"Canales encontrados en web: {len(web_channels)}")
    print(f"\n  Ya existentes (duplicados): {len(dup_channels)}")
    print(f"  NUEVOS a importar:          {len(new_channels)}")

    if not new_channels:
        print("\nNada nuevo que importar.")
        return

    print("\n--- Canales nuevos ---------------------------------------------------")
    for ch in new_channels:
        ps = ch['peer_full'][-4:]
        q  = f" [{ch['quality']}]" if ch['quality'] else ""
        print(f"  [{ch['group']:20s}] {ch['channel']}{q}  <-- {ch['source']}  ({ps})")

    if DRY_RUN:
        print("\n[DRY-RUN] Nada guardado.")
        return

    print(f"\nAnadiendo {len(new_channels)} canales a {M3U_FILE} ...")
    added = append_to_m3u_directly(new_channels, M3U_FILE)
    print(f"OK  Anadidos {added} canales al M3U.")
    print("Recarga la app (F5 en el navegador) para verlos.")


if __name__ == "__main__":
    main()
