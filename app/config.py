"""Environment-backed app settings."""
import os


def auth_enabled() -> bool:
    return os.environ.get("IPTV_AUTH_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def admin_user() -> str:
    return os.environ.get("IPTV_ADMIN_USER", "admin").strip() or "admin"


def admin_pass() -> str:
    return os.environ.get("IPTV_ADMIN_PASS", "admin").strip() or "admin"


def get_secret_key() -> str:
    return os.environ.get("IPTV_SECRET_KEY", "change-this-iptv-secret")

