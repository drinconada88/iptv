"""Generic fallback scraper based on peer-id regex heuristics."""
import re

from .common import dedup_by_peer, html_to_lines, infer_quality
from .common import fetch_html

PEER_RE = re.compile(r"[0-9a-fA-F]{40}")


def scrape(url: str, timeout_sec: int) -> list[dict]:
    html = fetch_html(url, timeout_sec)
    lines = html_to_lines(html)
    out = []
    seen = set()
    for i, line in enumerate(lines):
        for match in PEER_RE.findall(line):
            peer = match.strip()
            if peer in seen:
                continue
            seen.add(peer)
            channel = _guess_name(lines, i)
            if not channel:
                channel = f"Canal {peer[-4:]}"
            out.append(
                {
                    "group": "OTROS",
                    "channel": channel,
                    "quality": infer_quality(channel),
                    "source": "GENERIC",
                    "peer_full": peer,
                }
            )
    return dedup_by_peer(out)


def _guess_name(lines: list[str], idx: int) -> str:
    for delta in (0, -1, -2, -3, 1):
        j = idx + delta
        if j < 0 or j >= len(lines):
            continue
        text = lines[j]
        if PEER_RE.search(text):
            text = PEER_RE.sub("", text).strip(" -|:•")
        if len(text) >= 4:
            return text[:160]
    return ""
