"""Shared in-memory state for the IPTV Manager.

Single source of truth for mutable runtime data. Imported by services and
blueprints — never mutated directly from route handlers.
"""
import threading

from .constants import M3U_FILE


class AppState:
    def __init__(self):
        self.channels: list = []
        self.m3u_path: str = M3U_FILE

        self.health_cache: dict = {}
        self.health_meta: dict = {
            "last_run_at": 0,
            "running": False,
            "last_batch_count": 0,
        }

        self.health_lock = threading.Lock()
        self.manual_test_lock = threading.Lock()

        self._boot_lock = threading.Lock()
        self._booted = False


# Singleton — import this everywhere instead of using globals.
state = AppState()
