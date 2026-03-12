"""Sync routes."""
from flask import Blueprint, jsonify

from app.services.sync_service import sync_from_web

sync_bp = Blueprint("sync", __name__)


@sync_bp.route("/api/sync", methods=["POST"])
def api_sync():
    try:
        result = sync_from_web()
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

