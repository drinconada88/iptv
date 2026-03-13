import time


def health_cfg(cfg: dict) -> dict:
    enabled = bool(cfg.get("auto_check_enabled", True))
    try:
        minutes = float(cfg.get("auto_check_minutes", 2.0) or 2.0)
    except Exception:
        minutes = 2.0
    try:
        batch = int(cfg.get("auto_check_batch_size", 8) or 8)
    except Exception:
        batch = 8
    try:
        timeout = int(cfg.get("auto_check_timeout_sec", 20) or 20)
    except Exception:
        timeout = 20
    return {
        "enabled": enabled,
        "minutes": max(0.5, minutes),
        "batch_size": max(1, min(25, batch)),
        "timeout_sec": max(5, min(60, timeout)),
    }


def channel_base_cooldown(status: str) -> int:
    st = (status or "").upper()
    if st == "MAIN":
        return 120
    if st == "TEST":
        return 240
    if st == "BACKUP":
        return 480
    return 360


def health_update_for_peer(cache: dict, peer: str, result: dict, now_ts: int):
    prev = cache.get(peer, {})
    prev_fail = int(prev.get("fail_count") or 0)
    prev_status = str(prev.get("status") or "unknown").lower()
    status = (result.get("status") or "error").lower()

    if status == "online":
        fail_count = 0
        final_status = "online"
    else:
        fail_count = min(10, prev_fail + 1)
        # Require 2 consecutive failures before changing a previously-good
        # status.  A single transient error (network hiccup, AceStream startup)
        # should not flip the channel to offline.
        if fail_count < 2 and prev_status in ("online", "unknown"):
            final_status = prev_status
        else:
            final_status = status

    cache[peer] = {
        "status": final_status,
        "latency_ms": int(result.get("latency_ms") or 0),
        "detail": str(result.get("detail") or "")[:120],
        "checked_at": now_ts,
        "fail_count": fail_count,
    }


def pick_health_candidates(channels: list, cache: dict, batch_size: int) -> list:
    now = int(time.time())
    rows = []
    for ch in channels:
        if not bool(ch.get("enabled", True)):
            continue
        peer = (ch.get("peer_full") or "").strip()
        if not peer:
            continue
        h = cache.get(peer, {})
        last = int(h.get("checked_at") or 0)
        fail = int(h.get("fail_count") or 0)
        base = channel_base_cooldown(ch.get("status", ""))
        if fail > 0:
            base *= min(6, 1 + fail)
        if now - last < base:
            continue
        pri = {"MAIN": 0, "TEST": 1, "BACKUP": 2}.get(ch.get("status", "").upper(), 3)
        rows.append((pri, last, ch))
    rows.sort(key=lambda x: (x[0], x[1]))
    return [ch for _, _, ch in rows[:batch_size]]


def health_payload(channels: list, cache: dict, meta: dict, cfg: dict) -> dict:
    now = int(time.time())
    rows = {}
    for ch in channels:
        idx = ch["id"]
        peer = (ch.get("peer_full") or "").strip()
        if not bool(ch.get("enabled", True)):
            rows[idx] = {"status": "disabled", "latency_ms": 0, "detail": "", "checked_at": 0}
            continue
        if not peer:
            rows[idx] = {"status": "no_peer", "latency_ms": 0, "detail": "", "checked_at": 0}
            continue
        rows[idx] = cache.get(peer, {"status": "unknown", "latency_ms": 0, "detail": "", "checked_at": 0})

    last = int(meta.get("last_run_at", 0) or 0)
    next_run = int(meta.get("next_run_in_sec", 0) or 0)
    if not next_run and last:
        next_run = max(0, int(cfg["minutes"] * 60) - (now - last))
    return {
        "ok": True,
        "running": bool(meta.get("running", False)),
        "last_run_at": last,
        "last_batch_count": int(meta.get("last_batch_count", 0) or 0),
        "last_run_type": str(meta.get("last_run_type", "") or ""),
        "interval_minutes": cfg["minutes"],
        "next_run_in_sec": next_run,
        "results": rows,
    }

