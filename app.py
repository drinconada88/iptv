"""IPTV Manager — Flask entry point.

Ejecutar:  python app.py
Abrir:     http://localhost:5000
"""
import os

from flask import Flask

from iptv_core.channel_service import load_from_file
from iptv_core.constants import BASE_DIR, CONFIG_FILE, HEALTH_FILE, M3U_FILE
from iptv_core.health_service import ensure_runtime_background
from iptv_core.state import state
from routes import register_blueprints


def create_app() -> Flask:
    app = Flask(__name__)
    register_blueprints(app)
    return app


def _seed_file_if_needed(src_name: str, dst_path: str):
    """
    On Docker boots with IPTV_DATA_DIR mounted, seed data from repo root if needed.
    Never overwrite existing persistent files.
    """
    src_path = os.path.join(BASE_DIR, src_name)
    if os.path.isfile(dst_path) or not os.path.isfile(src_path):
        return
    try:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(src_path, encoding="utf-8") as src, open(
            dst_path, "w", encoding="utf-8"
        ) as dst:
            dst.write(src.read())
        print(f"OK  Seed copiado: {src_name} -> {dst_path}")
    except Exception as e:
        print(f"WARN  No se pudo inicializar {dst_path} desde {src_name}: {e}")


def _seed_data_if_needed():
    _seed_file_if_needed("lista_iptv.m3u", M3U_FILE)
    _seed_file_if_needed("config.json", CONFIG_FILE)
    _seed_file_if_needed("health_cache.json", HEALTH_FILE)


if __name__ == "__main__":
    _seed_data_if_needed()

    if os.path.isfile(M3U_FILE):
        load_from_file(M3U_FILE)
        print(f"OK  Cargados {len(state.channels)} canales desde {M3U_FILE}")
    else:
        print(f"WARN  No existe M3U inicial en {M3U_FILE}")

    app = create_app()
    ensure_runtime_background()
    print("\n  IPTV Manager arrancando en http://localhost:5000\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
