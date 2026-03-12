import re

from .constants import QUALITY_SET, STATUS_ORDER, STATUSES


def attr(line: str, name: str) -> str:
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
    q = tokens.pop().upper() if tokens and tokens[-1].upper() in QUALITY_SET else ""
    return " ".join(tokens), q, ps, source.strip()


def peer_short(full: str) -> str:
    return full[-4:] if len(full) >= 4 else full


def load_m3u(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    channels: list = []
    seen: set = set()
    pending_status: str | None = None

    for i, line in enumerate(lines):
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

        is_disabled = url_raw.startswith("# ") or url_raw.startswith("#http")
        url = url_raw.lstrip("# ") if is_disabled else url_raw
        peer_full = url.split("?id=", 1)[-1].strip() if "?id=" in url else ""

        raw = re.search(r",\s*(.+)$", extinf)
        raw = raw.group(1).strip() if raw else ""
        channel, quality, _, source = parse_display_name(raw)

        group = attr(extinf, "group-title")
        key = (group, channel)

        if pending_status:
            status = pending_status
            pending_status = None
        elif is_disabled:
            status = "DISABLED"
        else:
            status = "MAIN" if key not in seen else "BACKUP"
        seen.add(key)

        channels.append(
            {
                "id": len(channels),
                "group": group,
                "channel": channel,
                "quality": quality,
                "source": source,
                "peer_full": peer_full,
                "tvg_id": attr(extinf, "tvg-id"),
                "tvg_logo": attr(extinf, "tvg-logo"),
                "status": status,
                "notes": "",
            }
        )

    return channels


def write_m3u(
    channels: list,
    output_path: str,
    epg_url: str,
    ace_base_url: str,
    jellyfin_mode: bool = False,
) -> dict:
    def _key(c):
        return (
            c.get("group", ""),
            c.get("channel", ""),
            STATUS_ORDER.get(c.get("status", "BACKUP"), 99),
        )

    chans = sorted(channels, key=_key)
    out = [f'#EXTM3U url-tvg="{epg_url}" refresh="3600"', "#EXTVLCOPT:network-caching=1000", ""]

    cur_group = cur_channel = None
    for ch in chans:
        status = ch.get("status", "MAIN").upper()
        group = ch.get("group", "")
        channel = ch.get("channel", "")
        quality = ch.get("quality", "")
        source = ch.get("source", "")
        peer = ch.get("peer_full", "").strip()
        tvg_id = ch.get("tvg_id", "")
        tvg_logo = ch.get("tvg_logo", "")
        notes = ch.get("notes", "")

        if group != cur_group:
            cur_group = group
            cur_channel = None
            out += ["", "#" * 52, f"# CATEGORÍA: {group}", "#" * 52, ""]

        if channel != cur_channel:
            cur_channel = channel
            out += [
                f"# {'─' * 10} Canal: {channel} {'─' * 10}",
                f"# TVG-ID : {tvg_id}",
                f"# Logo   : {tvg_logo}",
                "",
            ]

        ps = peer_short(peer)
        meta = []
        if source:
            meta.append(f"Fuente: {source}")
        if quality:
            meta.append(f"Calidad: {quality}")
        if ps:
            meta.append(f"Peer: {ps}")
        meta.append(f"Estado: {status}")
        if notes:
            meta.append(f"Notas: {notes}")
        out.append("# " + "  |  ".join(meta))

        if jellyfin_mode:
            display = f"{channel} | {ps}" if ps else channel
        else:
            parts = [channel]
            if quality:
                parts.append(quality)
            if source:
                parts.append(source)
            if ps:
                parts.append(ps)
            display = " | ".join(parts)

        extinf = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" group-title="{group}",{display}'
        url = f"{ace_base_url}{peer}"

        if status == "DISABLED":
            out += ["# DISABLED", f"# {extinf}", f"# {url}", ""]
        else:
            out += [extinf, url, ""]

    out.append("")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    return {s: sum(1 for c in chans if c.get("status", "").upper() == s) for s in STATUSES}

