"""Streaming routes: VLC play file, MPEG-TS proxy, HLS proxy, debug."""
import base64

from flask import Blueprint, Response, jsonify, request, stream_with_context

from iptv_core.acexy_client import (
    acexy_connect,
    acexy_http_fetch,
    debug_stream_steps,
    rewrite_m3u8,
    stream_generator,
)
from iptv_core.channel_service import ace_base
from iptv_core.config_store import load_config
from iptv_core.state import state

streaming_bp = Blueprint("streaming", __name__)


@streaming_bp.route("/api/play/<int:idx>")
def api_play(idx: int):
    """Return a single-channel .m3u file for opening in VLC."""
    if not (0 <= idx < len(state.channels)):
        return "Not found", 404
    ch = state.channels[idx]
    peer = ch.get("peer_full", "").strip()
    name = ch.get("channel", f"Canal {idx}")
    quality = ch.get("quality", "")
    source = ch.get("source", "")
    group = ch.get("group", "")
    tvg_id = ch.get("tvg_id", "")
    logo = ch.get("tvg_logo", "")

    parts = [name]
    if quality:
        parts.append(quality)
    if source:
        parts.append(source)
    if peer:
        parts.append(peer[-4:])
    display = " | ".join(parts)

    url = f"{ace_base()}{peer}"
    m3u = (
        f"#EXTM3U\n"
        f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{logo}" group-title="{group}",{display}\n'
        f"{url}\n"
    )
    filename = f"{name.replace(' ', '_')}_{peer[-4:] if peer else 'nostream'}.m3u"
    return m3u, 200, {
        "Content-Type": "audio/x-mpegurl; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{filename}"',
    }


@streaming_bp.route("/api/stream/<int:idx>")
def api_stream(idx: int):
    """MPEG-TS proxy for the embedded player (avoids CORS)."""
    if not (0 <= idx < len(state.channels)):
        return "Not found", 404
    ch = state.channels[idx]
    peer = ch.get("peer_full", "").strip()
    if not peer:
        return "No peer configured", 400

    r, conn = acexy_connect(ace_base() + peer, timeout=45, read_timeout=60)
    if r is None:
        return "No se pudo conectar con Acexy/AceStream", 502

    content_type = r.getheader("Content-Type", "video/mp2t")
    if not content_type or content_type.lower() == "application/octet-stream":
        content_type = "video/mp2t"

    return Response(
        stream_with_context(stream_generator(r, conn, idx, peer)),
        content_type=content_type,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@streaming_bp.route("/api/stream/debug/<int:idx>")
def api_stream_debug(idx: int):
    """Diagnostics: trace redirect steps Acexy returns."""
    if not (0 <= idx < len(state.channels)):
        return jsonify({"error": "not found"}), 404
    ch = state.channels[idx]
    peer = ch.get("peer_full", "").strip()
    if not peer:
        return jsonify({"error": "no peer"}), 400

    start_url = ace_base() + peer
    steps = debug_stream_steps(start_url)
    return jsonify({"start_url": start_url, "steps": steps})


@streaming_bp.route("/api/hls/<int:idx>")
def api_hls_manifest(idx: int):
    """Proxy the HLS manifest from AceStream (avoids CORS in browser)."""
    if not (0 <= idx < len(state.channels)):
        return "Not found", 404
    ch = state.channels[idx]
    peer = ch.get("peer_full", "").strip()
    if not peer:
        return "No peer configured", 400

    cfg = load_config()
    hls_url = f"http://{cfg['ace_host']}:{cfg['ace_port']}/ace/manifest.m3u8?id={peer}"
    return _proxy_m3u8(hls_url)


@streaming_bp.route("/api/hls/seg")
def api_hls_seg():
    """Proxy HLS segments/chunklists (avoids CORS in browser)."""
    enc = request.args.get("u", "")
    if not enc:
        return "Missing url param", 400
    try:
        url = base64.urlsafe_b64decode(enc.encode()).decode()
    except Exception:
        return "Bad url encoding", 400
    return _proxy_hls_resource(url)


# ── Internal HLS helpers ──────────────────────────────────────────────────────

def _proxy_m3u8(url: str) -> Response:
    try:
        fetched = acexy_http_fetch(url, timeout=35)
    except Exception as e:
        return Response(
            f"# Error fetching manifest: {e}",
            502,
            content_type="application/vnd.apple.mpegurl",
        )

    ct = fetched["headers"].get("Content-Type", "application/vnd.apple.mpegurl")
    try:
        text = fetched["data"].decode("utf-8")
    except UnicodeDecodeError:
        text = fetched["data"].decode("latin-1", errors="replace")

    return Response(
        rewrite_m3u8(text, fetched["final_url"]),
        200,
        content_type=ct,
        headers={"Cache-Control": "no-cache"},
    )


def _proxy_hls_resource(url: str) -> Response:
    try:
        fetched = acexy_http_fetch(url, timeout=20)
    except Exception as e:
        return Response(f"Error: {e}", 502)

    data = fetched["data"]
    ct = fetched["headers"].get("Content-Type", "application/octet-stream")
    final_url = fetched["final_url"]

    if "mpegurl" in ct.lower() or final_url.split("?")[0].endswith(".m3u8"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
        return Response(
            rewrite_m3u8(text, final_url),
            200,
            content_type="application/vnd.apple.mpegurl",
            headers={"Cache-Control": "no-cache"},
        )

    return Response(data, 200, content_type=ct, headers={"Cache-Control": "no-cache"})
