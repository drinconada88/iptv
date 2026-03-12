"""Channel management routes: CRUD, persistence, live M3U endpoint."""
import os
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from iptv_core.channel_service import (
    ace_base,
    batch_update_channels,
    create_channel,
    delete_channel,
    duplicate_channel,
    export_to_tmp,
    get_channel,
    load_from_file,
    reorder_channels,
    save_to_file,
    sync_from_web,
    update_channel,
)
from iptv_core.config_store import load_config
from iptv_core.constants import EPG_URL, M3U_FILE
from iptv_core.health_service import ensure_runtime_background
from iptv_core.m3u_codec import peer_short
from iptv_core.state import state

channels_bp = Blueprint("channels", __name__)


@channels_bp.route("/")
def index():
    ensure_runtime_background()
    return render_template("index.html", m3u_path=state.m3u_path)


@channels_bp.route("/api/channels")
def api_channels():
    ensure_runtime_background()
    return jsonify(state.channels)


@channels_bp.route("/api/channel/<int:idx>", methods=["PUT"])
def api_update(idx: int):
    ch = update_channel(idx, request.get_json(silent=True) or {})
    if ch is None:
        return jsonify({"ok": False, "error": "Not found"}), 404
    return jsonify({"ok": True, "channel": ch})


@channels_bp.route("/api/channels/batch", methods=["PUT"])
def api_batch_update():
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids", [])
    patch = payload.get("patch", {})

    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "error": "ids debe ser una lista no vacia"}), 400
    if not isinstance(patch, dict) or not patch:
        return jsonify({"ok": False, "error": "patch debe ser un objeto no vacio"}), 400

    normalized_ids = []
    for raw_id in ids:
        try:
            normalized_ids.append(int(raw_id))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": f"id invalido: {raw_id}"}), 400

    updated, missing = batch_update_channels(normalized_ids, patch)
    return jsonify(
        {
            "ok": True,
            "updated": updated,
            "updated_count": len(updated),
            "missing": missing,
        }
    )


@channels_bp.route("/api/channel/<int:idx>", methods=["DELETE"])
def api_delete(idx: int):
    if not delete_channel(idx):
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True})


@channels_bp.route("/api/reorder", methods=["POST"])
def api_reorder():
    order = (request.get_json(silent=True) or {}).get("order", [])
    reorder_channels(order)
    return jsonify({"ok": True})


@channels_bp.route("/api/channel/new", methods=["POST"])
def api_new():
    ch = create_channel(request.get_json(silent=True) or {})
    return jsonify({"ok": True, "channel": ch})


@channels_bp.route("/api/channel/<int:idx>/duplicate", methods=["POST"])
def api_duplicate(idx: int):
    ch = duplicate_channel(idx)
    if ch is None:
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "channel": ch})


@channels_bp.route("/api/save", methods=["POST"])
def api_save():
    path = (request.get_json(silent=True) or {}).get("path")
    result = save_to_file(path)
    return jsonify({"ok": True, **result})


@channels_bp.route("/api/export")
def api_export():
    tmp = export_to_tmp()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return send_file(
        tmp,
        as_attachment=True,
        download_name=f"lista_iptv_{stamp}.m3u",
        mimetype="audio/x-mpegurl",
    )


@channels_bp.route("/api/load", methods=["POST"])
def api_load():
    path = (request.get_json(silent=True) or {}).get("path", M3U_FILE)
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": f"No existe: {path}"}), 404
    channels = load_from_file(path)
    return jsonify({"ok": True, "count": len(channels)})


@channels_bp.route("/api/sync", methods=["POST"])
def api_sync():
    try:
        result = sync_from_web()
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@channels_bp.route("/live.m3u")
def live_m3u():
    """Dynamic M3U endpoint for IPTV clients.

    Query params: host, port, status (MAIN/BACKUP/TEST), group.
    """
    cfg = load_config()
    host = request.args.get("host", "").strip() or cfg.get("ace_host", "")
    port = request.args.get("port", "").strip() or str(cfg.get("ace_port", ""))
    ace_path = cfg.get("ace_path", "/ace/getstream?id=")
    if not ace_path.startswith("/"):
        ace_path = "/" + ace_path

    scheme = "https" if port == "443" else "http"
    include_port = not (
        (scheme == "https" and port == "443") or (scheme == "http" and port == "80")
    )
    netloc = f"{host}:{port}" if include_port and port else host
    base_url = f"{scheme}://{netloc}{ace_path}"

    only_st = request.args.get("status", "").upper()
    only_gr = request.args.get("group", "")

    chans = [c for c in state.channels if c.get("status", "").upper() != "DISABLED"]
    if only_st:
        chans = [c for c in chans if c.get("status", "").upper() == only_st]
    if only_gr:
        chans = [c for c in chans if c.get("group", "") == only_gr]

    lines = [f'#EXTM3U url-tvg="{EPG_URL}" refresh="3600"', ""]
    for ch in chans:
        peer = ch.get("peer_full", "").strip()
        channel = ch.get("channel", "")
        quality = ch.get("quality", "")
        source = ch.get("source", "")
        group = ch.get("group", "")
        tvg_id = ch.get("tvg_id", "")
        tvg_logo = ch.get("tvg_logo", "")
        ps = peer_short(peer)

        parts = [channel]
        if quality:
            parts.append(quality)
        if source:
            parts.append(source)
        if ps:
            parts.append(ps)
        display = " | ".join(parts)

        lines.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" group-title="{group}",{display}'
        )
        lines.append(f"{base_url}{peer}")
        lines.append("")

    return Response("\n".join(lines), content_type="audio/x-mpegurl; charset=utf-8")
