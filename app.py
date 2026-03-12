"""IPTV Manager — Flask entry point.

Ejecutar:  python app.py
Abrir:     http://localhost:5000
"""
import os

from flask import Flask

from iptv_core.channel_service import load_from_file
from iptv_core.constants import BASE_DIR, M3U_FILE
from iptv_core.health_service import ensure_runtime_background
from iptv_core.state import state
from routes import register_blueprints


def create_app() -> Flask:
    app = Flask(__name__)
    register_blueprints(app)
    return app


def _seed_m3u_if_needed():
    """On first Docker boot copy the bundled M3U into the data volume."""
    seed_file = os.path.join(BASE_DIR, "lista_iptv.m3u")
    if not os.path.isfile(M3U_FILE) and os.path.isfile(seed_file):
        try:
            os.makedirs(os.path.dirname(M3U_FILE), exist_ok=True)
            with open(seed_file, encoding="utf-8") as src, \
                    open(M3U_FILE, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            print(f"OK  Seed M3U copiado a {M3U_FILE}")
        except Exception as e:
            print(f"WARN  No se pudo inicializar M3U en {M3U_FILE}: {e}")


if __name__ == "__main__":
    _seed_m3u_if_needed()

    if os.path.isfile(M3U_FILE):
        load_from_file(M3U_FILE)
        print(f"OK  Cargados {len(state.channels)} canales desde {M3U_FILE}")
    else:
        print(f"WARN  No existe M3U inicial en {M3U_FILE}")

    app = create_app()
    ensure_runtime_background()
    print("\n  IPTV Manager arrancando en http://localhost:5000\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
