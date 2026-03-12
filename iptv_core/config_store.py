"""Persistence layer for config.json and health_cache.json."""
import json
import logging
import os

from .constants import CONFIG_FILE, DEFAULT_CFG, HEALTH_FILE

logger = logging.getLogger(__name__)


def load_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return {**DEFAULT_CFG, **json.load(f)}
        except Exception:
            pass
    return dict(DEFAULT_CFG)


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def load_health_cache() -> dict:
    if not os.path.isfile(HEALTH_FILE):
        return {}
    try:
        with open(HEALTH_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_health_cache(cache: dict):
    try:
        with open(HEALTH_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("No se pudo guardar health cache: %s", e)
