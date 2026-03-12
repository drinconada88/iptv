"""Health-check orchestration: background thread and manual test helpers.

Owns the auto-check loop lifecycle. Reads/writes state.health_cache and
state.health_meta under state.health_lock.
"""
import logging
import threading
import time

from .acexy_client import test_url
from .channel_service import ace_base
from .config_store import load_config, load_health_cache, save_health_cache
from .health_logic import health_cfg, health_payload, health_update_for_peer, pick_health_candidates
from .state import state

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def ensure_runtime_background():
    """Idempotent: loads health cache and starts auto-check thread once."""
    if state._booted:
        return
    with state._boot_lock:
        if state._booted:
            return
        state.health_cache = load_health_cache()
        _start_auto_health_thread()
        state._booted = True


def get_health_payload() -> dict:
    with state.health_lock:
        meta = dict(state.health_meta)
        cache = dict(state.health_cache)
    cfg = health_cfg(load_config())
    return health_payload(state.channels, cache, meta, cfg)


def test_channel(idx: int) -> dict | None:
    """Manual single-channel test. Returns result dict or None if idx invalid."""
    if not (0 <= idx < len(state.channels)):
        return None
    ch = state.channels[idx]
    peer = (ch.get("peer_full") or "").strip()
    if not peer:
        return {"ok": False, "status": "no_peer", "latency_ms": 0}

    url = f"{ace_base()}{peer}"
    result = test_url(url, timeout=6)
    now = int(time.time())
    with state.health_lock:
        health_update_for_peer(state.health_cache, peer, result, now)
        state.health_meta["last_run_at"] = now
        state.health_meta["last_batch_count"] = 1
    save_health_cache(state.health_cache)
    return {"ok": True, "id": idx, **result}


# ── Auto-check internals ──────────────────────────────────────────────────────

def _run_auto_health_cycle():
    cfg = health_cfg(load_config())
    if not cfg["enabled"]:
        return
    if not state.manual_test_lock.acquire(blocking=False):
        return

    batch_count = 0
    try:
        with state.health_lock:
            state.health_meta["running"] = True

        candidates = pick_health_candidates(state.channels, state.health_cache, cfg["batch_size"])
        base = ace_base()
        now_ts = int(time.time())
        for ch in candidates:
            peer = (ch.get("peer_full") or "").strip()
            if not peer:
                continue
            result = test_url(f"{base}{peer}", timeout=cfg["timeout_sec"])
            with state.health_lock:
                health_update_for_peer(state.health_cache, peer, result, now_ts)
            batch_count += 1
            time.sleep(0.15)

        with state.health_lock:
            state.health_meta["last_run_at"] = int(time.time())
            state.health_meta["last_batch_count"] = batch_count
            state.health_meta["running"] = False
        if batch_count:
            save_health_cache(state.health_cache)
    finally:
        with state.health_lock:
            state.health_meta["running"] = False
        state.manual_test_lock.release()


def _auto_health_loop():
    while True:
        try:
            cfg = health_cfg(load_config())
            if cfg["enabled"]:
                _run_auto_health_cycle()
            sleep_s = max(30, int(cfg["minutes"] * 60))
            time.sleep(sleep_s)
        except Exception as e:
            logger.warning("auto_health_loop error: %s", e)
            time.sleep(30)


def _start_auto_health_thread():
    if getattr(_start_auto_health_thread, "_started", False):
        return
    t = threading.Thread(target=_auto_health_loop, daemon=True, name="auto-health")
    t.start()
    _start_auto_health_thread._started = True
