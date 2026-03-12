"""Channel business logic: CRUD, persistence and web sync.

All mutations go through this service so routes stay thin.
"""
import copy
import os

from .config_store import load_config
from .constants import EPG_URL, EXPORT_TMP, TMP_DIR
from .m3u_codec import load_m3u as codec_load_m3u
from .m3u_codec import write_m3u as codec_write_m3u
from .state import state
from .sync_sources import run_sync_sources

EDITABLE_FIELDS = [
    "channel", "group", "quality", "source",
    "peer_full", "tvg_id", "tvg_logo", "status", "notes",
]


# ── Acexy base URL ────────────────────────────────────────────────────────────

def ace_base(cfg: dict | None = None) -> str:
    c = cfg or load_config()
    return f"http://{c['ace_host']}:{c['ace_port']}{c['ace_path']}"


# ── Read ──────────────────────────────────────────────────────────────────────

def get_channel(idx: int) -> dict | None:
    return state.channels[idx] if 0 <= idx < len(state.channels) else None


# ── Write ─────────────────────────────────────────────────────────────────────

def load_from_file(path: str) -> list:
    state.channels = codec_load_m3u(path)
    state.m3u_path = path
    return state.channels


def _reindex():
    for i, ch in enumerate(state.channels):
        ch["id"] = i


def update_channel(idx: int, data: dict) -> dict | None:
    ch = get_channel(idx)
    if ch is None:
        return None
    for field in EDITABLE_FIELDS:
        if field in data:
            ch[field] = data[field]
    return ch


def batch_update_channels(ids: list[int], data: dict) -> tuple[list[dict], list[int]]:
    """Apply the same patch to many channels, returning updated and missing ids."""
    updated: list[dict] = []
    missing: list[int] = []
    for idx in ids:
        ch = update_channel(idx, data)
        if ch is None:
            missing.append(idx)
        else:
            updated.append(ch)
    return updated, missing


def delete_channel(idx: int) -> bool:
    if not (0 <= idx < len(state.channels)):
        return False
    state.channels.pop(idx)
    _reindex()
    return True


def reorder_channels(order: list):
    id_map = {ch["id"]: ch for ch in state.channels}
    reordered = [id_map[i] for i in order if i in id_map]
    seen = set(order)
    for ch in state.channels:
        if ch["id"] not in seen:
            reordered.append(ch)
    state.channels = reordered
    _reindex()


def create_channel(data: dict) -> dict:
    ch = {field: data.get(field, "") for field in EDITABLE_FIELDS}
    ch["id"] = len(state.channels)
    if not ch.get("status"):
        ch["status"] = "BACKUP"
    state.channels.append(ch)
    return ch


def duplicate_channel(idx: int) -> dict | None:
    ch = get_channel(idx)
    if ch is None:
        return None
    dup = copy.deepcopy(ch)
    dup["status"] = "BACKUP"
    state.channels.insert(idx + 1, dup)
    _reindex()
    return state.channels[idx + 1]


# ── Persistence ───────────────────────────────────────────────────────────────

def save_to_file(path: str | None = None) -> dict:
    from .backup_service import create_backup
    target = path or state.m3u_path
    backup = create_backup()
    cfg = load_config()
    stats = codec_write_m3u(
        channels=state.channels,
        output_path=target,
        epg_url=EPG_URL,
        ace_base_url=ace_base(cfg),
        jellyfin_mode=False,
    )
    state.m3u_path = target

    nas_result = None
    nas_path = cfg.get("nas_path", "").strip()
    if nas_path:
        try:
            codec_write_m3u(
                channels=state.channels,
                output_path=nas_path,
                epg_url=EPG_URL,
                ace_base_url=ace_base(cfg),
                jellyfin_mode=cfg.get("jellyfin_mode", False),
            )
            nas_result = {"ok": True, "path": nas_path}
        except Exception as e:
            nas_result = {"ok": False, "path": nas_path, "error": str(e)}

    return {"stats": stats, "path": target, "nas": nas_result, "backup": backup}


def export_to_tmp() -> str:
    """Write current channels to a temp file for download. Returns the path."""
    os.makedirs(TMP_DIR, exist_ok=True)
    cfg = load_config()
    codec_write_m3u(
        channels=state.channels,
        output_path=EXPORT_TMP,
        epg_url=EPG_URL,
        ace_base_url=ace_base(cfg),
    )
    return EXPORT_TMP


# ── Web sync ──────────────────────────────────────────────────────────────────

def sync_from_web() -> dict:
    cfg = load_config()
    known_peers = {ch.get("peer_full", "") for ch in state.channels}
    result = run_sync_sources(cfg, known_peers)

    added = []
    for ch in result.get("new_channels", []):
        peer = ch.get("peer_full", "")
        if not peer or peer in known_peers:
            continue
        ch["id"] = len(state.channels)
        state.channels.append(ch)
        known_peers.add(peer)
        added.append(ch)

    return {
        "found": result.get("found", 0),
        "added": len(added),
        "skipped": result.get("skipped", 0),
        "sources": result.get("sources", []),
        "new": [
            {
                "channel": c["channel"],
                "group": c["group"],
                "quality": c.get("quality", ""),
                "source": c.get("source", ""),
                "peer": c["peer_full"][-4:],
            }
            for c in added
        ],
    }
