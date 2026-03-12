"""Versioned backups for lista_iptv.m3u.

Strategy
--------
- Before every `save_to_file()` call, a timestamped snapshot is written to
  `backups/lista_iptv_YYYYMMDD_HHMMSS[_label].m3u`.
- After writing, old backups beyond MAX_BACKUPS are automatically pruned
  (oldest first, keeping the most recent ones).
- Manual backups can be created from the API at any time.
- Restoring a backup replaces M3U_FILE in place, then triggers `load_from_file`
  so the in-memory state is immediately consistent.
"""
import logging
import os
import shutil
from datetime import datetime

from .constants import BACKUPS_DIR, M3U_FILE, MAX_BACKUPS

logger = logging.getLogger(__name__)

_BACKUP_PREFIX = "lista_iptv_"
_BACKUP_EXT = ".m3u"


# ── Public API ────────────────────────────────────────────────────────────────

def create_backup(label: str = "") -> dict | None:
    """Copy M3U_FILE to backups/ with a timestamp.

    Returns the backup metadata dict, or None if M3U_FILE doesn't exist yet.
    """
    if not os.path.isfile(M3U_FILE):
        return None

    os.makedirs(BACKUPS_DIR, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = f"_{_slugify(label)}" if label else ""
    filename = f"{_BACKUP_PREFIX}{stamp}{slug}{_BACKUP_EXT}"
    dest = os.path.join(BACKUPS_DIR, filename)

    shutil.copy2(M3U_FILE, dest)
    logger.info("Backup creado: %s", filename)

    prune_old_backups()
    return _file_meta(dest)


def list_backups() -> list[dict]:
    """Return all backups sorted by newest first."""
    if not os.path.isdir(BACKUPS_DIR):
        return []
    files = [
        f for f in os.listdir(BACKUPS_DIR)
        if f.startswith(_BACKUP_PREFIX) and f.endswith(_BACKUP_EXT)
    ]
    metas = [_file_meta(os.path.join(BACKUPS_DIR, f)) for f in files]
    return sorted(metas, key=lambda m: m["created_at"], reverse=True)


def restore_backup(filename: str) -> dict:
    """Overwrite M3U_FILE with the backup, reload channels into memory.

    Returns {ok, filename, channels_loaded}.
    Raises FileNotFoundError if the backup doesn't exist.
    """
    path = _safe_path(filename)

    # Safety: back up current state before restoring
    create_backup(label="pre-restore")

    shutil.copy2(path, M3U_FILE)
    logger.info("Backup restaurado: %s → %s", filename, M3U_FILE)

    # Reload channels from the restored file
    from .channel_service import load_from_file
    channels = load_from_file(M3U_FILE)
    return {"ok": True, "filename": filename, "channels_loaded": len(channels)}


def delete_backup(filename: str) -> dict:
    """Delete a single backup file. Returns {ok, filename}."""
    path = _safe_path(filename)
    os.remove(path)
    logger.info("Backup eliminado: %s", filename)
    return {"ok": True, "filename": filename}


def prune_old_backups(keep: int = MAX_BACKUPS):
    """Remove oldest backups beyond `keep`. Auto-backups only (no 'manual' label)."""
    if not os.path.isdir(BACKUPS_DIR):
        return
    all_backups = list_backups()
    if len(all_backups) <= keep:
        return
    to_delete = all_backups[keep:]
    for meta in to_delete:
        try:
            os.remove(os.path.join(BACKUPS_DIR, meta["filename"]))
            logger.debug("Backup purgado: %s", meta["filename"])
        except Exception as e:
            logger.warning("No se pudo purgar backup %s: %s", meta["filename"], e)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _file_meta(path: str) -> dict:
    stat = os.stat(path)
    filename = os.path.basename(path)
    name = filename[len(_BACKUP_PREFIX):-len(_BACKUP_EXT)]
    parts = name.split("_", maxsplit=2)
    label = parts[2] if len(parts) > 2 else ""
    return {
        "filename": filename,
        "label": label,
        "size_bytes": stat.st_size,
        "created_at": int(stat.st_mtime),
    }


def _safe_path(filename: str) -> str:
    """Resolve filename inside BACKUPS_DIR. Raises if invalid or not found."""
    # Prevent path traversal
    if os.sep in filename or "/" in filename or filename.startswith("."):
        raise ValueError(f"Nombre de fichero no válido: {filename!r}")
    if not filename.startswith(_BACKUP_PREFIX) or not filename.endswith(_BACKUP_EXT):
        raise ValueError(f"No es un fichero de backup válido: {filename!r}")
    path = os.path.join(BACKUPS_DIR, filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Backup no encontrado: {filename}")
    return path


def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9]", "-", text.strip())[:30].strip("-")
