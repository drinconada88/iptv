"""Health-check orchestration: background thread and manual test helpers.

Runs a daily full scan at 05:00 and supports manual per-channel or batch checks.
Reads/writes state.health_cache and state.health_meta under state.health_lock.
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

DAILY_CHECK_HOUR = 5
DAILY_CHECK_MINUTE = 0


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
    meta["next_run_in_sec"] = _seconds_until_next_daily()
    return health_payload(state.channels, cache, meta, cfg)


def test_channel(idx: int) -> dict | None:
    """Manual single-channel test. Returns result dict or None if idx invalid."""
    if not (0 <= idx < len(state.channels)):
        return None
    ch = state.channels[idx]
    if not bool(ch.get("enabled", True)):
        return {"ok": False, "status": "disabled", "latency_ms": 0, "detail": "disabled"}
    peer = (ch.get("peer_full") or "").strip()
    if not peer:
        return {"ok": False, "status": "no_peer", "latency_ms": 0}

    url = f"{ace_base()}{peer}"
    result = test_url(url, timeout=7)
    now = int(time.time())
    with state.health_lock:
        health_update_for_peer(state.health_cache, peer, result, now)
        state.health_meta["last_run_at"] = now
        state.health_meta["last_batch_count"] = 1
    save_health_cache(state.health_cache)
    return {"ok": True, "id": idx, **result}


def test_batch(group: str | None = None, ids: list[int] | None = None) -> dict:
    """Manual batch check over all channels, a group, or selected ids."""
    cfg = health_cfg(load_config())
    timeout = max(7, int(cfg.get("timeout_sec", 7)))

    selected_ids = set()
    if ids:
        for raw in ids:
            try:
                selected_ids.add(int(raw))
            except Exception:
                continue

    target = []
    for ch in state.channels:
        if not bool(ch.get("enabled", True)):
            continue
        if selected_ids and int(ch.get("id", -1)) not in selected_ids:
            continue
        if group and (ch.get("group") or "") != group:
            continue
        target.append(ch)

    base = ace_base()
    now = int(time.time())
    checked = 0
    status_counts = {"online": 0, "offline": 0, "unknown": 0}
    results: dict[int, dict] = {}

    for ch in target:
        idx = int(ch.get("id", -1))
        peer = (ch.get("peer_full") or "").strip()
        if not peer:
            result = {"status": "no_peer", "latency_ms": 0, "detail": ""}
        else:
            result = test_url(f"{base}{peer}", timeout=timeout)
            checked += 1
            time.sleep(0.12)

        st = str(result.get("status") or "unknown").lower()
        if st == "online":
            status_counts["online"] += 1
        elif st in {"offline", "timeout", "error"}:
            status_counts["offline"] += 1
        else:
            status_counts["unknown"] += 1

        results[idx] = {
            "status": st,
            "latency_ms": int(result.get("latency_ms") or 0),
            "detail": str(result.get("detail") or "")[:120],
        }
        if peer:
            with state.health_lock:
                health_update_for_peer(state.health_cache, peer, result, now)

    with state.health_lock:
        state.health_meta["last_run_at"] = int(time.time())
        state.health_meta["last_batch_count"] = checked
        state.health_meta["last_run_type"] = "manual_batch"
    if checked:
        save_health_cache(state.health_cache)

    return {
        "ok": True,
        "scope": "selected" if selected_ids else ("group" if group else "all"),
        "group": group or "",
        "selected_count": len(selected_ids),
        "total_target": len(target),
        "checked": checked,
        "status_counts": status_counts,
        "results": results,
    }


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
            if _is_daily_run_due():
                _run_daily_health_cycle()
            time.sleep(20)
        except Exception as e:
            logger.warning("auto_health_loop error: %s", e)
            time.sleep(30)


def _start_auto_health_thread():
    if getattr(_start_auto_health_thread, "_started", False):
        return
    t = threading.Thread(target=_auto_health_loop, daemon=True, name="auto-health")
    t.start()
    _start_auto_health_thread._started = True


def _seconds_until_next_daily(now: float | None = None) -> int:
    now_ts = now or time.time()
    local = time.localtime(now_ts)
    target = time.struct_time(
        (
            local.tm_year,
            local.tm_mon,
            local.tm_mday,
            DAILY_CHECK_HOUR,
            DAILY_CHECK_MINUTE,
            0,
            local.tm_wday,
            local.tm_yday,
            local.tm_isdst,
        )
    )
    target_ts = time.mktime(target)
    if target_ts <= now_ts:
        target_ts += 24 * 60 * 60
    return max(0, int(target_ts - now_ts))


def _today_key(now: float | None = None) -> str:
    t = time.localtime(now or time.time())
    return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"


def _is_daily_run_due(now: float | None = None) -> bool:
    now_ts = now or time.time()
    local = time.localtime(now_ts)
    # Strict cron-like behavior: run only inside the exact scheduled minute.
    if not (local.tm_hour == DAILY_CHECK_HOUR and local.tm_min == DAILY_CHECK_MINUTE):
        return False
    with state.health_lock:
        last_key = str(state.health_meta.get("last_daily_run_key", "") or "")
    return last_key != _today_key(now_ts)


def _run_daily_health_cycle():
    if not state.manual_test_lock.acquire(blocking=False):
        return
    try:
        with state.health_lock:
            state.health_meta["running"] = True
            state.health_meta["last_run_type"] = "daily"

        test_batch(group=None)

        with state.health_lock:
            state.health_meta["last_daily_run_key"] = _today_key()
            state.health_meta["running"] = False
    finally:
        with state.health_lock:
            state.health_meta["running"] = False
        state.manual_test_lock.release()
