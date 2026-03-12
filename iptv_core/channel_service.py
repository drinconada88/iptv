"""Channel business logic: CRUD, persistence and web sync.

All mutations go through this service so routes stay thin.
"""
import copy
import os

from .config_store import load_config
from .constants import EPG_URL, EXPORT_TMP, M3U_FILE, STATUSES, TMP_DIR
from .m3u_codec import load_m3u as codec_load_m3u
from .m3u_codec import write_m3u as codec_write_m3u
from .state import state
from .sync_sources import run_sync_sources

EDITABLE_FIELDS = [
    "channel", "group", "quality", "source",
    "peer_full", "tvg_id", "tvg_logo", "status", "enabled", "notes",
]


# ── Internal helpers ──────────────────────────────────────────────────────────
def _to_bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


# ── Acexy base URL ────────────────────────────────────────────────────────────

def ace_base(cfg: dict | None = None) -> str:
    c = cfg or load_config()
    return f"http://{c['ace_host']}:{c['ace_port']}{c['ace_path']}"


def ace_base_from_values(host: str, port: str, cfg: dict | None = None) -> str:
    c = cfg or load_config()
    ace_path = str(c.get("ace_path", "/ace/getstream?id=")).strip() or "/ace/getstream?id="
    if not ace_path.startswith("/"):
        ace_path = "/" + ace_path
    return f"http://{host}:{port}{ace_path}"


# ── Read ──────────────────────────────────────────────────────────────────────

def get_channel(idx: int) -> dict | None:
    return state.channels[idx] if 0 <= idx < len(state.channels) else None


# ── Write ─────────────────────────────────────────────────────────────────────

def load_from_file(path: str) -> list:
    state.channels = codec_load_m3u(path)
    for ch in state.channels:
        ch["status"] = str(ch.get("status") or "BACKUP").upper()
        if ch["status"] not in STATUSES:
            ch["status"] = "BACKUP"
        ch["enabled"] = _to_bool(ch.get("enabled"), default=True)
    state.m3u_path = path
    return state.channels


def _reindex():
    for i, ch in enumerate(state.channels):
        ch["id"] = i


def update_channel(idx: int, data: dict) -> dict | None:
    ch = get_channel(idx)
    if ch is None:
        return None
    prev_status = str(ch.get("status") or "BACKUP").upper()
    for field in EDITABLE_FIELDS:
        if field in data:
            ch[field] = data[field]
    if "status" in data:
        next_status = str(data.get("status") or prev_status or "BACKUP").upper()
        if next_status == "DISABLED":
            ch["enabled"] = False
            next_status = prev_status if prev_status in STATUSES else "BACKUP"
        if next_status not in STATUSES:
            next_status = "BACKUP"
        ch["status"] = next_status
    if "enabled" in data:
        ch["enabled"] = _to_bool(ch.get("enabled"), default=True)
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
    ch["status"] = str(ch.get("status") or "BACKUP").upper()
    if ch["status"] not in STATUSES:
        ch["status"] = "BACKUP"
    ch["enabled"] = _to_bool(data.get("enabled"), default=True)
    state.channels.append(ch)
    return ch


def duplicate_channel(idx: int) -> dict | None:
    ch = get_channel(idx)
    if ch is None:
        return None
    dup = copy.deepcopy(ch)
    dup["status"] = "BACKUP"
    dup["enabled"] = True
    state.channels.insert(idx + 1, dup)
    _reindex()
    return state.channels[idx + 1]


# ── Persistence ───────────────────────────────────────────────────────────────

def save_to_file(path: str | None = None) -> dict:
    from .backup_service import create_backup
    # Canonical source-of-truth: always persist to runtime M3U_FILE unless an
    # explicit path is provided by non-UI callers.
    target = path or M3U_FILE
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

    disabled_count = sum(1 for c in state.channels if not bool(c.get("enabled", True)))
    return {
        "stats": stats,
        "disabled_count": disabled_count,
        "path": target,
        "nas": nas_result,
        "backup": backup,
    }


def export_to_tmp(host: str | None = None, port: str | None = None) -> str:
    """Write current channels to a temp file for download. Returns the path."""
    os.makedirs(TMP_DIR, exist_ok=True)
    cfg = load_config()
    export_base = ace_base(cfg)
    host_v = (host or "").strip()
    port_v = (port or "").strip()
    if host_v and port_v:
        export_base = ace_base_from_values(host_v, port_v, cfg)
    codec_write_m3u(
        channels=state.channels,
        output_path=EXPORT_TMP,
        epg_url=EPG_URL,
        ace_base_url=export_base,
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
