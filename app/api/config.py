"""Config and stats routes."""
from collections import Counter

from flask import Blueprint, jsonify, request

from app.domain.state import state
from app.persistence.config_store import load_config, save_config
from app.services.channels_service import ace_base

config_bp = Blueprint("config", __name__)


@config_bp.route("/api/config", methods=["GET"])
def api_config_get():
    return jsonify(load_config())


@config_bp.route("/api/config", methods=["POST"])
def api_config_set():
    data = request.get_json(silent=True) or {}
    cfg = load_config()

    for key in ("ace_host", "ace_port", "ace_path", "nas_path"):
        if key in data:
            cfg[key] = str(data[key]).strip()

    if "jellyfin_mode" in data:
        cfg["jellyfin_mode"] = bool(data["jellyfin_mode"])
    if "auto_check_enabled" in data:
        cfg["auto_check_enabled"] = bool(data["auto_check_enabled"])
    if "sync_sources" in data and isinstance(data["sync_sources"], list):
        cfg["sync_sources"] = data["sync_sources"]

    _clamp_float(cfg, data, "auto_check_minutes", lo=0.5)
    _clamp_int(cfg, data, "auto_check_batch_size", lo=1, hi=25)
    _clamp_int(cfg, data, "auto_check_timeout_sec", lo=2, hi=10)

    save_config(cfg)
    return jsonify({"ok": True, "config": cfg, "ace_base": ace_base(cfg)})


@config_bp.route("/api/stats")
def api_stats():
    counts = Counter(ch.get("status", "") for ch in state.channels)
    gcounts = Counter(ch.get("group", "") for ch in state.channels)
    disabled_count = sum(1 for ch in state.channels if not bool(ch.get("enabled", True)))
    return jsonify(
        {
            "total": len(state.channels),
            "status_counts": dict(counts),
            "disabled_count": disabled_count,
            "group_counts": {g: c for g, c in sorted(gcounts.items())},
            "path": state.m3u_path,
        }
    )


def _clamp_float(cfg: dict, data: dict, key: str, lo: float):
    if key in data:
        try:
            cfg[key] = max(lo, float(data[key]))
        except Exception:
            pass


def _clamp_int(cfg: dict, data: dict, key: str, lo: int, hi: int):
    if key in data:
        try:
            cfg[key] = max(lo, min(hi, int(data[key])))
        except Exception:
            pass

