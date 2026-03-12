"""Health-check routes: status, manual test, batch test and ping."""
from flask import Blueprint, jsonify, request

from iptv_core.acexy_client import test_url
from iptv_core.channel_service import ace_base
from iptv_core.config_store import load_config
from iptv_core.health_service import (
    ensure_runtime_background,
    get_health_payload,
    test_batch,
    test_channel,
)
from iptv_core.state import state

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/health")
def api_health():
    ensure_runtime_background()
    return jsonify(get_health_payload())


@health_bp.route("/api/test/ping")
def api_test_ping():
    """Check whether the local AceStream proxy is reachable."""
    cfg = load_config()
    base = f"http://{cfg['ace_host']}:{cfg['ace_port']}/"
    result = test_url(base, timeout=3)
    return jsonify({"ok": True, "host": cfg["ace_host"], "port": cfg["ace_port"], **result})


@health_bp.route("/api/test/<int:idx>")
def api_test_channel(idx: int):
    """Test the stream for a single channel (safe: max one concurrent test)."""
    if not (0 <= idx < len(state.channels)):
        return jsonify({"ok": False, "status": "not_found"}), 404

    if not state.manual_test_lock.acquire(blocking=False):
        return jsonify(
            {"ok": False, "status": "busy", "latency_ms": 0, "detail": "another_check_running"}
        ), 429

    try:
        result = test_channel(idx)
        if result is None:
            return jsonify({"ok": False, "status": "not_found"}), 404
        return jsonify(result)
    finally:
        state.manual_test_lock.release()


@health_bp.route("/api/test/batch", methods=["POST"])
def api_test_batch():
    """Batch check for all channels, group, or selected ids."""
    payload = request.get_json(silent=True) or {}
    group = str(payload.get("group", "")).strip() or None
    raw_ids = payload.get("ids", [])
    ids = raw_ids if isinstance(raw_ids, list) else []

    if not state.manual_test_lock.acquire(blocking=False):
        return jsonify({"ok": False, "status": "busy", "detail": "another_check_running"}), 429

    try:
        result = test_batch(group=group, ids=ids)
        return jsonify(result)
    finally:
        state.manual_test_lock.release()
