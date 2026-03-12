"""Blueprint registration for IPTV Manager."""
from flask import Flask


def register_blueprints(app: Flask):
    from .auth_bp import auth_bp
    from .backups_bp import backups_bp
    from .channels_bp import channels_bp
    from .config_bp import config_bp
    from .health_bp import health_bp
    from .streaming_bp import streaming_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(channels_bp)
    app.register_blueprint(streaming_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(backups_bp)
