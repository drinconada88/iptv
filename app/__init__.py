"""Flask app factory and middleware wiring."""
from pathlib import Path

from flask import Flask, jsonify, redirect, request, session, url_for
from jinja2 import ChoiceLoader, FileSystemLoader

from app.config import auth_enabled, get_secret_key


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="web/templates",
        static_folder="web/static",
    )
    app.secret_key = get_secret_key()
    legacy_templates = str(Path(__file__).resolve().parent.parent / "templates")
    app.jinja_loader = ChoiceLoader([app.jinja_loader, FileSystemLoader(legacy_templates)])

    @app.before_request
    def _require_login():
        if not auth_enabled():
            return None

        path = request.path or ""
        if path.startswith("/static/"):
            return None
        if path in {"/login", "/logout", "/live.m3u"}:
            return None

        if session.get("auth_ok"):
            return None

        if path.startswith("/api/"):
            return jsonify({"ok": False, "error": "auth_required"}), 401
        return redirect(url_for("auth.login_page", next=path))

    from app.api.auth import auth_bp
    from app.api.backups import backups_bp
    from app.api.channels import channels_bp
    from app.api.config import config_bp
    from app.api.health import health_bp
    from app.api.streaming import streaming_bp
    from app.api.sync import sync_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(channels_bp)
    app.register_blueprint(streaming_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(backups_bp)
    app.register_blueprint(sync_bp)
    return app

