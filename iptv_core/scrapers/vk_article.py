"""Dedicated scraper for VK article pages with channel/hash lists."""
import re
import ssl
import urllib.error
import urllib.request

from .common import dedup_by_peer, html_to_lines, infer_quality

PEER_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def scrape(url: str, timeout_sec: int) -> list[dict]:
    html = _fetch_vk_html(url, timeout_sec)
    lines = html_to_lines(html)

    out: list[dict] = []
    seen: set[str] = set()
    current_group = "OTROS"

    for i, line in enumerate(lines):
        group = _group_from_text(line)
        if group:
            current_group = group

        if not PEER_RE.match(line):
            continue
        peer = line.lower().strip()
        if peer in seen:
            continue
        seen.add(peer)

        channel = _guess_channel_name(lines, i)
        if not channel:
            channel = f"Canal {peer[-4:]}"

        out.append(
            {
                "group": current_group,
                "channel": channel,
                "quality": _quality_from_name(channel),
                "source": "VK_CHANNELS",
                "peer_full": peer,
            }
        )

    return dedup_by_peer(out)


def _guess_channel_name(lines: list[str], idx: int) -> str:
    for delta in (-1, -2, -3, -4, 1):
        j = idx + delta
        if j < 0 or j >= len(lines):
            continue
        cand = lines[j].strip().strip("-:|")
        if not cand:
            continue
        if PEER_RE.match(cand):
            continue
        if len(cand) < 4:
            continue
        low = cand.lower()
        if low in {"channels list", "copiar", "copy", "id"}:
            continue
        return cand[:180]
    return ""


def _group_from_text(text: str) -> str:
    up = text.upper()
    if "DAZN" in up:
        return "DAZN"
    if "LALIGA" in up or "LA LIGA" in up:
        return "LA LIGA"
    if "CAMPEONES" in up or "CHAMPIONS" in up:
        return "LIGA DE CAMPEONES"
    if "DEPORT" in up or "SPORT" in up:
        return "DEPORTES"
    return ""


def _quality_from_name(name: str) -> str:
    up = name.upper()
    if "1080" in up:
        return "FHD"
    if "720" in up:
        return "HD"
    return infer_quality(name)


def _fetch_vk_html(url: str, timeout_sec: int) -> str:
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
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        if isinstance(reason, ssl.SSLCertVerificationError):
            # Some networks inject SSL chains that break Python cert validation.
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as r:
                return r.read().decode("utf-8", errors="replace")
        raise

