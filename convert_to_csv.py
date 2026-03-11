"""
Migración única: lista_iptv.m3u → channels.csv

Extrae de cada canal: grupo, nombre, calidad, fuente, peer, tvg_id, logo.
Asigna MAIN al primer stream de cada canal y BACKUP al resto.

Uso:
    python convert_to_csv.py
    python convert_to_csv.py --input otra_lista.m3u --output canales.csv
"""
import re
import csv
import os
import sys
import argparse

BASE_DIR    = os.path.dirname(__file__)
DEF_INPUT   = os.path.join(BASE_DIR, "lista_iptv.m3u")
DEF_OUTPUT  = os.path.join(BASE_DIR, "channels.csv")
ACE_BASE    = "http://192.168.1.169:8081/ace/getstream?id="
QUALITY_SET = {"FHD", "HD", "SD", "4K"}

CSV_FIELDS = [
    "group", "channel", "quality", "source",
    "peer_full", "tvg_id", "tvg_logo", "status", "notes",
]


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _attr(extinf: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', extinf)
    return m.group(1) if m else ""


def parse_display_name(raw: str):
    """
    Descompone el nombre del canal del M3U original.
    Formatos soportados:
        'DAZN 1 FHD ad6d --> NEW ERA'
        'DAZN 1 d276 --> ELCANO'
        'Canal 1 (1RFEF) (SOLO EVENTOS) 437d --> NEW ERA V'
    Devuelve: (channel, quality, peer_short, source)
    """
    if " --> " not in raw:
        return raw.strip(), "", "", ""

    left, source = raw.rsplit(" --> ", 1)
    tokens = left.split()

    peer_s = ""
    if tokens and re.fullmatch(r"[0-9a-fA-F]{4}", tokens[-1]):
        peer_s = tokens.pop()

    quality = ""
    if tokens and tokens[-1].upper() in QUALITY_SET:
        quality = tokens.pop().upper()

    return " ".join(tokens), quality, peer_s, source.strip()


def load_m3u(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    channels: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("#EXTINF"):
            i += 1
            continue

        extinf = line
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        url = lines[j] if j < len(lines) else ""
        peer_full = url.split("?id=", 1)[-1].strip() if "?id=" in url else ""

        raw_name = re.search(r",\s*(.+)$", extinf)
        raw_name = raw_name.group(1).strip() if raw_name else ""
        channel, quality, _, source = parse_display_name(raw_name)

        channels.append({
            "group":    _attr(extinf, "group-title"),
            "channel":  channel,
            "quality":  quality,
            "source":   source,
            "peer_full": peer_full,
            "tvg_id":   _attr(extinf, "tvg-id"),
            "tvg_logo": _attr(extinf, "tvg-logo"),
            "status":   "",
            "notes":    "",
        })
        i = j + 1

    return channels


def assign_status(channels: list[dict]) -> list[dict]:
    """Primer stream de cada (grupo, canal) → MAIN; el resto → BACKUP."""
    seen: set[tuple[str, str]] = set()
    for ch in channels:
        key = (ch["group"], ch["channel"])
        ch["status"] = "MAIN" if key not in seen else "BACKUP"
        seen.add(key)
    return channels


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convierte M3U → channels.csv")
    parser.add_argument("--input",  default=DEF_INPUT,  metavar="M3U",
                        help=f"Fichero M3U de entrada (default: {DEF_INPUT})")
    parser.add_argument("--output", default=DEF_OUTPUT, metavar="CSV",
                        help=f"CSV de salida (default: {DEF_OUTPUT})")
    parser.add_argument("--force",  action="store_true",
                        help="Sobreescribir el CSV si ya existe")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: no se encuentra '{args.input}'", file=sys.stderr)
        sys.exit(1)

    if os.path.isfile(args.output) and not args.force:
        answer = input(f"'{args.output}' ya existe. ¿Sobreescribir? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado.")
            sys.exit(0)

    print(f"Leyendo  : {args.input}")
    channels = assign_status(load_m3u(args.input))

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(channels)

    main_c   = sum(1 for c in channels if c["status"] == "MAIN")
    backup_c = len(channels) - main_c

    print(f"Guardado : {args.output}")
    print(f"Canales  : {len(channels)}  (MAIN={main_c}  BACKUP={backup_c})")

    # Preview unique channel names
    unique = sorted({(c["group"], c["channel"]) for c in channels})
    print(f"\nCanales únicos detectados ({len(unique)}):")
    for group, channel in unique[:20]:
        print(f"  [{group}] {channel}")
    if len(unique) > 20:
        print(f"  ... y {len(unique) - 20} más")


if __name__ == "__main__":
    main()
