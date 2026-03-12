"""Dedicated scraper for NEW ERA page."""
import json
import re

from .common import CAT_NAMES, dedup_by_peer, fetch_html, html_to_lines, infer_quality


def scrape(url: str, timeout_sec: int) -> list[dict]:
    html = fetch_html(url, timeout_sec)
    parsed = _parse_from_next_data(html)
    if parsed:
        return dedup_by_peer(parsed)
    return dedup_by_peer(_parse_with_regex(html))


def _parse_from_next_data(html: str) -> list[dict]:
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except Exception:
        return []
    found: list[dict] = []
    _walk_json(data, found)
    return found


def _walk_json(obj, found: list, depth: int = 0):
    if depth > 15:
        return
    if isinstance(obj, list):
        parsed = _try_channel_list(obj)
        if parsed:
            found.extend(parsed)
            return
        for item in obj:
            _walk_json(item, found, depth + 1)
    elif isinstance(obj, dict):
        for value in obj.values():
            _walk_json(value, found, depth + 1)


def _try_channel_list(lst: list) -> list[dict]:
    if not lst or not isinstance(lst[0], dict):
        return []
    sample = lst[0]
    peer_key = _find_key(sample, ["id", "peer", "hash", "aceId", "acestream_id"])
    name_key = _find_key(sample, ["name", "title", "canal", "channel", "nombre"])
    category_key = _find_key(sample, ["category", "group", "categoria", "grupo"])
    source_key = _find_key(sample, ["source", "fuente", "tag", "etiqueta"])
    quality_key = _find_key(sample, ["quality", "calidad", "resolution"])
    if not (peer_key and name_key):
        return []

    out = []
    for item in lst:
        if not isinstance(item, dict):
            continue
        peer = str(item.get(peer_key, "")).strip()
        channel = str(item.get(name_key, "")).strip()
        if not peer or not channel or len(peer) < 20:
            continue
        group = str(item.get(category_key, "DEPORTES")).strip().upper() if category_key else "DEPORTES"
        source = str(item.get(source_key, "")).strip() if source_key else ""
        quality = str(item.get(quality_key, "")).strip().upper() if quality_key else ""
        out.append(
            {
                "group": group if group in CAT_NAMES else "OTROS",
                "channel": channel,
                "quality": quality,
                "source": source,
                "peer_full": peer,
            }
        )
    return out


def _find_key(d: dict, candidates: list[str]) -> str | None:
    dl = {k.lower(): k for k in d}
    for c in candidates:
        if c.lower() in dl:
            return dl[c.lower()]
    return None


def _parse_with_regex(html: str) -> list[dict]:
    lines = html_to_lines(html)
    peer_re = re.compile(r"^[0-9a-fA-F]{40}$")
    junk = {"copiar id reproducir", "copiar", "reproducir", "id"}
    out = []
    seen_hash = set()
    current_group = "OTROS"

    for i, line in enumerate(lines):
        upper = line.upper().strip("#").strip()
        if upper in CAT_NAMES:
            current_group = upper
            continue
        if not peer_re.match(line):
            continue
        peer = line
        if peer in seen_hash:
            continue
        seen_hash.add(peer)

        raw_name = ""
        for back in range(1, 7):
            prev = lines[i - back] if i - back >= 0 else ""
            if prev.lower() in junk or peer_re.match(prev):
                continue
            if len(prev) > 4 and not prev.isdigit():
                raw_name = prev
                break
        if not raw_name:
            continue

        source = ""
        channel = raw_name
        if " --> " in raw_name:
            left, source = raw_name.rsplit(" --> ", 1)
            channel = left.strip()

        out.append(
            {
                "group": current_group,
                "channel": channel,
                "quality": infer_quality(raw_name),
                "source": source,
                "peer_full": peer,
            }
        )
    return out
