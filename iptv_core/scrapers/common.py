"""Common helpers for web sync scrapers."""
import re
import urllib.request

from iptv_core.constants import QUALITY_SET

CAT_NAMES = {
    "1RFEF",
    "DAZN",
    "DEPORTES",
    "EUROSPORT",
    "EVENTOS",
    "FORMULA 1",
    "FUTBOL INT",
    "HYPERMOTION",
    "LA LIGA",
    "LIGA DE CAMPEONES",
    "LIGA ENDESA",
    "MOTOR",
    "MOVISTAR",
    "MOVISTAR DEPORTES",
    "NBA",
    "SPORT TV",
    "TDT",
    "TENNIS",
    "UFC",
    "OTROS",
}


def fetch_html(url: str, timeout_sec: int) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as r:
        return r.read().decode("utf-8", errors="replace")


def dedup_by_peer(channels: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for ch in channels:
        peer = str(ch.get("peer_full", "")).strip()
        if not peer or peer in seen:
            continue
        seen.add(peer)
        out.append(ch)
    return out


def html_to_lines(html: str) -> list[str]:
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    return [l.strip() for l in text.splitlines() if l.strip()]


def infer_quality(text: str) -> str:
    tokens = [t.strip().upper() for t in re.split(r"[|/()\-\s]+", text) if t.strip()]
    for t in tokens:
        if t in QUALITY_SET:
            return t
    return ""

