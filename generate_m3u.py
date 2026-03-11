"""
Genera un M3U limpio y estructurado desde channels.csv.

El M3U resultante sigue esta convención:
  - Nombre de canal:  CANAL | CALIDAD | FUENTE | peer
  - Canales DISABLED: comentados (# DISABLED)
  - Orden:            grupo → canal → estado (MAIN, BACKUP, TEST, DISABLED)
  - Comentarios:      bloque por categoría y bloque por canal

Uso:
    python generate_m3u.py
    python generate_m3u.py --input canales.csv --output mi_lista.m3u
    python generate_m3u.py --only-main          (excluye BACKUP/TEST/DISABLED)
"""
import csv
import os
import sys
import argparse

BASE_DIR   = os.path.dirname(__file__)
DEF_INPUT  = os.path.join(BASE_DIR, "channels.csv")
DEF_OUTPUT = os.path.join(BASE_DIR, "lista_iptv_clean.m3u")
ACE_BASE   = "http://192.168.1.169:8081/ace/getstream?id="
EPG_URL    = (
    "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/"
    "refs/heads/master/guiatv.xml,"
    "https://epgshare01.online/epgshare01/epg_ripper_NL1.xml.gz"
)

STATUS_ORDER = {"MAIN": 0, "BACKUP": 1, "TEST": 2, "DISABLED": 3}


# ── Helpers ───────────────────────────────────────────────────────────────────

def peer_short(full: str) -> str:
    return full[-4:] if len(full) >= 4 else full


def display_name(ch: dict) -> str:
    """Genera 'CANAL | CALIDAD | FUENTE | peer' según los datos disponibles."""
    parts = [ch.get("channel", "?")]
    if ch.get("quality"):
        parts.append(ch["quality"])
    if ch.get("source"):
        parts.append(ch["source"])
    ps = peer_short(ch.get("peer_full", ""))
    if ps:
        parts.append(ps)
    return " | ".join(parts)


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── M3U generator ─────────────────────────────────────────────────────────────

def generate(channels: list[dict], output: str, only_main: bool = False) -> dict:
    def _sort_key(c):
        return (
            c.get("group", ""),
            c.get("channel", ""),
            STATUS_ORDER.get(c.get("status", "BACKUP"), 99),
            c.get("quality", ""),
        )

    chans = sorted(channels, key=_sort_key)

    out = [
        f'#EXTM3U url-tvg="{EPG_URL}" refresh="3600"',
        "#EXTVLCOPT:network-caching=1000",
        "",
    ]

    stats = {"MAIN": 0, "BACKUP": 0, "TEST": 0, "DISABLED": 0, "skipped": 0}
    cur_group = cur_channel = None

    for ch in chans:
        status   = ch.get("status", "MAIN").upper()
        group    = ch.get("group", "")
        channel  = ch.get("channel", "")
        quality  = ch.get("quality", "")
        source   = ch.get("source", "")
        peer     = ch.get("peer_full", "").strip()
        tvg_id   = ch.get("tvg_id", "")
        tvg_logo = ch.get("tvg_logo", "")
        notes    = ch.get("notes", "")

        if only_main and status != "MAIN":
            stats["skipped"] += 1
            continue

        # ── Category header ────────────────────────────────────────────
        if group != cur_group:
            cur_group    = group
            cur_channel  = None
            out += [
                "",
                "#" * 52,
                f"# CATEGORÍA: {group}",
                "#" * 52,
                "",
            ]

        # ── Channel header (once per unique channel name) ──────────────
        if channel != cur_channel:
            cur_channel = channel
            sep = "─" * 10
            out += [
                f"# {sep} Canal: {channel} {sep}",
                f"# TVG-ID : {tvg_id}",
                f"# Logo   : {tvg_logo}",
                "",
            ]

        # ── Stream entry ───────────────────────────────────────────────
        ps   = peer_short(peer)
        meta = []
        if source:  meta.append(f"Fuente: {source}")
        if quality: meta.append(f"Calidad: {quality}")
        if ps:      meta.append(f"Peer: {ps}")
        meta.append(f"Estado: {status}")
        if notes:   meta.append(f"Notas: {notes}")

        out.append("# " + "  |  ".join(meta))

        extinf = (
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" '
            f'group-title="{group}",{display_name(ch)}'
        )
        url = f"{ACE_BASE}{peer}"

        if status == "DISABLED":
            out += ["# DISABLED", f"# {extinf}", f"# {url}", ""]
        else:
            out += [extinf, url, ""]

        stats[status] = stats.get(status, 0) + 1

    out.append("")  # trailing newline
    with open(output, "w", encoding="utf-8") as f:
        f.write("\n".join(out))

    return stats


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera M3U estructurado desde channels.csv")
    parser.add_argument("--input",     default=DEF_INPUT,  metavar="CSV")
    parser.add_argument("--output",    default=DEF_OUTPUT, metavar="M3U")
    parser.add_argument("--only-main", action="store_true",
                        help="Incluir solo streams con estado MAIN")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: no se encuentra '{args.input}'", file=sys.stderr)
        print("Ejecuta primero:  python convert_to_csv.py", file=sys.stderr)
        sys.exit(1)

    channels = read_csv(args.input)
    print(f"Leyendo  : {args.input}  ({len(channels)} entradas)")

    stats = generate(channels, args.output, only_main=args.only_main)

    print(f"Generado : {args.output}")
    print(f"  MAIN={stats['MAIN']}  BACKUP={stats['BACKUP']}  "
          f"TEST={stats['TEST']}  DISABLED={stats['DISABLED']}", end="")
    if stats["skipped"]:
        print(f"  (omitidos={stats['skipped']})", end="")
    print()


if __name__ == "__main__":
    main()
