"""Dedicated scraper for acestreamid.com."""
import re

from .common import CAT_NAMES, dedup_by_peer, fetch_html, html_to_lines, infer_quality

PEER_RE = re.compile(r"[0-9a-fA-F]{40}")


def scrape(url: str, timeout_sec: int) -> list[dict]:
    html = fetch_html(url, timeout_sec)
    lines = html_to_lines(html)

    out = []
    seen = set()
    current_group = "OTROS"

    for i, line in enumerate(lines):
        group_candidate = _group_from_text(line)
        if group_candidate:
            current_group = group_candidate

        for match in PEER_RE.findall(line):
            peer = match.strip()
            if peer in seen:
                continue
            seen.add(peer)

            name = _guess_channel_name(lines, i)
            if not name:
                continue

            out.append(
                {
                    "group": current_group,
                    "channel": name,
                    "quality": infer_quality(name),
                    "source": "ACESTREAMID",
                    "peer_full": peer,
                }
            )

    return dedup_by_peer(out)


def _guess_channel_name(lines: list[str], i: int) -> str:
    # Search nearby text around the line where peer appears.
    for delta in (0, -1, -2, -3, 1, 2):
        j = i + delta
        if j < 0 or j >= len(lines):
            continue
        cand = lines[j].strip()
        if not cand:
            continue
        if PEER_RE.search(cand):
            # remove peer id from same line
            cand = PEER_RE.sub("", cand).strip(" -|:•")
        if not cand:
            continue
        if len(cand) < 4:
            continue
        low = cand.lower()
        if low in {"copy", "copiar", "id", "acestream id", "peer"}:
            continue
        return cand[:180]
    return ""


def _group_from_text(text: str) -> str:
    up = text.upper().strip("# ").strip()
    if up in CAT_NAMES:
        return up

    # Heuristic buckets by keywords commonly seen on acestreamid pages.
    if "DAZN" in up:
        return "DAZN"
    if "CHAMPIONS" in up or "CAMPEONES" in up:
        return "LIGA DE CAMPEONES"
    if "LALIGA" in up or "LA LIGA" in up:
        return "LA LIGA"
    if "F1" in up or "FORMULA" in up:
        return "FORMULA 1"
    if "TENNIS" in up:
        return "TENNIS"
    if "NBA" in up:
        return "NBA"
    if "UFC" in up:
        return "UFC"
    if "MOVISTAR" in up:
        return "MOVISTAR"
    if "SPORT" in up or "DEPORT" in up:
        return "DEPORTES"
    return ""
