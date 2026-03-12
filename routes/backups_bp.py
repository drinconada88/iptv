"""Backup management routes for lista_iptv.m3u versioning."""
from flask import Blueprint, jsonify, request

from iptv_core.backup_service import (
    create_backup,
    delete_backup,
    list_backups,
    restore_backup,
)

backups_bp = Blueprint("backups", __name__)


@backups_bp.route("/api/backups", methods=["GET"])
def api_list_backups():
    """List all available backups, newest first."""
    return jsonify({"ok": True, "backups": list_backups()})


@backups_bp.route("/api/backups", methods=["POST"])
def api_create_backup():
    """Create a manual backup with an optional label."""
    label = (request.get_json(silent=True) or {}).get("label", "manual")
    backup = create_backup(label=label)
    if backup is None:
        return jsonify({"ok": False, "error": "No hay M3U para respaldar"}), 404
    return jsonify({"ok": True, "backup": backup})


@backups_bp.route("/api/backups/<filename>/restore", methods=["POST"])
def api_restore_backup(filename: str):
    """Restore a backup, replacing the current M3U and reloading channels."""
    try:
        result = restore_backup(filename)
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@backups_bp.route("/api/backups/<filename>", methods=["DELETE"])
def api_delete_backup(filename: str):
    """Delete a single backup file."""
    try:
        result = delete_backup(filename)
        return jsonify(result)
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
