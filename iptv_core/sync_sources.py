"""Web sync source orchestration."""

from .constants import DEFAULT_CFG
from .scrapers import SCRAPER_REGISTRY


def normalize_sources(raw_sources) -> list[dict]:
    default_sources = DEFAULT_CFG.get("sync_sources", [])
    src_list = raw_sources if isinstance(raw_sources, list) and raw_sources else default_sources
    out = []
    for i, src in enumerate(src_list):
        if not isinstance(src, dict):
            continue
        parser = str(src.get("parser", "new_era")).strip().lower() or "new_era"
        url = str(src.get("url", "")).strip()
        if not url:
            continue
        out.append(
            {
                "id": str(src.get("id") or f"src_{i+1}"),
                "name": str(src.get("name") or str(src.get("id") or f"Fuente {i+1}")),
                "enabled": bool(src.get("enabled", True)),
                "parser": parser,
                "url": url,
                "timeout_sec": _clamp_int(src.get("timeout_sec", 60), lo=5, hi=120, fallback=60),
                "priority": _clamp_int(src.get("priority", 100), lo=0, hi=9999, fallback=100),
            }
        )
    out.sort(key=lambda s: (s["priority"], s["name"].lower()))
    return out


def run_sync_sources(cfg: dict, known_peers: set[str]) -> dict:
    sources = [s for s in normalize_sources(cfg.get("sync_sources")) if s.get("enabled")]
    seen = set(known_peers)

    summary = {
        "found": 0,
        "added": 0,
        "skipped": 0,
        "new_channels": [],
        "sources": [],
    }

    for src in sources:
        sid = src["id"]
        sname = src["name"]
        parser_name = src["parser"]
        source_result = {"id": sid, "name": sname, "parser": parser_name, "ok": False}
        try:
            parser = SCRAPER_REGISTRY.get(parser_name)
            if parser is None:
                raise ValueError(f"parser no soportado: {parser_name}")

            parsed = parser(src["url"], src["timeout_sec"])
            found = len(parsed)
            added = 0
            skipped = 0
            created = []
            for ch in parsed:
                peer = str(ch.get("peer_full", "")).strip()
                if not peer:
                    skipped += 1
                    continue
                if peer in seen:
                    skipped += 1
                    continue
                seen.add(peer)
                added += 1
                created.append(
                    {
                        "group": str(ch.get("group", "OTROS")).strip() or "OTROS",
                        "channel": str(ch.get("channel", "")).strip(),
                        "quality": str(ch.get("quality", "")).strip(),
                        "source": str(ch.get("source", "")).strip(),
                        "peer_full": peer,
                        "status": "BACKUP",
                        "tvg_id": "",
                        "tvg_logo": "",
                        "notes": f"sync web {sname}",
                    }
                )

            summary["found"] += found
            summary["added"] += added
            summary["skipped"] += skipped
            summary["new_channels"].extend(created)
            source_result.update(
                {"ok": True, "found": found, "added": added, "skipped": skipped}
            )
        except Exception as e:
            source_result.update({"ok": False, "error": str(e)})
        summary["sources"].append(source_result)

    return summary


def _clamp_int(value, lo: int, hi: int, fallback: int) -> int:
    try:
        n = int(value)
    except Exception:
        return fallback
    return max(lo, min(hi, n))

