"""Basic session authentication routes."""
import os

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

auth_bp = Blueprint("auth", __name__)


def _auth_enabled() -> bool:
    return os.environ.get("IPTV_AUTH_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _admin_user() -> str:
    return os.environ.get("IPTV_ADMIN_USER", "admin").strip() or "admin"


def _admin_pass() -> str:
    return os.environ.get("IPTV_ADMIN_PASS", "admin").strip() or "admin"


@auth_bp.route("/login", methods=["GET"])
def login_page():
    if not _auth_enabled() or session.get("auth_ok"):
        return redirect(url_for("channels.index"))
    return render_template("login.html", error="", username="")


@auth_bp.route("/login", methods=["POST"])
def login_post():
    if not _auth_enabled():
        return redirect(url_for("channels.index"))

    payload = request.get_json(silent=True)
    if payload is not None:
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", "")).strip()
        ok = username == _admin_user() and password == _admin_pass()
        if ok:
            session["auth_ok"] = True
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    username = (request.form.get("username", "") or "").strip()
    password = (request.form.get("password", "") or "").strip()
    if username == _admin_user() and password == _admin_pass():
        session["auth_ok"] = True
        nxt = request.args.get("next", "").strip()
        if nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(url_for("channels.index"))

    return render_template("login.html", error="Credenciales incorrectas", username=username), 401


@auth_bp.route("/logout", methods=["POST", "GET"])
def logout():
    session.pop("auth_ok", None)
    if request.method == "POST":
        return jsonify({"ok": True})
    return redirect(url_for("auth.login_page"))
