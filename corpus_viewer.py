#!/usr/bin/env python3
"""Local, read-only workspace for browsing VIGILYX email training records."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event
import time
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

from corpus_catalog import CorpusCatalog, CorpusFileChangedError, CorpusPages, summarize
from corpus_detail import VIEWS, comparison_sections, detail_sections, record_json


DEFAULT_CORPUS = Path(__file__).resolve().parent / "data" / "corpus.json"
BG, PAPER, TINT, LINE = "#eef2f5", "#ffffff", "#f5f8fa", "#dce4ea"
INK, MUTED = "#142737", "#526675"
NAV, NAV_LINE, NAV_MUTED = "#102735", "#2b4654", "#aec3cc"
ACCENT, ACCENT_LIGHT, SEL = "#00685f", "#e3f4ed", "#d8eee9"
WARNING, DANGER_BG = "#a13f37", "#fcece8"
LABELS = {
    "label": {"malicious": "恶意", "benign": "正常"},
    "domain": {"finance": "金融", "accounting": "财会", "shopping": "消费", "workplace": "职场"},
    "difficulty": {"easy": "简单", "medium": "中等", "hard": "困难"},
    "language": {"zh": "中文", "en": "英文", "zh-en": "中英双语"},
}
FACETS = {"label": "标签", "domain": "领域", "difficulty": "难度", "language": "语言"}
ORDERS = {"newest": "最新加入", "oldest": "最早加入", "subject": "按主题排序"}


def string(value):
    """Convert metadata to Tk-safe display text."""
    if value is None:
        return ""
    return str(value).encode("utf-8", errors="replace").decode("utf-8")


def one_line(value):
    return " ".join(string(value).split())


def display_facet(key, value):
    return LABELS[key].get(value, one_line(value) or "未标注")


def yield_to_window(_read, _total):
    # Yield periodically during indexing so Aqua can process redraw and input events.
    time.sleep(0.001)



class CorpusViewer:
    def __init__(self, root, pages):
        self.root = root
        self.pages = pages
        self.page_size = pages.page_size
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="corpus")
        self.cancel = Event()
        self.session = 0
        self.request = 0
        self.search_timer = None
        self.query_job = None
        self.catalog = None
        self.matches = ()
        self.records = []
        self.rows = ()
        self.page_index = 0
        self.has_next = False
        self.loading = False
        self.indexing = False
        self.empty_text = "正在打开语料…"
        self.record = None
        self.summary = None
        self.rendered = {}
        self.links = {}
        self.stale = False
        self.evidence_on = False
        self.practice = tk.BooleanVar(root, False)
        self.revealed = False
        self.native_modifier = "Command" if root.tk.call("tk", "windowingsystem") == "aqua" else "Control"
        self.flavor = "⌘" if self.native_modifier == "Command" else "Ctrl+"

        root.title("VIGILYX · 邮件语料工作台")
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(1420, screen_w - 64)}x{min(900, screen_h - 110)}")
        root.minsize(940, 590)
        root.configure(bg=BG)
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.configure_styles()
        self.build_header()
        self.build_workspace()
        self.build_footer()
        self.bind_keys()
        self.open_file(pages.path, reuse=pages)

    def configure_styles(self):
        f = font.nametofont("TkDefaultFont", self.root).actual("family")
        fixed = font.nametofont("TkFixedFont", self.root).actual("family")
        self.ui = ("PingFang SC" if sys.platform == "darwin" else f, 12)
        self.small = (self.ui[0], 11)
        self.mono = (fixed, 10)
        self.style = s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", font=self.ui, background=PAPER, foreground=INK)
        s.configure("TFrame", background=PAPER)
        s.configure("TLabel", background=PAPER, foreground=INK)
        s.configure("Muted.TLabel", foreground=MUTED, font=self.small)
        s.configure("TButton", padding=(10, 6), borderwidth=1,
                    bordercolor=LINE, lightcolor=PAPER, darkcolor=PAPER,
                    background=PAPER, focuscolor=ACCENT, focusthickness=1)
        s.map("TButton", background=[("pressed", SEL), ("active", TINT)],
              foreground=[("disabled", "#7a8b95")])
        s.configure("Primary.TButton", background=ACCENT, foreground=PAPER,
                    bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        s.map("Primary.TButton", background=[("active", "#00574e")], foreground=[("disabled", "#dae5e2")])
        s.configure("Nav.TButton", background=NAV, foreground="#eaf4f7", bordercolor=NAV_LINE,
                    lightcolor=NAV, darkcolor=NAV, focuscolor="#79ccba")
        s.map("Nav.TButton", background=[("active", NAV_LINE)], foreground=[("disabled", NAV_MUTED)])
        s.configure("Quiet.TButton", padding=(7, 4), bordercolor=PAPER, focuscolor=ACCENT)
        s.configure("Tool.TMenubutton", padding=(9, 6), bordercolor=LINE,
                    lightcolor=PAPER, darkcolor=PAPER, arrowcolor=MUTED)
        s.map("Tool.TMenubutton", background=[("active", TINT)], foreground=[("disabled", "#7a8b95")])
        s.configure("TCombobox", background=TINT, fieldbackground=PAPER, foreground=INK,
                    selectbackground=PAPER, selectforeground=INK, bordercolor=LINE, arrowcolor=MUTED,
                    lightcolor=PAPER, darkcolor=PAPER, padding=(5, 3))
        s.map("TCombobox", fieldbackground=[("disabled", TINT), ("readonly", PAPER)],
              foreground=[("disabled", "#7a8b95")], bordercolor=[("focus", ACCENT)])
        s.configure("Search.TEntry", fieldbackground=TINT, bordercolor=LINE,
                    lightcolor=TINT, darkcolor=TINT, insertcolor=INK, padding=(9, 8))
        s.map("Search.TEntry", bordercolor=[("focus", ACCENT)])
        s.configure("Workspace.TPanedwindow", background=BG, sashthickness=13)
        s.configure("Treeview", background=PAPER, fieldbackground=PAPER,
                    foreground=INK, borderwidth=0, rowheight=34, font=self.ui)
        s.map("Treeview", background=[("selected", SEL)], foreground=[("selected", "#054e46")])
        s.configure("Treeview.Heading", background=TINT, foreground=MUTED, font=(*self.small, "bold"),
                    relief="flat", borderwidth=0, padding=(7, 6))
        s.map("Treeview.Heading", background=[("active", TINT)])
        s.configure("TNotebook", background=PAPER, borderwidth=0, tabmargins=(10, 0, 10, 0))
        s.configure("TNotebook.Tab", background=TINT, foreground=MUTED, font=self.small,
                    padding=(10, 9), bordercolor=LINE, lightcolor=TINT, darkcolor=TINT)
        s.map("TNotebook.Tab", background=[("selected", ACCENT_LIGHT), ("active", TINT)],
              foreground=[("selected", ACCENT), ("active", INK)], bordercolor=[("selected", ACCENT)])
        s.configure("Vertical.TScrollbar", background="#c1cdd5", troughcolor=TINT, arrowsize=10,
                    arrowcolor=MUTED, bordercolor=TINT, lightcolor="#c1cdd5", darkcolor="#c1cdd5")
        s.configure("Horizontal.TScrollbar", background="#c1cdd5", troughcolor=TINT, arrowsize=10,
                    arrowcolor=MUTED, bordercolor=TINT, lightcolor="#c1cdd5", darkcolor="#c1cdd5")

    def line(self, parent, color=LINE):
        tk.Frame(parent, bg=color, height=1).pack(fill="x")

    def text_label(self, parent, text="", *, bg=PAPER, fg=INK, face=None, **kwargs):
        return tk.Label(parent, text=text, bg=bg, fg=fg, font=face or self.ui, **kwargs)

    def build_header(self):
        mast = tk.Frame(self.root, bg=NAV, padx=22, pady=13)
        mast.grid(row=0, column=0, sticky="ew")
        mark = tk.Canvas(mast, width=42, height=42, bg=NAV, highlightthickness=0)
        mark.pack(side="left", padx=(0, 12))
        mark.create_polygon(9, 1, 33, 1, 41, 9, 41, 33, 33, 41, 9, 41, 1, 33, 1, 9,
                            fill="#0d574f")
        mark.create_line(10, 14, 21, 23, 32, 14, fill="#b4f3de", width=2, capstyle="round",
                         joinstyle="round")
        mark.create_rectangle(10, 13, 32, 29, outline="#b4f3de", width=2)
        identity = tk.Frame(mast, bg=NAV)
        identity.pack(side="left")
        self.text_label(identity, "VIGILYX  /  TRAINING DATA", bg=NAV, fg="#81d1b9",
                        face=(*self.mono, "bold"), anchor="w").pack(fill="x")
        self.text_label(identity, "邮件语料工作台", bg=NAV, fg="#f0f7fa",
                        face=(self.ui[0], 22, "bold"), anchor="w").pack(fill="x")

        self.mode_button = ttk.Button(mast, text="进入盲测", style="Nav.TButton", command=self.toggle_practice)
        self.mode_button.pack(side="right")
        ttk.Button(mast, text="重新载入", style="Nav.TButton", command=self.reload).pack(side="right", padx=8)
        ttk.Button(mast, text="打开文件…", style="Nav.TButton", command=self.choose_file).pack(side="right")
        data = tk.Frame(mast, bg=NAV)
        data.pack(side="right", padx=(8, 18))
        self.text_label(data, "当前语料", bg=NAV, fg=NAV_MUTED, face=self.small, anchor="e").pack(fill="x")
        self.filename = self.text_label(data, bg=NAV, fg="#eff8fa", face=(*self.small, "bold"), anchor="e")
        self.filename.pack(fill="x")

    def build_workspace(self):
        self.split = ttk.Panedwindow(self.root, orient="horizontal", style="Workspace.TPanedwindow")
        self.split.grid(row=1, column=0, sticky="nsew", padx=18, pady=(14, 4))
        self.sidebar = ttk.Frame(self.split, width=450)
        self.detail = ttk.Frame(self.split, width=760)
        self.split.add(self.sidebar, weight=0)
        self.split.add(self.detail, weight=1)
        self.split.bind("<ButtonRelease-1>", self.clamp_split, add="+")
        self.split.bind("<Configure>", self.clamp_split, add="+")
        self.root.after_idle(self.set_initial_split)

        toolbar = ttk.Frame(self.sidebar, padding=(14, 13, 14, 10))
        toolbar.pack(fill="x")
        toolbar.columnconfigure(0, weight=1, uniform="facet")
        toolbar.columnconfigure(1, weight=1, uniform="facet")
        self.text_label(toolbar, "样本库", face=(self.ui[0], 18, "bold"), anchor="w").grid(row=0, column=0, sticky="w")
        self.reset_button = ttk.Button(toolbar, text="重置检索", style="Quiet.TButton", command=self.reset_search)
        self.reset_button.grid(row=0, column=1, sticky="e")
        searchline = ttk.Frame(toolbar)
        searchline.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 3))
        self.query = tk.StringVar(self.root)
        self.search = ttk.Entry(searchline, textvariable=self.query, style="Search.TEntry")
        self.search.pack(side="left", fill="x", expand=True)
        ttk.Button(searchline, text="清空", style="Quiet.TButton", command=lambda: self.query.set("")).pack(side="right", padx=(4, 0))
        self.search.bind("<Return>", self.search_now)
        self.search.bind("<Escape>", lambda _event: self.query.set(""))
        self.query.trace_add("write", self.schedule_search)
        self.search_hint = self.text_label(toolbar, fg=MUTED, face=self.small, anchor="w",
                                           text=f"搜索主题、发件人、正文、往来或编号 · {self.flavor}F")
        self.search_hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(1, 6))
        self.filters = {}
        self.filter_labels = {}
        self.facets = {}
        for i, (key, title) in enumerate(FACETS.items()):
            col = i % 2
            row = 3 + (i // 2) * 2
            pad = (0, 5) if col == 0 else (5, 0)
            label = ttk.Label(toolbar, text=title, style="Muted.TLabel")
            label.grid(row=row, column=col, sticky="w", padx=pad)
            widget = ttk.Combobox(toolbar, width=9, state="disabled", values=(f"全部{title}",))
            widget.current(0)
            widget.grid(row=row + 1, column=col, sticky="ew", padx=pad, pady=(2, 6))
            widget.bind("<<ComboboxSelected>>", self.search_now)
            self.filters[key] = widget
            self.filter_labels[key] = label
            self.facets[key] = (None,)

        result = tk.Frame(self.sidebar, bg=TINT, padx=13, pady=6)
        result.pack(fill="x")
        self.result_title = self.text_label(result, bg=TINT, fg=MUTED, face=(*self.small, "bold"), anchor="w")
        self.result_title.pack(side="left", fill="x", expand=True)
        self.sort = ttk.Combobox(result, values=tuple(ORDERS.values()), width=10, state="disabled")
        self.sort.current(0)
        self.sort.pack(side="right")
        self.sort.bind("<<ComboboxSelected>>", self.search_now)

        listing = ttk.Frame(self.sidebar)
        listing.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(listing, columns=("subject", "label", "id"), show="headings", selectmode="browse")
        for key, title, width, minwidth, expand in (
            ("subject", "邮件主题", 244, 110, True),
            ("label", "标签", 55, 46, False),
            ("id", "样本编号", 110, 84, False),
        ):
            self.tree.column(key, width=width, minwidth=minwidth, stretch=expand,
                             anchor="w" if key == "subject" else "center")
            self.tree.heading(key, text=title, anchor="w" if key == "subject" else "center")
        self.tree.tag_configure("stripe", background="#f8fafb")
        bar = ttk.Scrollbar(listing, command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.select_record)
        self.tree.bind("<Return>", self.focus_detail)

        self.line(self.sidebar)
        paging = ttk.Frame(self.sidebar, padding=(12, 9))
        paging.pack(fill="x")
        self.previous = ttk.Button(paging, text="‹  上一页", command=lambda: self.change_page(-1))
        self.next = ttk.Button(paging, text="下一页  ›", command=lambda: self.change_page(1))
        self.previous.pack(side="left")
        self.next.pack(side="right")
        self.page_text = ttk.Label(paging, style="Muted.TLabel", anchor="center")
        self.page_text.pack(side="left", fill="x", expand=True)

        hero = ttk.Frame(self.detail, padding=(22, 14, 20, 12))
        hero.pack(fill="x")
        hero_top = ttk.Frame(hero)
        hero_top.pack(fill="x")
        self.kicker = self.text_label(hero_top, text="样本详情", fg=ACCENT, face=(*self.small, "bold"), anchor="w")
        self.kicker.pack(side="left")
        self.action_menu_button = ttk.Menubutton(hero_top, text="样本操作", style="Tool.TMenubutton")
        self.action_menu_button.pack(side="right")
        self.action_menu = tk.Menu(self.action_menu_button, tearoff=False)
        self.action_menu_button.configure(menu=self.action_menu)
        self.practice_button = ttk.Button(hero_top, text="揭晓答案", style="Primary.TButton", command=self.reveal_answer)
        self.pair_button = ttk.Button(hero_top, text="配对对照", command=self.compare_record)
        self.subject = self.text_label(hero, face=(self.ui[0], 23, "bold"), anchor="w", justify="left")
        self.subject.pack(fill="x", pady=(7, 5))
        self.subject.bind("<Configure>", self.wrap_title)
        meta = ttk.Frame(hero)
        meta.pack(fill="x")
        self.label_badge = self.text_label(meta, padx=8, pady=2, face=(*self.small, "bold"))
        self.label_badge.pack(side="left", padx=(0, 9))
        self.metadata = self.text_label(meta, fg=MUTED, face=self.small, anchor="w")
        self.metadata.pack(side="left", fill="x", expand=True)
        self.line(self.detail)

        self.tabs = ttk.Notebook(self.detail)
        self.tabs.pack(fill="both", expand=True, pady=(8, 0))
        self.frames = {}
        self.views = {}
        for key, title in VIEWS:
            frame, widget = self.make_reader(self.tabs, code=key == "json")
            self.tabs.add(frame, text=title)
            self.frames[key], self.views[key] = frame, widget
            widget.bind("<Motion>", lambda event, view=key: self.reader_motion(event, view))
            widget.bind("<Button-1>", lambda event, view=key: self.reader_click(event, view))
        self.tabs.bind("<<NotebookTabChanged>>", self.render_detail)

    def make_reader(self, parent, *, code=False):
        frame = ttk.Frame(parent)
        widget = tk.Text(frame, background=PAPER, foreground=INK, selectbackground=SEL,
                         selectforeground=INK, highlightthickness=0, borderwidth=0, padx=22, pady=14,
                         width=24, height=8,
                         wrap="none" if code else "word", spacing1=2, spacing2=5, spacing3=3,
                         font=(self.mono[0], 12) if code else (self.ui[0], 14), state="disabled")
        styles = {
            "title": {"font": (self.ui[0], 20, "bold"), "spacing3": 8},
            "section": {"font": (self.ui[0], 15, "bold"), "foreground": ACCENT, "spacing1": 11},
            "meta": {"foreground": MUTED, "font": self.small},
            "body": {},
            "quote": {"foreground": INK, "background": TINT, "lmargin1": 12, "lmargin2": 12},
            "link": {"foreground": ACCENT, "underline": True},
            "warning": {"foreground": WARNING},
            "code": {"font": (self.mono[0], 12), "foreground": INK},
            "evidence": {"background": "#fcf0c9"},
            "benign": {"foreground": ACCENT, "font": (*self.ui, "bold")},
            "malicious": {"foreground": WARNING, "font": (*self.ui, "bold")},
            "located": {"background": "#ffd87e"},
            "subsection": {"font": (*self.ui, "bold"), "spacing1": 5},
            "added": {"background": "#e0f4e8", "foreground": "#155e42"},
            "removed": {"background": DANGER_BG, "foreground": WARNING},
            "diff": {"background": TINT, "foreground": MUTED},
        }
        for name, opts in styles.items():
            widget.tag_configure(name, **opts)
        widget.tag_raise("sel")
        vbar = ttk.Scrollbar(frame, command=widget.yview)
        widget.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        if code:
            hbar = ttk.Scrollbar(frame, orient="horizontal", command=widget.xview)
            widget.configure(xscrollcommand=hbar.set)
            hbar.pack(side="bottom", fill="x")
        widget.pack(fill="both", expand=True)
        return frame, widget

    def build_footer(self):
        footer = tk.Frame(self.root, bg=BG, padx=19, pady=6)
        footer.grid(row=2, column=0, sticky="ew")
        self.status = self.text_label(footer, bg=BG, fg=MUTED, face=self.small, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.text_label(footer, "本地只读  ·  链接仅显示文本", bg=BG, fg=MUTED, face=self.small).pack(side="right", padx=(10, 0))

    def wrap_title(self, event):
        width = max(250, event.width - 6)
        if str(self.subject.cget("wraplength")) != str(width):
            self.subject.configure(wraplength=width)

    def set_initial_split(self):
        self.split.sashpos(0, 440)
        self.clamp_split()

    def clamp_split(self, _event=None):
        width = self.split.winfo_width()
        if width > 850:
            position = self.split.sashpos(0)
            target = min(width - 500, max(340, position))
            if position != target:
                self.split.sashpos(0, target)

    def bind_keys(self):
        def bind(key, callback):
            def handle(_event):
                callback()
                return "break"
            self.root.bind(f"<{self.native_modifier}-{key}>", handle)
        bind("f", self.focus_search)
        bind("o", self.choose_file)
        bind("r", self.reload)
        bind("bracketleft", lambda: self.change_page(-1))
        bind("bracketright", lambda: self.change_page(1))

    def focus_search(self):
        self.search.focus_set()
        self.search.selection_range(0, "end")

    def focus_detail(self, _event=None):
        view = self.current_view()
        if view:
            self.views[view].focus_set()
        return "break"

    def set_status(self, text, error=False):
        self.status.configure(text=text, fg=WARNING if error else MUTED)

    def choose_file(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="选择语料 JSON", initialdir=self.pages.path.parent,
            filetypes=(("JSON 语料", "*.json"), ("所有文件", "*")),
        )
        if path:
            self.open_file(Path(path))

    def reload(self):
        self.open_file(self.pages.path, preserve=True)

    def close(self):
        self.cancel.set()
        self.session += 1
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def run_job(self, action, success, failure, *, request=None):
        session = self.session
        future = self.executor.submit(action)

        def poll():
            if session != self.session or (request is not None and request != self.request):
                future.cancel()
                return
            if not future.done():
                self.root.after(20, poll)
                return
            try:
                data = future.result()
            except Exception as exc:
                failure(exc)
            else:
                success(data)

        self.root.after(15, poll)
        return future

    def open_file(self, path, *, reuse=None, preserve=False):
        file_filters = self.filter_values() if preserve else {}
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None
        self.cancel.set()
        self.cancel = Event()
        self.session += 1
        self.request += 1
        self.query_job = None
        self.pages = reuse if reuse is not None else CorpusPages(Path(path).expanduser().absolute(), self.page_size)
        name = self.pages.path.name
        self.filename.configure(text=one_line(name[:24] + "…" if len(name) > 25 else name))
        self.root.title(f"VIGILYX · 邮件语料工作台 — {one_line(name)}")
        self.catalog = None
        self.stale = False
        self.indexing = True
        self.loading = True
        self.matches = ()
        self.empty_text = "正在打开语料…"
        self.has_next = False
        if not preserve:
            self.query.set("")
            self.sort.current(0)
        self.sort.configure(state="disabled")
        self.populate_filters({})
        self.show_rows((), [], 0)
        self.set_status("正在读取最新样本…")
        reader = self.pages
        cancelled = self.cancel
        self.run_job(lambda: reader.read_page(0),
                     lambda batch: self.first_page(batch, reader, cancelled, file_filters),
                     self.open_error)

    def first_page(self, batch, reader, cancelled, file_filters):
        records, self.has_next = batch
        self.empty_text = "语料为空"
        self.loading = False
        self.show_rows(tuple(summarize(record, i) for i, record in enumerate(records)), records, 0)
        self.set_status("正在建立全库索引，可以先浏览已加载样本…")
        self.run_job(lambda: CorpusCatalog.build(reader.path, expected_version=reader.version,
                                                 cancelled=cancelled.is_set, progress=yield_to_window),
                     lambda catalog: self.catalog_ready(catalog, file_filters), self.index_error)

    def catalog_ready(self, catalog, file_filters):
        self.catalog = catalog
        self.indexing = False
        self.populate_filters(catalog.facets, file_filters)
        self.sort.configure(state="readonly")
        # Complete the first page without replacing its widgets unless search
        # settings already call for a different result set.
        order = self.sort.current()
        if not (self.query.get().strip() or self.filter_values() or order > 0):
            self.matches = catalog.select()
            self.update_navigation()
            self.update_record_tools()
            self.show_file_status()
        else:
            self.search_now()

    def open_error(self, error):
        self.loading = self.indexing = False
        self.empty_text = "无法读取语料"
        self.show_rows((), [], 0)
        self.set_status(f"{one_line(error)}　可打开另一份文件或重新载入。", error=True)

    def index_error(self, error):
        self.loading = self.indexing = False
        self.update_navigation()
        self.read_error(error, prefix="全库索引未就绪")

    def read_error(self, error, *, prefix="读取失败"):
        self.loading = False
        if isinstance(error, CorpusFileChangedError):
            self.request += 1
            self.stale = True
            self.catalog = None
            self.has_next = False
            self.matches = ()
            self.populate_filters({})
            self.sort.configure(state="disabled")
            self.update_record_tools()
            notice = "语料文件已更改。请点击「重新载入」读取新版本。"
        else:
            notice = f"{prefix}：{one_line(error)}"
        self.update_navigation()
        self.set_status(notice, error=True)

    def show_file_status(self):
        if self.catalog is None:
            return
        try:
            size = self.catalog.version[2]
            size_text = f"  ·  {size / (1024 * 1024):.1f} MB" if size >= 1024 * 1024 else f"  ·  {size:,} B"
        except (ValueError, IndexError, TypeError):
            size_text = ""
        self.set_status(f"全库 {len(self.catalog):,} 条{size_text}  ·  \u201c最新加入\u201d按语料追加顺序")

    def populate_filters(self, counts, saved=None):
        saved = saved or {}
        for key, widget in self.filters.items():
            facets = counts.get(key, {})
            keys = sorted(facets, key=lambda value: (-facets[value], display_facet(key, value)))
            self.facets[key] = (None, *keys)
            widget.configure(values=(f"全部{FACETS[key]}", *(
                f"{display_facet(key, value)}  ({facets[value]:,})" for value in keys
            )))
            value = saved.get(key)
            widget.current(self.facets[key].index(value) if value in self.facets[key] else 0)
            widget.configure(state="readonly" if facets else "disabled")

    def filter_values(self):
        output = {}
        for key, widget in self.filters.items():
            if key == "label" and self.practice.get():
                continue
            idx = widget.current()
            if 0 < idx < len(self.facets[key]):
                output[key] = self.facets[key][idx]
        return output

    def reset_search(self):
        self.query.set("")
        for widget in self.filters.values():
            widget.current(0)
        self.sort.current(0)
        self.search_now()
        self.focus_search()

    def schedule_search(self, *_args):
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
        if self.catalog is not None:
            self.request += 1
            if self.query_job is not None:
                self.query_job.cancel()
            self.loading = True
            self.update_navigation()
        self.search_timer = self.root.after(200, self.search_now)

    def search_now(self, _event=None, *, keep_ordinal=None):
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None
        catalog = self.catalog
        if catalog is None:
            return
        query, filters, blind = self.query.get().strip(), self.filter_values(), self.practice.get()
        order = tuple(ORDERS)[max(0, self.sort.current())]

        def search_page():
            matches = catalog.select(query, filters, order, blind=blind)
            pos = 0
            if keep_ordinal is not None:
                pos = next((i for i, row in enumerate(matches) if row.ordinal == keep_ordinal), 0)
            index = pos // self.page_size
            start = index * self.page_size
            rows = matches[start:start + self.page_size]
            return matches, rows, catalog.read_records(rows), index, pos - start

        self.submit_query(search_page, self.search_done)
        return "break"

    def submit_query(self, action, success):
        self.request += 1
        if self.query_job is not None:
            self.query_job.cancel()
        self.loading = True
        self.update_navigation()
        self.query_job = self.run_job(action, success, self.read_error, request=self.request)

    def search_done(self, result):
        self.matches, rows, records, index, selected = result
        self.loading = False
        self.empty_text = "没有匹配样本" if len(self.catalog) else "语料为空"
        self.show_rows(rows, records, index, selected=str(selected))
        self.show_file_status()

    def change_page(self, step):
        index = self.page_index + step
        if self.loading or self.stale or index < 0:
            return
        if self.catalog is None:
            if step > 0 and not self.has_next:
                return
            reader = self.pages

            def page_done(batch):
                records, self.has_next = batch
                self.loading = False
                self.show_rows(tuple(summarize(record, index * self.page_size + i)
                                     for i, record in enumerate(records)), records, index)
            self.submit_query(lambda: reader.read_page(index), page_done)
            return
        catalog = self.catalog
        rows = self.matches[index * self.page_size:(index + 1) * self.page_size]
        if not rows:
            return

        def page_done(records):
            self.loading = False
            self.show_rows(rows, records, index)
            self.show_file_status()

        self.submit_query(lambda: catalog.read_records(rows), page_done)

    def update_navigation(self):
        start = self.page_index * self.page_size
        if self.catalog is not None:
            count = len(self.matches)
            pages = (count + self.page_size - 1) // self.page_size
            found = f"{count:,} 条结果"
            position = f"{self.page_index + 1} / {pages:,}" if count else "—"
            can_next = start + self.page_size < count
        else:
            found = "索引构建中…" if self.indexing else f"本页 {len(self.rows):,} 条"
            position = f"第 {self.page_index + 1} 页" if self.rows else "—"
            can_next = self.has_next
        self.result_title.configure(text=found)
        self.page_text.configure(text="读取中…" if self.loading else position)
        can_page = bool(self.rows) and not (self.loading or self.stale)
        self.previous.configure(state="normal" if can_page and self.page_index else "disabled")
        self.next.configure(state="normal" if can_page and can_next else "disabled")
        self.reset_button.configure(state="normal" if self.catalog is not None else "disabled")

    def fill_tree(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        blind = self.practice.get()
        self.tree.configure(displaycolumns=("subject", "id") if blind else ("subject", "label", "id"))
        for i, row in enumerate(self.rows):
            # Encode visible distinctions with words as well as color.
            label = {"malicious": "恶意", "benign": "正常"}.get(row.label, one_line(row.label) or "—")
            tags = ("stripe",) if i % 2 else ()
            self.tree.insert("", "end", iid=str(i),
                             values=(one_line(row.subject) or "（无主题）", label if not blind else "",
                                     one_line(row.record_id)), tags=tags)
        if self.rows:
            iid = selected if selected and self.tree.exists(selected) else "0"
            self.tree.selection_set(iid)
            self.tree.focus(iid)
            self.tree.see(iid)
        self.select_record()

    def show_rows(self, rows, records, index, *, selected=None):
        self.rows, self.records, self.page_index = rows, records, index
        self.fill_tree(selected)
        self.update_navigation()

    def select_record(self, _event=None):
        selected = self.tree.selection()
        idx = int(selected[0]) if selected else -1
        record = self.records[idx] if 0 <= idx < len(self.records) else None
        if record is not self.record:
            self.record = record
            self.summary = self.rows[idx] if record is not None else None
            self.revealed = False
            self.rendered.clear()
        self.update_record_tools()
        self.render_detail()

    @property
    def redacted(self):
        return self.practice.get() and not self.revealed

    def update_record_tools(self):
        record, row = self.record, self.summary
        blind, has_record = self.redacted, record is not None
        if (blind or not has_record) and self.current_view() in ("assessment", "sources", "json"):
            self.tabs.select(self.frames["email"])
        for key in ("assessment", "sources", "json"):
            frame = self.frames[key]
            if blind:
                self.tabs.hide(frame)
            else:
                self.tabs.add(frame)

        self.practice_button.pack_forget()
        self.pair_button.pack_forget()
        if has_record and blind:
            self.practice_button.pack(side="right", before=self.action_menu_button, padx=(0, 8))
        elif row is not None and row.pair_id and self.catalog is not None:
            self.pair_button.configure(state="normal" if self.catalog.paired_with(row) else "disabled")
            self.pair_button.pack(side="right", before=self.action_menu_button, padx=(0, 8))

        self.action_menu.delete(0, "end")
        self.action_menu_button.configure(state="normal" if has_record else "disabled")
        if has_record:
            self.action_menu.add_command(label="复制分类输入 JSON", command=lambda: self.copy_json(True))
            self.action_menu.add_command(label="导出分类输入 JSON…", command=lambda: self.export_json(True))
            if not blind:
                self.action_menu.add_separator()
                self.action_menu.add_command(label="复制完整记录 JSON", command=lambda: self.copy_json(False))
                self.action_menu.add_command(label="导出完整记录 JSON…", command=lambda: self.export_json(False))
                self.action_menu.add_separator()
                self.action_menu.add_command(label="关闭原文高亮" if self.evidence_on else "高亮原文证据",
                                             command=self.toggle_evidence)
        self.label_badge.pack_forget()
        if row is None:
            self.subject.configure(text=self.empty_text)
            self.metadata.configure(text="")
            self.kicker.configure(text="样本详情")
            return

        title = one_line(row.subject) or "（无主题）"
        self.subject.configure(text=title[:220] + "…" if len(title) > 220 else title)
        parts = [one_line(row.record_id)]
        parts.extend(display_facet(key, getattr(row, key)) for key in ("domain", "difficulty", "language")
                     if getattr(row, key))
        self.metadata.configure(text="  ·  ".join(parts))
        self.kicker.configure(text="盲测中  /  答案已隐藏" if blind else ("盲测  /  已揭晓" if self.practice.get() else "样本详情"))
        if not blind:
            bg, fg = {"malicious": (DANGER_BG, WARNING), "benign": (ACCENT_LIGHT, ACCENT)}.get(row.label, (TINT, MUTED))
            self.label_badge.configure(text=display_facet("label", row.label), bg=bg, fg=fg)
            self.label_badge.pack(side="left", before=self.metadata, padx=(0, 9))

    def current_view(self):
        path = self.tabs.select()
        return next((key for key, frame in self.frames.items() if str(frame) == path), None)

    def toggle_evidence(self):
        self.evidence_on = not self.evidence_on
        self.update_record_tools()
        self.render_detail()

    def toggle_practice(self):
        blind = not self.practice.get()
        selected_ordinal = self.summary.ordinal if self.summary is not None else None
        rerun = bool(self.query.get().strip() or (blind and "label" in self.filter_values()))
        self.practice.set(blind)
        self.revealed = False
        self.rendered.clear()
        self.mode_button.configure(text="退出盲测" if blind else "进入盲测")
        if blind:
            self.filters["label"].current(0)
            self.filters["label"].grid_remove()
            self.filter_labels["label"].grid_remove()
            self.tabs.select(self.frames["email"])
        else:
            self.filters["label"].grid()
            self.filter_labels["label"].grid()
        selected = self.tree.selection()
        self.fill_tree(selected[0] if selected else None)
        if rerun:
            self.search_now(keep_ordinal=selected_ordinal)

    def reveal_answer(self):
        if self.record is None or not self.redacted:
            return
        self.revealed = True
        self.update_record_tools()
        self.tabs.select(self.frames["assessment"])
        self.render_detail()

    @staticmethod
    def replace_text(widget, sections):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        custom_tags = [tag for tag in widget.tag_names() if tag.startswith(("anchor:", "link:"))]
        if custom_tags:
            widget.tag_delete(*custom_tags)
        widget.configure(cursor="xterm")
        # Send one Tcl command instead of one per span on long provenance pages.
        contents = []
        for value, tags in sections:
            contents.extend((string(value), (tags,) if isinstance(tags, str) else tags))
        if contents:
            widget.insert("end", *contents)
        widget.configure(state="disabled")
        widget.yview_moveto(0)
        widget.xview_moveto(0)

    def render_detail(self, _event=None):
        view = self.current_view()
        if not view or (self.redacted and view not in ("email", "history")):
            return
        widget = self.views[view]
        token = (self.redacted, self.evidence_on, self.empty_text if self.record is None else "")
        if self.rendered.get(view) == token:
            return
        self.rendered[view] = token
        links = {}
        if self.record is not None:
            sections = detail_sections(self.record, view, highlight=not self.redacted, links=links)
        else:
            description = {
                "没有匹配样本": "试试更短的关键词，或使用左侧「重置检索」清除筛选。",
                "语料为空": "此 JSON 文件没有可浏览的样本。",
                "无法读取语料": "请检查底部信息，或打开另一份 JSON 语料文件。",
            }.get(self.empty_text, "")
            sections = [(description, "meta")]
        lang = self.summary.language if self.summary is not None else ""
        widget.configure(wrap="none" if view == "json" else ("char" if lang.startswith("zh") else "word"))
        widget.tag_configure("evidence", background="#fcf0c9" if self.evidence_on else "")
        self.replace_text(widget, sections)
        self.links[view] = links

    def reader_location(self, event, view):
        links = self.links.get(view, {})
        if links and not self.redacted:
            tags = event.widget.tag_names(f"@{event.x},{event.y}")
            return next((links[tag] for tag in tags if tag in links), None)
        return None

    def reader_motion(self, event, view):
        cursor = "hand2" if self.reader_location(event, view) else "xterm"
        if event.widget.cget("cursor") != cursor:
            event.widget.configure(cursor=cursor)

    def reader_click(self, event, view):
        target = self.reader_location(event, view)
        if target:
            return self.jump_to(*target)

    def jump_to(self, view, anchor):
        if self.redacted:
            return
        self.tabs.select(self.frames[view])
        self.render_detail()
        widget = self.views[view]
        for reader in self.views.values():
            reader.tag_remove("located", "1.0", "end")
        span = widget.tag_nextrange(anchor, "1.0")
        if span:
            widget.tag_add("located", *span)
            widget.see(span[0])
            widget.focus_set()
        return "break"

    def copy_json(self, input_only):
        if self.record is None or (self.redacted and not input_only):
            return
        payload = record_json(self.record, input_only=input_only)
        self.root.clipboard_clear()
        self.root.clipboard_append(payload.encode("utf-8", errors="backslashreplace").decode("utf-8"))
        self.set_status("已复制分类输入 JSON" if input_only else "已复制完整记录 JSON")

    def export_json(self, input_only):
        if self.record is None or (self.redacted and not input_only):
            return
        payload = record_json(self.record, input_only=input_only)
        record_id = one_line(self.summary.record_id)
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in record_id)[:80]
        path = filedialog.asksaveasfilename(
            parent=self.root, title="导出样本 JSON", defaultextension=".json",
            initialfile=f"{safe_id or 'record'}{'-input' if input_only else ''}.json",
            filetypes=(("JSON", "*.json"),),
        )
        if not path:
            return
        destination = Path(path)
        try:
            if destination.resolve() == self.pages.path.resolve() or (
                destination.exists() and destination.samefile(self.pages.path)
            ):
                raise ValueError("请选用不同的文件名，当前语料以只读方式打开。")
            destination.write_text(payload + "\n", encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError) as error:
            messagebox.showerror("无法导出", str(error), parent=self.root)
        else:
            self.set_status(f"已导出 {one_line(destination.name)}")

    def compare_record(self):
        if self.redacted or self.catalog is None or self.summary is None:
            return
        catalog, record, row = self.catalog, self.record, self.summary
        paired = catalog.paired_with(row)
        if paired:
            self.run_job(lambda: catalog.read_records(paired),
                         lambda records: self.show_comparison(record, records) if record is self.record and not self.redacted else None,
                         self.read_error)

    def show_comparison(self, record, counterparts):
        popup = tk.Toplevel(self.root)
        popup.title("VIGILYX · 配对对照")
        popup.geometry("900x690")
        popup.minsize(530, 390)
        popup.configure(bg=PAPER)
        # Keep the revealed pair confined to this window, then return focus to
        # the selected record when it closes.
        popup.transient(self.root)
        popup.grab_set()
        header = ttk.Frame(popup, padding=(22, 13))
        header.pack(fill="x")
        self.text_label(header, "分类输入差异", face=(self.ui[0], 19, "bold")).pack(side="left")
        ttk.Button(header, text="关闭", command=popup.destroy).pack(side="right")
        self.text_label(header, "− 当前样本    + 对照样本", fg=MUTED, face=self.small).pack(side="right", padx=12)
        self.line(popup)
        pane, reader = self.make_reader(popup)
        pane.pack(fill="both", expand=True)
        reader.configure(wrap="char")
        sections = []
        for counter in counterparts:
            if sections:
                sections.append(("\n\n", "body"))
            sections.extend(comparison_sections(record, counter))
        self.replace_text(reader, sections)
        popup.bind("<Escape>", lambda _e: popup.destroy())
        reader.focus_set()


def use_supported_tk():
    if sys.platform != "darwin" or tk.TkVersion >= 8.6:
        return True

    for version in ("3.15", "3.14", "3.13", "3.12", "3.11", "3.10"):
        name = f"python{version}"
        candidates = (shutil.which(name), Path.home() / ".local" / "bin" / name)
        for candidate in candidates:
            if not candidate or not os.access(candidate, os.X_OK):
                continue
            try:
                probe = subprocess.run(
                    [candidate, "-c", "import tkinter; raise SystemExit(tkinter.TkVersion < 8.6)"],
                    capture_output=True, timeout=2,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if probe.returncode == 0:
                os.execv(candidate, [str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]])

    print("当前 Python 使用 Tk 8.5。请使用带 Tk 8.6 或更新版本的 Python 运行查看器。", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description="浏览、检索和审阅 VIGILYX 邮件语料。")
    parser.add_argument("corpus", nargs="?", type=Path, default=DEFAULT_CORPUS, help="语料 JSON 路径")
    parser.add_argument("--page-size", type=int, default=50, metavar="N", help="每页条数（1–200，默认 50）")
    args = parser.parse_args()
    if not 1 <= args.page_size <= 200:
        parser.error("--page-size 必须在 1–200 之间")

    if not use_supported_tk():
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"无法打开图形窗口：{error}", file=sys.stderr)
        return 1
    CorpusViewer(root, CorpusPages(args.corpus, args.page_size))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
