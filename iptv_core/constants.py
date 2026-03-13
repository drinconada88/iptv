import os


BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# In Docker mount /data for persistence; otherwise same as BASE_DIR.
DATA_DIR = os.environ.get("IPTV_DATA_DIR", BASE_DIR)

# ── Single source-of-truth M3U ────────────────────────────────────────────────
# Only ONE M3U file matters at runtime. Everything else is derived from it:
#   - /live.m3u   → served in memory, never written to disk
#   - /api/export → written to TMP_DIR temporarily, then sent as download
#   - backups/    → timestamped copies made before every save
M3U_FILE = os.path.join(DATA_DIR, "lista_iptv.m3u")

# ── Support files ─────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
HEALTH_FILE = os.path.join(DATA_DIR, "health_cache.json")

# Temporary files for downloads — not tracked by git.
TMP_DIR = os.path.join(DATA_DIR, "tmp")
EXPORT_TMP = os.path.join(TMP_DIR, "_export_tmp.m3u")

# Versioned backups of M3U_FILE — not tracked by git.
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
MAX_BACKUPS = 15  # keep this many auto-backups; older ones are pruned

# ── EPG ───────────────────────────────────────────────────────────────────────
EPG_URL = (
    "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/"
    "refs/heads/master/guiatv.xml,"
    "https://epgshare01.online/epgshare01/epg_ripper_NL1.xml.gz"
)

# ── Channel metadata ──────────────────────────────────────────────────────────
STATUSES = ["MAIN", "BACKUP", "TEST"]
QUALITY_SET = {"FHD", "HD", "SD", "4K"}
STATUS_ORDER = {s: i for i, s in enumerate(STATUSES)}

DEFAULT_CFG = {
    "ace_host": "192.168.1.169",
    "ace_port": "8081",
    "ace_path": "/ace/getstream?id=",
    "nas_path": "",
    "jellyfin_mode": False,
    "auto_check_enabled": True,
    "auto_check_minutes": 2.0,
    "auto_check_batch_size": 8,
    "auto_check_timeout_sec": 20,
    "sync_sources": [
        {
            "id": "new_era",
            "name": "NEW ERA",
            "enabled": True,
            "parser": "new_era",
            "url": (
                "https://ipfs.io/ipns/"
                "k2k4r8oqlcjxsritt5mczkcn4mmvcmymbqw7113fz2flkrerfwfps004/"
                "?tab=canales"
            ),
            "timeout_sec": 60,
            "priority": 10,
        },
        {
            "id": "acestreamid",
            "name": "AceStreamID",
            "enabled": False,
            "parser": "acestreamid",
            "url": "https://acestreamid.com/",
            "timeout_sec": 60,
            "priority": 20,
        },
        {
            "id": "hashes_json",
            "name": "Hashes JSON",
            "enabled": True,
            "parser": "hashes_json",
            "url": (
                "https://k51qzi5uqu5di462t7j4vu4akwfhvtjhy88qbupktvoacqfqe9uforjvhyi4wr"
                ".ipns.dweb.link/hashes.json"
            ),
            "timeout_sec": 45,
            "priority": 15,
        },
        {
            "id": "vk_channels",
            "name": "VK Channels",
            "enabled": True,
            "parser": "vk_article",
            "url": "https://vk.com/@-214914587-channels-list?subtype=primary",
            "timeout_sec": 45,
            "priority": 25,
        }
    ],
}
