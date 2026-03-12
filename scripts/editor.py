"""
IPTV Channel Editor  —  v3
Interfaz rediseñada: sidebar de grupos, panel de edición lateral,
estadísticas en cabecera y menú contextual.
"""
import copy
import os
import csv
import re
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from collections import Counter
from typing import Optional

# ── Paths & constants ─────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(__file__)
CSV_FILE  = os.path.join(BASE_DIR, "channels.csv")
M3U_FILE  = os.path.join(BASE_DIR, "lista_iptv.m3u")
ACE_BASE  = "http://192.168.1.169:8081/ace/getstream?id="
EPG_URL   = (
    "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/"
    "refs/heads/master/guiatv.xml,"
    "https://epgshare01.online/epgshare01/epg_ripper_NL1.xml.gz"
)

STATUSES     = ["MAIN", "BACKUP", "TEST", "DISABLED"]
QUALITIES    = ["FHD", "HD", "SD", "4K", ""]
QUALITY_SET  = {"FHD", "HD", "SD", "4K"}
STATUS_ORDER = {s: i for i, s in enumerate(STATUSES)}
CSV_FIELDS   = [
    "group", "channel", "quality", "source",
    "peer_full", "tvg_id", "tvg_logo", "status", "notes",
]

# ── Catppuccin Mocha palette ──────────────────────────────────────────────────
C = {
    "base":    "#1e1e2e", "mantle":  "#181825", "crust":   "#11111b",
    "s0":      "#313244", "s1":      "#45475a", "s2":      "#585b70",
    "ov0":     "#6c7086", "ov1":     "#7f849c",
    "sub0":    "#a6adc8", "sub1":    "#bac2de", "text":    "#cdd6f4",
    "blue":    "#89b4fa", "mauve":   "#cba6f7", "lavender":"#b4befe",
    "red":     "#f38ba8", "peach":   "#fab387", "yellow":  "#f9e2af",
    "green":   "#a6e3a1", "teal":    "#94e2d5", "sky":     "#89dceb",
}
STATUS_FG  = {"MAIN": C["green"], "BACKUP": C["yellow"],
              "TEST": C["sky"],   "DISABLED": C["red"]}
STATUS_TBG = {"MAIN": "#1e2e1e", "BACKUP": "#2e2b1a",
              "TEST": "#1a2830", "DISABLED": "#2e1a1e"}

TREE_COLS = ("channel", "quality", "source", "peer", "status")
COL_HDR   = {"channel": "Canal", "quality": "Cal.",
             "source": "Fuente", "peer": "Peer", "status": "Estado"}
COL_W     = {"channel": 265, "quality": 55, "source": 155, "peer": 65, "status": 85}


# ── Backend helpers ───────────────────────────────────────────────────────────

def peer_short(full: str) -> str:
    return full[-4:] if len(full) >= 4 else full

def _m3u_attr(line: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', line)
    return m.group(1) if m else ""

def _parse_display_name(raw: str):
    if " --> " not in raw:
        return raw.strip(), "", "", ""
    left, source = raw.rsplit(" --> ", 1)
    tokens = left.split()
    ps = tokens.pop() if tokens and re.fullmatch(r"[0-9a-fA-F]{4}", tokens[-1]) else ""
    q  = tokens.pop().upper() if tokens and tokens[-1].upper() in QUALITY_SET else ""
    return " ".join(tokens), q, ps, source.strip()

def load_csv(path: str) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in CSV_FIELDS:
            r.setdefault(k, "")
    return rows

def save_csv(path: str, channels: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for ch in channels:
            w.writerow({k: ch.get(k, "") for k in CSV_FIELDS})

def import_m3u(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    channels: list = []
    seen: set = set()
    i = 0
    while i < len(lines):
        if not lines[i].startswith("#EXTINF"):
            i += 1
            continue
        extinf = lines[i]
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        url = lines[j] if j < len(lines) else ""
        peer_full = url.split("?id=", 1)[-1].strip() if "?id=" in url else ""
        raw = re.search(r",\s*(.+)$", extinf)
        raw = raw.group(1).strip() if raw else ""
        channel, quality, _, source = _parse_display_name(raw)
        group  = _m3u_attr(extinf, "group-title")
        key    = (group, channel)
        status = "MAIN" if key not in seen else "BACKUP"
        seen.add(key)
        channels.append({
            "group": group, "channel": channel, "quality": quality,
            "source": source, "peer_full": peer_full,
            "tvg_id": _m3u_attr(extinf, "tvg-id"),
            "tvg_logo": _m3u_attr(extinf, "tvg-logo"),
            "status": status, "notes": "",
        })
        i = j + 1
    return channels

def generate_m3u(channels: list, output: str, only_main: bool = False) -> dict:
    def _key(c):
        return (c.get("group",""), c.get("channel",""),
                STATUS_ORDER.get(c.get("status","BACKUP"), 99))
    chans = sorted(channels, key=_key)
    out = [f'#EXTM3U url-tvg="{EPG_URL}" refresh="3600"',
           "#EXTVLCOPT:network-caching=1000", ""]
    stats = {s: 0 for s in STATUSES}
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
            continue
        if group != cur_group:
            cur_group = group; cur_channel = None
            out += ["", "#"*52, f"# CATEGORÍA: {group}", "#"*52, ""]
        if channel != cur_channel:
            cur_channel = channel
            out += [f"# {'─'*10} Canal: {channel} {'─'*10}",
                    f"# TVG-ID : {tvg_id}", f"# Logo   : {tvg_logo}", ""]
        ps = peer_short(peer)
        meta = []
        if source:  meta.append(f"Fuente: {source}")
        if quality: meta.append(f"Calidad: {quality}")
        if ps:      meta.append(f"Peer: {ps}")
        meta.append(f"Estado: {status}")
        if notes:   meta.append(f"Notas: {notes}")
        out.append("# " + "  |  ".join(meta))
        parts = [channel]
        if quality: parts.append(quality)
        if source:  parts.append(source)
        if ps:      parts.append(ps)
        extinf = (f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" '
                  f'group-title="{group}",{" | ".join(parts)}')
        url = f"{ACE_BASE}{peer}"
        if status == "DISABLED":
            out += ["# DISABLED", f"# {extinf}", f"# {url}", ""]
        else:
            out += [extinf, url, ""]
        stats[status] = stats.get(status, 0) + 1
    out.append("")
    with open(output, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return stats


# ── GUI ───────────────────────────────────────────────────────────────────────

class ChannelEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("IPTV Channel Editor")
        self.geometry("1340x780")
        self.minsize(1040, 600)
        self.configure(bg=C["base"])
        self.option_add("*tearOff", False)

        self._csv_path: str = ""
        self._channels: list = []
        self._filtered: list = []
        self._unsaved: bool  = False
        self._sort_col: str  = ""
        self._sort_rev: bool = False
        self._sel_idx: Optional[int] = None
        self._active_group: str = "Todos"

        self._setup_styles()
        self._build_header()
        self._build_statusbar()
        self._build_toolbar()
        self._build_main()
        self._build_context_menu()

        self.bind("<Control-s>", lambda _: self._cmd_save())
        self.bind("<Control-f>", lambda _: self._filter_entry.focus_set())
        self.bind("<Escape>",    lambda _: self._clear_edit())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._auto_load()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _setup_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        bg   = C["base"]
        surf = C["s0"]
        text = C["text"]
        blue = C["blue"]
        mnlt = C["mantle"]

        s.configure("Treeview",
            background=surf, foreground=text, fieldbackground=surf,
            rowheight=24, font=("Segoe UI", 9))
        s.configure("Treeview.Heading",
            background=C["crust"], foreground=blue,
            font=("Segoe UI", 9, "bold"), relief="flat")
        s.map("Treeview",
            background=[("selected", C["s1"])],
            foreground=[("selected", "#ffffff")])
        s.configure("TScrollbar",
            background=surf, troughcolor=bg, arrowcolor=C["sub0"],
            relief="flat", borderwidth=0)
        s.configure("TEntry",
            fieldbackground=surf, foreground=text, insertcolor=text,
            bordercolor=C["s1"], relief="flat", padding=4)
        s.map("TEntry", bordercolor=[("focus", blue)])
        s.configure("TCombobox",
            fieldbackground=surf, background=surf, foreground=text,
            selectbackground=surf, selectforeground=text, relief="flat",
            padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", surf)])

        # Button variants
        for name, bg_c, fg_c, hover_c in [
            ("Primary",   blue,        mnlt,       "#b4d0ff"),
            ("Success",   C["green"],  mnlt,       "#c4f0bd"),
            ("Muted",     C["s1"],     text,       C["s2"]),
            ("Danger",    C["s1"],     C["red"],   C["s2"]),
            ("Mauve",     C["mauve"],  mnlt,       "#ddb4ff"),
        ]:
            s.configure(f"{name}.TButton",
                background=bg_c, foreground=fg_c,
                font=("Segoe UI", 9, "bold"), padding=(10, 5), relief="flat")
            s.map(f"{name}.TButton",
                background=[("active", hover_c), ("pressed", bg_c)])

        s.configure("TLabel", background=bg, foreground=text, font=("Segoe UI", 9))
        s.configure("TLabelframe", background=mnlt, foreground=C["sub0"],
            relief="flat", borderwidth=1)
        s.configure("TLabelframe.Label", background=mnlt, foreground=C["sub0"],
            font=("Segoe UI", 8, "bold"))
        s.configure("TPanedwindow", background=C["crust"])
        s.configure("Sash", sashrelief="flat", sashthickness=4,
            background=C["s1"])

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self):
        hdr = tk.Frame(self, bg=C["crust"], height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Left: logo + title
        left = tk.Frame(hdr, bg=C["crust"])
        left.pack(side="left", padx=18, pady=0, fill="y")

        tk.Label(left, text="◈", bg=C["crust"], fg=C["blue"],
                  font=("Segoe UI", 20)).pack(side="left", padx=(0, 10))
        title_col = tk.Frame(left, bg=C["crust"])
        title_col.pack(side="left", fill="y", pady=10)
        tk.Label(title_col, text="IPTV Channel Editor",
                  bg=C["crust"], fg=C["text"],
                  font=("Segoe UI", 13, "bold")).pack(anchor="w")
        self._subtitle_lbl = tk.Label(title_col, text="Abre un CSV o importa un M3U",
                  bg=C["crust"], fg=C["sub0"],
                  font=("Segoe UI", 8))
        self._subtitle_lbl.pack(anchor="w")

        # Right: stat badges
        right = tk.Frame(hdr, bg=C["crust"])
        right.pack(side="right", padx=18, pady=0, fill="y")

        self._stat_lbls: dict = {}
        for status in STATUSES:
            fg   = STATUS_FG[status]
            tbg  = STATUS_TBG[status]
            badge = tk.Frame(right, bg=tbg, padx=12, pady=4,
                              highlightbackground=fg,
                              highlightthickness=1)
            badge.pack(side="left", padx=4, pady=10)
            tk.Label(badge, text=status, bg=tbg, fg=fg,
                      font=("Segoe UI", 7, "bold")).pack()
            n_lbl = tk.Label(badge, text="—", bg=tbg, fg=fg,
                              font=("Segoe UI", 14, "bold"))
            n_lbl.pack()
            self._stat_lbls[status] = n_lbl

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = tk.Frame(self, bg=C["crust"], height=24)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)

        self._unsaved_lbl = tk.Label(sb, text="",
            bg=C["crust"], fg=C["yellow"],
            font=("Segoe UI", 8, "bold"))
        self._unsaved_lbl.pack(side="right", padx=14)

        self._status_var = tk.StringVar(value="Listo")
        tk.Label(sb, textvariable=self._status_var,
                  bg=C["crust"], fg=C["sub0"],
                  font=("Segoe UI", 8), anchor="w").pack(
            side="left", padx=14, fill="x", expand=True)

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = tk.Frame(self, bg=C["mantle"], pady=7, padx=14)
        tb.pack(fill="x")

        for text, cmd, style in [
            ("📂  Abrir CSV",    self._cmd_open,     "Muted.TButton"),
            ("💾  Guardar CSV",  self._cmd_save,     "Primary.TButton"),
            ("📤  Generar M3U",  self._cmd_generate, "Mauve.TButton"),
            ("📥  Importar M3U", self._cmd_import,   "Muted.TButton"),
        ]:
            ttk.Button(tb, text=text, command=cmd, style=style).pack(
                side="left", padx=3)

        # Divider
        tk.Frame(tb, bg=C["s1"], width=1).pack(
            side="left", fill="y", padx=14, pady=2)

        # Search
        tk.Label(tb, text="🔍", bg=C["mantle"], fg=C["sub0"],
                  font=("Segoe UI", 10)).pack(side="left", padx=(0, 5))
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        self._filter_entry = ttk.Entry(tb, textvariable=self._filter_var, width=26)
        self._filter_entry.pack(side="left", padx=(0, 14))

        # Status filter
        tk.Label(tb, text="Estado:", bg=C["mantle"], fg=C["sub0"],
                  font=("Segoe UI", 9)).pack(side="left")
        self._stat_filter = tk.StringVar(value="Todos")
        self._stat_filter.trace_add("write", lambda *_: self._apply_filter())
        ttk.Combobox(tb, textvariable=self._stat_filter,
                     values=["Todos"] + STATUSES,
                     state="readonly", width=12).pack(side="left", padx=(5, 0))

        # Keyboard hint
        tk.Label(tb, text="Ctrl+S guardar  ·  Ctrl+F buscar  ·  Supr eliminar  ·  Clic derecho opciones",
                  bg=C["mantle"], fg=C["ov1"],
                  font=("Segoe UI", 7)).pack(side="right", padx=6)

    # ── Main 3-pane layout ────────────────────────────────────────────────────

    def _build_main(self):
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # ── Left: Groups sidebar ──────────────────────────────────────────────
        left = tk.Frame(paned, bg=C["mantle"], width=170)
        left.pack_propagate(False)
        paned.add(left, weight=0)

        tk.Label(left, text="  GRUPOS", bg=C["mantle"], fg=C["blue"],
                  font=("Segoe UI", 8, "bold"), anchor="w").pack(
            fill="x", padx=6, pady=(12, 4))
        tk.Frame(left, bg=C["s1"], height=1).pack(fill="x", padx=6)

        lb_fr = tk.Frame(left, bg=C["mantle"])
        lb_fr.pack(fill="both", expand=True, padx=4, pady=4)

        lb_scroll = ttk.Scrollbar(lb_fr, orient="vertical")
        lb_scroll.pack(side="right", fill="y")

        self._group_lb = tk.Listbox(
            lb_fr,
            bg=C["mantle"], fg=C["text"],
            selectbackground=C["s0"],
            selectforeground=C["blue"],
            activestyle="none",
            font=("Segoe UI", 9),
            relief="flat", bd=0,
            highlightthickness=0,
            yscrollcommand=lb_scroll.set,
            cursor="hand2",
        )
        lb_scroll.config(command=self._group_lb.yview)
        self._group_lb.pack(fill="both", expand=True)
        self._group_lb.bind("<<ListboxSelect>>", self._on_group_select)

        # ── Middle: Channels table ────────────────────────────────────────────
        middle = tk.Frame(paned, bg=C["base"])
        paned.add(middle, weight=3)

        tree_outer = tk.Frame(middle, bg=C["base"],
                               highlightbackground=C["s1"],
                               highlightthickness=1)
        tree_outer.pack(fill="both", expand=True, padx=6, pady=6)

        self._tree = ttk.Treeview(tree_outer, columns=TREE_COLS,
                                   show="headings", selectmode="browse")
        for status, color in STATUS_FG.items():
            self._tree.tag_configure(status, foreground=color)
        self._tree.tag_configure("even", background="#252537")
        self._tree.tag_configure("odd",  background=C["s0"])

        for col in TREE_COLS:
            self._tree.heading(col, text=COL_HDR[col],
                                command=lambda c=col: self._sort(c))
            anch = "center" if col in ("quality", "peer", "status") else "w"
            self._tree.column(col, width=COL_W[col], minwidth=40, anchor=anch)

        vsb = ttk.Scrollbar(tree_outer, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_outer, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>",          self._on_select)
        self._tree.bind("<Button-3>",          self._on_right_click)
        self._tree.bind("<Delete>",            self._cmd_delete)

        # ── Right: Edit panel ─────────────────────────────────────────────────
        right = tk.Frame(paned, bg=C["mantle"], width=345)
        right.pack_propagate(False)
        paned.add(right, weight=0)
        self._build_edit_panel(right)

    # ── Edit panel ────────────────────────────────────────────────────────────

    def _build_edit_panel(self, parent: tk.Frame):
        # Placeholder
        self._ph = tk.Frame(parent, bg=C["mantle"])
        self._ph.place(relwidth=1, relheight=1)
        tk.Label(self._ph, text="◈", bg=C["mantle"], fg=C["ov0"],
                  font=("Segoe UI", 36)).pack(expand=True, pady=(90, 8))
        tk.Label(self._ph, text="Selecciona un canal\npara editar sus propiedades",
                  bg=C["mantle"], fg=C["ov0"],
                  font=("Segoe UI", 10), justify="center").pack()

        # Form container
        self._form_frame = tk.Frame(parent, bg=C["mantle"])
        self._form_frame.place(relwidth=1, relheight=1)
        self._form_frame.lower()

        # ── Channel header card ───────────────────────────────────────────────
        hdr = tk.Frame(self._form_frame, bg=C["crust"], padx=16, pady=12)
        hdr.pack(fill="x")

        self._fn_name = tk.Label(hdr, text="",
            bg=C["crust"], fg=C["text"],
            font=("Segoe UI", 11, "bold"),
            wraplength=295, justify="left", anchor="w")
        self._fn_name.pack(fill="x")

        self._fn_sub = tk.Label(hdr, text="",
            bg=C["crust"], fg=C["sub0"],
            font=("Segoe UI", 8), anchor="w")
        self._fn_sub.pack(fill="x", pady=(2, 0))

        tk.Frame(self._form_frame, bg=C["s1"], height=1).pack(fill="x")

        # ── Scrollable form ───────────────────────────────────────────────────
        canvas_fr = tk.Frame(self._form_frame, bg=C["mantle"])
        canvas_fr.pack(fill="both", expand=True)

        scrl = ttk.Scrollbar(canvas_fr, orient="vertical")
        scrl.pack(side="right", fill="y")

        canvas = tk.Canvas(canvas_fr, bg=C["mantle"],
                            highlightthickness=0, bd=0)
        canvas.configure(yscrollcommand=scrl.set)
        scrl.config(command=canvas.yview)
        canvas.pack(fill="both", expand=True)

        form = tk.Frame(canvas, bg=C["mantle"])
        win_id = canvas.create_window((0, 0), window=form, anchor="nw")

        def _resize_form(e):
            canvas.itemconfig(win_id, width=e.width)
        def _update_scroll(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.bind("<Configure>", _resize_form)
        form.bind("<Configure>",   _update_scroll)

        def _wheel(e):
            canvas.yview_scroll(-1 * int(e.delta / 120), "units")
        canvas.bind("<Enter>",  lambda _: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>",  lambda _: canvas.unbind_all("<MouseWheel>"))

        # ── Form fields ───────────────────────────────────────────────────────

        def section(text):
            fr = tk.Frame(form, bg=C["mantle"])
            fr.pack(fill="x", padx=14, pady=(10, 2))
            tk.Label(fr, text=text, bg=C["mantle"], fg=C["blue"],
                      font=("Segoe UI", 8, "bold")).pack(side="left")
            tk.Frame(fr, bg=C["s1"], height=1).pack(
                side="left", fill="x", expand=True, padx=(8, 0), pady=1)

        def lbl(text):
            tk.Label(form, text=text, bg=C["mantle"], fg=C["sub0"],
                      font=("Segoe UI", 8), anchor="w").pack(
                fill="x", padx=14, pady=(5, 1))

        def ent(var):
            e = ttk.Entry(form, textvariable=var)
            e.pack(fill="x", padx=14, pady=(0, 2))
            return e

        def combo(var, values, width=None):
            kwargs = {"textvariable": var, "values": values, "state": "readonly"}
            if width:
                kwargs["width"] = width
            cb = ttk.Combobox(form, **kwargs)
            cb.pack(fill="x", padx=14, pady=(0, 2))
            return cb

        # ── Identidad ─────────────────────────────────────────────────────────
        section("IDENTIDAD")
        lbl("Canal");  self._fv_channel = tk.StringVar(); ent(self._fv_channel)
        lbl("Grupo");  self._fv_group   = tk.StringVar(); ent(self._fv_group)

        row_fr = tk.Frame(form, bg=C["mantle"])
        row_fr.pack(fill="x", padx=14, pady=(4, 2))
        row_fr.columnconfigure((1, 3), weight=1)

        tk.Label(row_fr, text="Calidad", bg=C["mantle"], fg=C["sub0"],
                  font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w", padx=(0, 4))
        tk.Label(row_fr, text="Estado",  bg=C["mantle"], fg=C["sub0"],
                  font=("Segoe UI", 8)).grid(row=0, column=2, sticky="w", padx=(8, 4))

        self._fv_quality = tk.StringVar()
        self._fv_status  = tk.StringVar()
        ttk.Combobox(row_fr, textvariable=self._fv_quality,
                     values=QUALITIES, state="readonly").grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(0, 4))
        stat_cb = ttk.Combobox(row_fr, textvariable=self._fv_status,
                     values=STATUSES, state="readonly")
        stat_cb.grid(row=1, column=2, columnspan=2, sticky="ew", padx=(4, 0))

        lbl("Fuente");  self._fv_source = tk.StringVar(); ent(self._fv_source)
        lbl("TVG-ID");  self._fv_tvgid  = tk.StringVar(); ent(self._fv_tvgid)

        # ── Peer Hash ─────────────────────────────────────────────────────────
        section("PEER HASH  (AceStream ID)")

        self._fv_peer = tk.StringVar()
        peer_ent = ttk.Entry(form, textvariable=self._fv_peer,
                              font=("Consolas", 9))
        peer_ent.pack(fill="x", padx=14, pady=(0, 4))
        peer_ent.bind("<Return>", lambda _: self._apply_edit())

        cp_fr = tk.Frame(form, bg=C["mantle"])
        cp_fr.pack(fill="x", padx=14, pady=(0, 6))
        ttk.Button(cp_fr, text="📋  Copiar hash",
                    style="Muted.TButton",
                    command=self._copy_peer).pack(side="left")

        # ── Extras ────────────────────────────────────────────────────────────
        section("EXTRAS")
        lbl("Logo URL"); self._fv_logo  = tk.StringVar(); ent(self._fv_logo)
        lbl("Notas");    self._fv_notes = tk.StringVar(); ent(self._fv_notes)

        # ── Action buttons ────────────────────────────────────────────────────
        tk.Frame(form, bg=C["s1"], height=1).pack(fill="x", padx=14, pady=(10, 0))
        btn_fr = tk.Frame(form, bg=C["mantle"])
        btn_fr.pack(fill="x", padx=14, pady=12)
        ttk.Button(btn_fr, text="✔  Guardar cambios",
                    style="Success.TButton",
                    command=self._apply_edit).pack(fill="x", pady=(0, 6))
        ttk.Button(btn_fr, text="✖  Descartar selección",
                    style="Danger.TButton",
                    command=self._clear_edit).pack(fill="x")

        # padding at bottom
        tk.Frame(form, bg=C["mantle"], height=20).pack()

    # ── Context menu ──────────────────────────────────────────────────────────

    def _build_context_menu(self):
        self._ctx = tk.Menu(self,
            bg=C["s0"], fg=C["text"],
            activebackground=C["s1"], activeforeground=C["blue"],
            relief="flat", bd=1, font=("Segoe UI", 9))

        self._ctx.add_command(label="✏   Editar canal",     command=self._on_select)
        self._ctx.add_command(label="📋  Copiar Peer Hash",  command=self._copy_peer)
        self._ctx.add_separator()

        sm = tk.Menu(self._ctx, bg=C["s0"], fg=C["text"],
            activebackground=C["s1"], activeforeground=C["blue"],
            relief="flat", bd=1, font=("Segoe UI", 9))
        for st in STATUSES:
            fg = STATUS_FG[st]
            sm.add_command(label=f"  {st}",
                            foreground=fg, activeforeground=fg,
                            command=lambda s=st: self._quick_status(s))
        self._ctx.add_cascade(label="⇄   Cambiar estado", menu=sm)
        self._ctx.add_separator()
        self._ctx.add_command(label="⧉   Duplicar como BACKUP", command=self._cmd_duplicate)
        self._ctx.add_separator()
        self._ctx.add_command(label="🗑   Eliminar canal",
                               foreground=C["red"], activeforeground=C["red"],
                               command=self._cmd_delete)

    def _on_right_click(self, event):
        row = self._tree.identify_row(event.y)
        if not row:
            return
        self._tree.selection_set(row)
        self._on_select()
        try:
            self._ctx.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx.grab_release()

    # ── Data loading ──────────────────────────────────────────────────────────

    def _auto_load(self):
        if os.path.isfile(CSV_FILE):
            self._load_csv(CSV_FILE)
        elif os.path.isfile(M3U_FILE):
            if messagebox.askyesno(
                "Convertir lista",
                f"No se encontró channels.csv.\n"
                f"¿Importar {os.path.basename(M3U_FILE)} y crear el CSV?"):
                self._do_import(M3U_FILE)

    def _load_csv(self, path: str):
        self._channels = load_csv(path)
        self._csv_path = path
        self._unsaved  = False
        self._refresh_all()
        self.title(f"IPTV Channel Editor  —  {os.path.basename(path)}")
        self._subtitle_lbl.config(text=os.path.basename(path))
        self._set_status(f"✓  {len(self._channels)} canales cargados")

    def _refresh_all(self):
        self._populate_groups()
        self._apply_filter()
        self._update_stats()

    def _populate_groups(self):
        counts = Counter(ch.get("group", "") for ch in self._channels)
        groups = sorted(counts.keys())
        self._group_lb.delete(0, "end")
        self._group_lb.insert("end", f"  Todos  ({len(self._channels)})")
        for g in groups:
            self._group_lb.insert("end", f"  {g}  ({counts[g]})")
        self._group_lb.selection_set(0)

    def _update_stats(self):
        counts = Counter(ch.get("status", "") for ch in self._channels)
        for st, lbl in self._stat_lbls.items():
            lbl.config(text=str(counts.get(st, 0)))

    # ── Filtering & display ───────────────────────────────────────────────────

    def _on_group_select(self, _event=None):
        sel = self._group_lb.curselection()
        if not sel:
            return
        raw = self._group_lb.get(sel[0]).strip()
        m = re.match(r"^(.+?)\s+\(\d+\)$", raw)
        name = m.group(1).strip() if m else raw
        self._active_group = "Todos" if name.lower() == "todos" else name
        self._apply_filter()

    def _apply_filter(self):
        query  = self._filter_var.get().lower()
        grp_f  = self._active_group
        stat_f = self._stat_filter.get()
        self._filtered = [
            i for i, ch in enumerate(self._channels)
            if (grp_f  == "Todos" or ch.get("group")  == grp_f)
            and (stat_f == "Todos" or ch.get("status") == stat_f)
            and (not query or any(
                query in ch.get(k, "").lower()
                for k in ("group", "channel", "source", "peer_full",
                           "tvg_id", "notes", "quality")
            ))
        ]
        self._refresh_tree()

    def _refresh_tree(self):
        prev = self._tree.selection()
        self._tree.delete(*self._tree.get_children())
        for row_n, idx in enumerate(self._filtered):
            ch     = self._channels[idx]
            status = ch.get("status", "")
            parity = "even" if row_n % 2 == 0 else "odd"
            self._tree.insert("", "end", iid=str(idx),
                               values=(
                                   ch.get("channel", ""),
                                   ch.get("quality", ""),
                                   ch.get("source", ""),
                                   peer_short(ch.get("peer_full", "")),
                                   status,
                               ),
                               tags=(status, parity))
        if prev and prev[0] in {str(i) for i in self._filtered}:
            self._tree.selection_set(prev[0])
            self._tree.see(prev[0])

        n, t = len(self._filtered), len(self._channels)
        self._set_status(f"Mostrando {n} / {t} canales")
        self._update_unsaved_label()

    # ── Selection & edit ─────────────────────────────────────────────────────

    def _on_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._sel_idx = idx
        ch = self._channels[idx]

        self._fv_channel.set(ch.get("channel", ""))
        self._fv_group.set(ch.get("group", ""))
        self._fv_quality.set(ch.get("quality", ""))
        self._fv_status.set(ch.get("status", "MAIN"))
        self._fv_source.set(ch.get("source", ""))
        self._fv_tvgid.set(ch.get("tvg_id", ""))
        self._fv_peer.set(ch.get("peer_full", ""))
        self._fv_logo.set(ch.get("tvg_logo", ""))
        self._fv_notes.set(ch.get("notes", ""))

        self._fn_name.config(text=ch.get("channel", "(sin nombre)"))
        parts = [p for p in [
            ch.get("group", ""),
            ch.get("quality", ""),
            ch.get("source", ""),
        ] if p]
        ps = peer_short(ch.get("peer_full", ""))
        if ps:
            parts.append(f"[{ps}]")
        self._fn_sub.config(text="  ·  ".join(parts))

        self._form_frame.lift()

    def _apply_edit(self):
        if self._sel_idx is None:
            return
        peer = self._fv_peer.get().strip()
        if peer and not re.fullmatch(r"[0-9a-fA-F]+", peer):
            messagebox.showwarning("Peer inválido",
                "El hash de AceStream solo admite caracteres hexadecimales.")
            return
        ch = self._channels[self._sel_idx]
        ch["channel"]  = self._fv_channel.get().strip()
        ch["group"]    = self._fv_group.get().strip()
        ch["quality"]  = self._fv_quality.get().strip()
        ch["status"]   = self._fv_status.get().strip()
        ch["source"]   = self._fv_source.get().strip()
        ch["tvg_id"]   = self._fv_tvgid.get().strip()
        ch["peer_full"] = peer
        ch["tvg_logo"] = self._fv_logo.get().strip()
        ch["notes"]    = self._fv_notes.get().strip()
        self._unsaved = True
        saved = self._sel_idx
        self._refresh_all()
        # Restore selection + re-populate form header
        if str(saved) in {str(i) for i in self._filtered}:
            self._tree.selection_set(str(saved))
            self._tree.see(str(saved))
            self._sel_idx = saved
            self._on_select()
        self._set_status(f"✓  «{ch['channel']}» guardado")

    def _clear_edit(self):
        self._sel_idx = None
        self._tree.selection_remove(*self._tree.selection())
        self._ph.lift()

    # ── Context menu actions ──────────────────────────────────────────────────

    def _copy_peer(self):
        if self._sel_idx is None:
            return
        peer = self._channels[self._sel_idx].get("peer_full", "")
        self.clipboard_clear()
        self.clipboard_append(peer)
        self._set_status(f"✓  Peer copiado al portapapeles  [{peer_short(peer)}]")

    def _quick_status(self, status: str):
        if self._sel_idx is None:
            return
        self._channels[self._sel_idx]["status"] = status
        self._fv_status.set(status)
        self._unsaved = True
        saved = self._sel_idx
        self._refresh_all()
        if str(saved) in {str(i) for i in self._filtered}:
            self._tree.selection_set(str(saved))
            self._sel_idx = saved
            self._on_select()
        self._set_status(f"✓  Estado → {status}")

    def _cmd_duplicate(self):
        if self._sel_idx is None:
            return
        dup = copy.deepcopy(self._channels[self._sel_idx])
        dup["status"] = "BACKUP"
        new_idx = self._sel_idx + 1
        self._channels.insert(new_idx, dup)
        self._unsaved = True
        self._refresh_all()
        if str(new_idx) in {str(i) for i in self._filtered}:
            self._tree.selection_set(str(new_idx))
            self._sel_idx = new_idx
            self._on_select()
        self._set_status(f"✓  Canal duplicado como BACKUP")

    def _cmd_delete(self, _event=None):
        if self._sel_idx is None:
            return
        name = self._channels[self._sel_idx].get("channel", "?")
        if not messagebox.askyesno("Eliminar canal",
                f"¿Eliminar «{name}» definitivamente?\nEsta acción no se puede deshacer."):
            return
        self._channels.pop(self._sel_idx)
        self._unsaved = True
        self._sel_idx = None
        self._clear_edit()
        self._refresh_all()
        self._set_status(f"✓  «{name}» eliminado")

    # ── Sorting ───────────────────────────────────────────────────────────────

    def _sort(self, col: str):
        self._sort_rev = (not self._sort_rev) if self._sort_col == col else False
        self._sort_col = col
        key_fn = {
            "channel": lambda i: self._channels[i].get("channel", "").lower(),
            "quality": lambda i: self._channels[i].get("quality", "").lower(),
            "source":  lambda i: self._channels[i].get("source", "").lower(),
            "peer":    lambda i: peer_short(self._channels[i].get("peer_full", "")),
            "status":  lambda i: STATUS_ORDER.get(
                self._channels[i].get("status", ""), 99),
        }
        if col in key_fn:
            self._filtered.sort(key=key_fn[col], reverse=self._sort_rev)
        self._refresh_tree()

    # ── Commands ─────────────────────────────────────────────────────────────

    def _cmd_open(self):
        if self._unsaved and not messagebox.askyesno(
                "Sin guardar", "¿Descartar cambios y abrir otro CSV?"):
            return
        path = filedialog.askopenfilename(
            title="Abrir CSV",
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
            initialdir=BASE_DIR,
        )
        if path:
            self._load_csv(path)

    def _cmd_save(self):
        if not self._csv_path:
            self._csv_path = filedialog.asksaveasfilename(
                title="Guardar CSV",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")],
                initialdir=BASE_DIR,
                initialfile="channels.csv",
            )
            if not self._csv_path:
                return
        save_csv(self._csv_path, self._channels)
        self._unsaved = False
        self._update_unsaved_label()
        self._set_status(f"✓  CSV guardado  →  {os.path.basename(self._csv_path)}")
        self.title(f"IPTV Channel Editor  —  {os.path.basename(self._csv_path)}")

    def _cmd_generate(self):
        if not self._channels:
            messagebox.showinfo("Sin datos", "No hay canales cargados.")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar M3U generado",
            defaultextension=".m3u",
            filetypes=[("M3U playlist", "*.m3u *.m3u8"), ("Todos", "*.*")],
            initialdir=BASE_DIR,
            initialfile="lista_iptv_clean.m3u",
        )
        if not path:
            return
        only_main = messagebox.askyesno(
            "Modo generación",
            "¿Incluir SOLO streams MAIN?\n\n"
            "  Sí  →  lista compacta (un stream por canal)\n"
            "  No  →  incluir MAIN + BACKUP + TEST\n"
            "         (los DISABLED quedan comentados)",
        )
        stats = generate_m3u(self._channels, path, only_main=only_main)
        active = stats["MAIN"] + stats["BACKUP"] + stats["TEST"]
        self._set_status(
            f"✓  M3U generado  ·  {active} activos  ·  "
            f"{stats['DISABLED']} desactivados  →  {os.path.basename(path)}")

    def _cmd_import(self):
        path = filedialog.askopenfilename(
            title="Importar M3U",
            filetypes=[("M3U playlist", "*.m3u *.m3u8"), ("Todos", "*.*")],
            initialdir=BASE_DIR,
        )
        if not path:
            return
        if self._unsaved and not messagebox.askyesno(
                "Sin guardar", "¿Descartar cambios e importar el M3U?"):
            return
        self._do_import(path)

    def _do_import(self, path: str):
        channels = import_m3u(path)
        self._channels = channels
        base = os.path.splitext(os.path.basename(path))[0]
        self._csv_path = os.path.join(BASE_DIR, f"{base}_channels.csv")
        self._unsaved  = True
        self._refresh_all()
        self._subtitle_lbl.config(text=os.path.basename(self._csv_path) + " *")
        self.title(f"IPTV Channel Editor  —  {os.path.basename(self._csv_path)} *")
        main_c = sum(1 for c in channels if c["status"] == "MAIN")
        self._set_status(
            f"✓  {len(channels)} streams importados ({main_c} MAIN)  ·  "
            f"Ctrl+S para guardar el CSV")

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        if self._unsaved:
            ans = messagebox.askyesnocancel(
                "Sin guardar",
                "Hay cambios sin guardar.\n¿Guardar el CSV antes de salir?")
            if ans is None:
                return
            if ans:
                self._cmd_save()
        self.destroy()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    def _update_unsaved_label(self):
        self._unsaved_lbl.config(
            text="⚠  Sin guardar  ·  Ctrl+S" if self._unsaved else "")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ChannelEditor()
    app.mainloop()
