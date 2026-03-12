"""Dedicated scraper for JSON feeds with {hashes:[...]} format."""
import json
import re
import urllib.request

from .common import CAT_NAMES, dedup_by_peer, infer_quality

PEER_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def scrape(url: str, timeout_sec: int) -> list[dict]:
    data = _fetch_json(url, timeout_sec)
    rows = data.get("hashes", [])
    if not isinstance(rows, list):
        return []

    out: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue

        peer = str(item.get("hash", "")).strip().lower()
        if not PEER_RE.match(peer):
            continue

        title = str(item.get("title", "")).strip()
        if not title:
            continue

        raw_group = str(item.get("group", "")).strip().upper() or "OTROS"
        group = raw_group if raw_group in CAT_NAMES else raw_group
        tvg_id = str(item.get("tvg_id", "")).strip()
        tvg_logo = str(item.get("logo", "")).strip()

        out.append(
            {
                "group": group,
                "channel": _clean_title(title),
                "quality": _quality_from_title(title),
                "source": "HASHES_JSON",
                "peer_full": peer,
                "tvg_id": tvg_id,
                "tvg_logo": tvg_logo,
            }
        )

    return dedup_by_peer(out)


def _fetch_json(url: str, timeout_sec: int) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as r:
        text = r.read().decode("utf-8", errors="replace")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("JSON raíz inválido")
    return payload


def _clean_title(title: str) -> str:
    # Remove visual quality markers like "*" or "**" without touching the name.
    cleaned = re.sub(r"\s*\*+\s*$", "", title).strip()
    return cleaned or title.strip()


def _quality_from_title(title: str) -> str:
    up = title.upper()
    if "1080P" in up:
        return "FHD"
    if "720P" in up:
        return "HD"
    if "4K" in up:
        return "4K"
    return infer_quality(title)

