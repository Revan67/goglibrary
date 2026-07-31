# -*- coding: utf-8 -*-
"""Desktop GUI shell for gogrepoc. Imports gogrepoc_backend as a library --
a GUI-only fork of gogrepoc.py that may add hooks/callbacks as needed.
gogrepoc.py itself is never modified and stays the clean, no-GUI, CLI-only
script; gogrepoc_backend.py is free to diverge for the GUI's sake.
"""
import datetime
import json
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog

import customtkinter as ctk

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
# gogrepoc_backend reads/writes gog-token.dat, gog-manifest.*, gogrepo.log etc. as bare
# relative filenames (same as the CLI, which assumes you've cd'd into this directory).
# Anchor the process CWD here so the GUI finds an existing token/manifest regardless of
# how it was launched (shortcut, different terminal cwd, etc.).
os.chdir(_SCRIPT_DIR)
import gogrepoc_backend as gog

# ---------------------------------------------------------------------------
# design tokens (light, dark) -- mirrors the approved HTML mockup
# ---------------------------------------------------------------------------
BG = ("#f5f3fa", "#15131a")
SURFACE = ("#ffffff", "#1c1a24")
SURFACE_2 = ("#ede9f7", "#242030")
SURFACE_3 = ("#e3ddf3", "#2c273a")
BORDER = ("#ddd6ee", "#322c40")
TEXT = ("#211f2b", "#eae7f2")
TEXT_DIM = ("#6c6680", "#9d97b3")
TEXT_FAINT = ("#948da8", "#6f6884")
ACCENT = ("#6f5cf0", "#9384f8")
ACCENT_INK = ("#ffffff", "#14121c")
ACCENT_SOFT = ("#efecfd", "#2a2540")
GOOD = ("#2e9463", "#56c390")
GOOD_SOFT = ("#e3f3ea", "#1c3128")
WARN = ("#b8791f", "#e6b356")
WARN_SOFT = ("#faf1e0", "#3a3120")
BAD = ("#c94a44", "#e97b76")
BAD_SOFT = ("#fbe9e8", "#3a2422")
MONO_BG = ("#edeaf7", "#100e16")

SETTINGS_FILENAME = "gogrepo_gui_settings.json"


def human_size(n):
    if not n:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0 or unit == "TB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def format_relative_time(ts):
    dt = datetime.datetime.fromtimestamp(ts)
    now = datetime.datetime.now()
    time_part = dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == now.date():
        return "Today, %s" % time_part
    if dt.date() == (now - datetime.timedelta(days=1)).date():
        return "Yesterday, %s" % time_part
    return dt.strftime("%b %d, %Y")


def pick_font(*preferred):
    available = set(tkfont.families())
    for name in preferred:
        if name in available:
            return name
    return preferred[-1]


UI_FONT_FAMILY = None   # resolved once a Tk root exists, see App.__init__
MONO_FONT_FAMILY = None


def F(size=13, weight="normal"):
    return ctk.CTkFont(family=UI_FONT_FAMILY, size=round(size), weight=weight)


def MONO(size=12, weight="normal"):
    return ctk.CTkFont(family=MONO_FONT_FAMILY, size=round(size), weight=weight)


# ---------------------------------------------------------------------------
# logging -> queue bridge (gogrepoc's info/warn/debug/error are bound methods
# of logging.getLogger('ws'); we attach our own handler, we never touch
# gogrepoc.py or its existing console/file handlers)
# ---------------------------------------------------------------------------
class QueueLogHandler(logging.Handler):
    def __init__(self, out_queue):
        super().__init__()
        self._q = out_queue

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self._q.put(("log", record.levelno, msg))


# ---------------------------------------------------------------------------
# small reusable widgets
# ---------------------------------------------------------------------------
class Group(ctk.CTkFrame):
    """Fieldset-style bordered group with an uppercase legend."""

    def __init__(self, master, title, **kw):
        super().__init__(master, fg_color=SURFACE, border_width=1, border_color=BORDER,
                          corner_radius=8, **kw)
        self.grid_columnconfigure((0, 1), weight=1)
        legend = ctk.CTkLabel(self, text=title.upper(), font=F(10.5, "bold"),
                               text_color=TEXT_DIM)
        legend.grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 6))
        self._row = 1

    def add(self, widget, span=1):
        widget.grid(row=self._row, column=0, columnspan=(2 if span == 2 else 1),
                    sticky="ew", padx=14, pady=6)
        self._row += 1
        return widget

    def add_pair(self, left, right):
        left.grid(row=self._row, column=0, sticky="ew", padx=(14, 7), pady=6)
        right.grid(row=self._row, column=1, sticky="ew", padx=(7, 14), pady=6)
        self._row += 1

    def finish(self):
        ctk.CTkLabel(self, text="", height=4).grid(row=self._row, column=0)


class CheckRow(ctk.CTkFrame):
    def __init__(self, master, title, desc=None, default=False):
        super().__init__(master, fg_color="transparent")
        self.var = tk.BooleanVar(value=default)
        cb = ctk.CTkCheckBox(self, text=title, variable=self.var, font=F(12.5),
                              text_color=TEXT, checkbox_width=16, checkbox_height=16,
                              fg_color=ACCENT, hover_color=ACCENT)
        cb.pack(anchor="w")
        if desc:
            ctk.CTkLabel(self, text=desc, font=F(11), text_color=TEXT_FAINT,
                         justify="left").pack(anchor="w", padx=(26, 0))

    def get(self):
        return bool(self.var.get())


class RadioGroup(ctk.CTkFrame):
    def __init__(self, master, options, default=0):
        """options: list of (value, title, desc)"""
        super().__init__(master, fg_color="transparent")
        self.var = tk.StringVar(value=options[default][0])
        for value, title, desc in options:
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(anchor="w", fill="x", pady=2)
            rb = ctk.CTkRadioButton(row, text=title, variable=self.var, value=value,
                                     font=F(12.5), text_color=TEXT, fg_color=ACCENT,
                                     hover_color=ACCENT)
            rb.pack(anchor="w")
            if desc:
                ctk.CTkLabel(row, text=desc, font=F(11), text_color=TEXT_FAINT
                             ).pack(anchor="w", padx=(26, 0))

    def get(self):
        return self.var.get()


class EnumChipSelect(ctk.CTkFrame):
    """Fixed, enumerable set of values (OS or language) shown as removable chip
    pills. Click anywhere on the box (or an existing chip) to open a checklist
    popup and pick several at once -- constrained to the known set, unlike
    free-text input."""

    def __init__(self, master, items, default_selected=None, on_change=None):
        """items: list of (key, label). on_change(list_of_selected_keys), if given,
        fires after every add/remove -- used to persist the selection."""
        # explicit height=1: CTkFrame defaults to 200x200 when it has no packed
        # children yet to shrink-wrap around, which otherwise leaves a large
        # blank box before anything is selected/rendered.
        super().__init__(master, fg_color=SURFACE_2, border_width=1, border_color=BORDER,
                          corner_radius=6, height=1, cursor="hand2")
        self.items = items
        self.labels = dict(items)
        self.selected = [k for k, _ in items if k in set(default_selected or [])]
        self.on_change = on_change
        self.wrap = ctk.CTkFrame(self, fg_color="transparent", height=1, cursor="hand2")
        self.wrap.pack(fill="x", padx=6, pady=6)
        self._chip_widgets = []
        self._render()
        self.bind("<Button-1>", lambda _e: self._open_picker())
        self.wrap.bind("<Button-1>", lambda _e: self._open_picker())

    def _notify(self):
        if self.on_change is not None:
            self.on_change(list(self.selected))

    def _remove_key(self, key):
        self.selected.remove(key)
        self._render()
        self._notify()

    def _toggle_from_picker(self, key, var):
        if var.get():
            if key not in self.selected:
                self.selected.append(key)
        else:
            if key in self.selected:
                self.selected.remove(key)
        self._render()
        self._notify()

    def _open_picker(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Select")
        popup.geometry("280x380")
        popup.transient(self.winfo_toplevel())
        popup.grab_set()
        popup.configure(fg_color=BG)

        header = ctk.CTkFrame(popup, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(header, text="Select", font=F(13, "bold"), text_color=TEXT).pack(side="left")
        ctk.CTkButton(header, text="Done", width=64, font=F(11.5, "bold"), fg_color=ACCENT,
                      hover_color=ACCENT, text_color=ACCENT_INK, command=popup.destroy
                      ).pack(side="right")

        list_frame = ctk.CTkScrollableFrame(popup, fg_color="transparent")
        list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 14))
        try:
            list_frame._scrollbar.configure(fg_color=BG, button_color=BG, button_hover_color=BG)
        except Exception:
            pass

        for key, label in self.items:
            v = tk.BooleanVar(value=(key in self.selected))
            ctk.CTkCheckBox(list_frame, text=label, variable=v, font=F(12), text_color=TEXT,
                            checkbox_width=15, checkbox_height=15, fg_color=ACCENT,
                            hover_color=ACCENT,
                            command=lambda k=key, v=v: self._toggle_from_picker(k, v)
                            ).pack(anchor="w", pady=4, padx=4)

    def _render(self):
        for w in self._chip_widgets:
            w.destroy()
        self._chip_widgets = []
        if not self.selected:
            hint = ctk.CTkLabel(self.wrap, text="click to select…", font=F(11.5),
                                 text_color=TEXT_FAINT)
            hint.pack(side="left", padx=(4, 0), pady=3)
            hint.bind("<Button-1>", lambda _e: self._open_picker())
            self._chip_widgets.append(hint)
            return
        for key in self.selected:
            chip = ctk.CTkFrame(self.wrap, fg_color=ACCENT_SOFT, corner_radius=999)
            chip.pack(side="left", padx=(0, 6), pady=2)
            lbl = ctk.CTkLabel(chip, text=self.labels.get(key, key), font=F(11.5, "bold"),
                                text_color=TEXT, cursor="hand2")
            lbl.pack(side="left", padx=(10, 4), pady=3)
            lbl.bind("<Button-1>", lambda _e: self._open_picker())
            btn = ctk.CTkButton(chip, text="×", width=16, height=16, corner_radius=8,
                                 fg_color="transparent", hover_color=SURFACE_3,
                                 text_color=TEXT_FAINT, font=F(11),
                                 command=lambda k=key: self._remove_key(k))
            btn.pack(side="left", padx=(0, 6))
            self._chip_widgets.append(chip)
        if len(self.selected) < len(self.items):
            more = ctk.CTkLabel(self.wrap, text="+ %d more…" % (len(self.items) - len(self.selected)),
                                 font=F(11), text_color=TEXT_FAINT)
            more.pack(side="left", padx=(2, 0), pady=3)
            more.bind("<Button-1>", lambda _e: self._open_picker())
            self._chip_widgets.append(more)

    def get(self):
        return list(self.selected)


class ChipInput(ctk.CTkFrame):
    """Free-text tag input, reserved for ids / skipids (title-or-id, not enumerable)."""

    def __init__(self, master, placeholder="+ add title or id"):
        super().__init__(master, fg_color=SURFACE_2, border_width=1, border_color=BORDER,
                          corner_radius=6, height=1)
        self.values = []
        # height=1: see EnumChipSelect's note above -- an empty CTkFrame otherwise
        # defaults to 200px tall with nothing to shrink-wrap around.
        self.wrap = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self.wrap.pack(fill="x", padx=6, pady=6)
        self.entry = ctk.CTkEntry(self, placeholder_text=placeholder, border_width=0,
                                   fg_color="transparent", font=F(12))
        self.entry.pack(fill="x", padx=6, pady=(0, 6))
        self.entry.bind("<Return>", self._add)
        self._chip_widgets = []

    def _add(self, _evt=None):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self.values.append(text)
        self._render()

    def _remove(self, text):
        self.values.remove(text)
        self._render()

    def _render(self):
        for w in self._chip_widgets:
            w.destroy()
        self._chip_widgets = []
        for text in self.values:
            chip = ctk.CTkFrame(self.wrap, fg_color=ACCENT_SOFT, corner_radius=999)
            chip.pack(side="left", padx=(0, 6), pady=2)
            ctk.CTkLabel(chip, text=text, font=F(11.5, "bold"), text_color=TEXT
                         ).pack(side="left", padx=(10, 4), pady=3)
            btn = ctk.CTkButton(chip, text="×", width=16, height=16, corner_radius=8,
                                 fg_color="transparent", hover_color=SURFACE_3,
                                 text_color=TEXT_FAINT, font=F(11),
                                 command=lambda t=text: self._remove(t))
            btn.pack(side="left", padx=(0, 6))
            self._chip_widgets.append(chip)

    def get(self):
        # Flush whatever's still typed but not committed (Enter never pressed) --
        # otherwise clicking Run with an uncommitted value silently drops it,
        # the ids filter sees an empty list, and the whole manifest gets processed.
        self._add()
        return list(self.values)


class Advanced(ctk.CTkFrame):
    def __init__(self, master, count):
        super().__init__(master, fg_color="transparent")
        self._open = False
        self.toggle_btn = ctk.CTkButton(
            self, text="▸ Advanced (%d)" % count, anchor="w", fg_color="transparent",
            hover_color=SURFACE_2, text_color=TEXT_DIM, font=F(12, "bold"),
            command=self._flip)
        self.toggle_btn.pack(anchor="w", fill="x")
        self.body = ctk.CTkFrame(self, fg_color="transparent")

    def _flip(self):
        self._open = not self._open
        arrow = "▾" if self._open else "▸"
        text = self.toggle_btn.cget("text").split(" ", 1)[1]
        self.toggle_btn.configure(text="%s %s" % (arrow, text))
        if self._open:
            self.body.pack(fill="x", pady=(8, 0))
        else:
            self.body.pack_forget()


# ---------------------------------------------------------------------------
# main application
# ---------------------------------------------------------------------------
NAV_ITEMS = [
    ("update", "Update", "Update locally saved game manifest from GOG server."),
    ("download", "Download", "Download all your GOG games and extra files."),
    ("verify", "Verify", "Scan your downloaded GOG files and verify their integrity."),
]
STUB_ITEMS = ["Import", "Backup", "Clean", "Trash"]
PANEL_INFO = dict((k, (l, d)) for k, l, d in NAV_ITEMS)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        global UI_FONT_FAMILY, MONO_FONT_FAMILY
        UI_FONT_FAMILY = pick_font("Segoe UI Variable Display", "Segoe UI", "Arial")
        MONO_FONT_FAMILY = pick_font("Cascadia Mono", "Cascadia Code", "Consolas")

        self.title("gogrepo")
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(fg_color=BG)
        ctk.set_appearance_mode("system")
        try:
            self.state("zoomed")
        except tk.TclError:
            pass

        self.job_running = False
        self.wakelock = gog.Wakelock()
        self.log_queue = queue.Queue()
        self.issues = []
        self.download_queue = {}  # key -> {"name", "size", "phase"}, insertion order
        self._install_log_bridge()

        self.settings = self._load_settings()
        self.manifest_items = []
        self._load_manifest_snapshot()

        self._build_shell()
        self.show_panel("download")
        self.after(120, self._poll_queue)

    # -- logging -------------------------------------------------------
    def _install_log_bridge(self):
        handler = QueueLogHandler(self.log_queue)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
        gog.rootLogger.addHandler(handler)
        self.log_handler = handler

    def _poll_queue(self):
        try:
            while True:
                kind, *payload = self.log_queue.get_nowait()
                if kind == "log":
                    level, msg = payload
                    self._append_log(msg)
                    if level >= logging.WARNING:
                        self._append_issue(level, msg)
                elif kind == "queue":
                    phase, key, name, size = payload
                    self.download_queue[key] = {"name": name, "size": size, "phase": phase}
                    self._render_download_queue()
                elif kind == "done":
                    (ok, err) = payload
                    self._on_job_done(ok, err)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _append_log(self, msg):
        self.log_body.configure(state="normal")
        self.log_body.insert("end", msg + "\n")
        self.log_body.see("end")
        self.log_body.configure(state="disabled")

    def _append_issue(self, level, msg):
        self.issues.append((level, msg))
        self._render_issues()

    def _on_download_event(self, phase, key, name, size):
        """Called from any of the download worker threads -- must do nothing but
        push onto the thread-safe queue, same discipline as QueueLogHandler."""
        self.log_queue.put(("queue", phase, key, name, size))

    def _render_issues(self):
        frame = getattr(self, "issues_list_frame", None)
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        if not self.issues:
            ctk.CTkLabel(frame, text=getattr(self, "issues_empty_text", "No issues yet."),
                         font=F(11.5), text_color=TEXT_FAINT, wraplength=260, justify="left"
                         ).pack(anchor="w", padx=8, pady=8)
            return
        for lvl, msg in self.issues[-200:]:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", pady=3)
            is_error = lvl >= logging.ERROR
            pill = ctk.CTkLabel(row, text=("error" if is_error else "warning"), font=F(10, "bold"),
                                 fg_color=(BAD_SOFT if is_error else WARN_SOFT),
                                 text_color=(BAD if is_error else WARN), corner_radius=999,
                                 width=54, height=18)
            pill.pack(side="left", padx=(0, 8), anchor="n")
            ctk.CTkLabel(row, text=msg, font=F(11.5), text_color=TEXT, anchor="w",
                         wraplength=260, justify="left").pack(side="left", fill="x", expand=True)

    # -- manifest snapshot (read-only) ----------------------------------
    def _settings_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), SETTINGS_FILENAME)

    def _load_settings(self):
        defaults = {
            "game_dir": os.path.abspath(gog.GAME_STORAGE_DIR),
            "update_os": list(gog.DEFAULT_OS_LIST),
            "update_lang": list(gog.DEFAULT_LANG_LIST),
            "download_os": [],
            "download_lang": [],
        }
        try:
            with open(self._settings_path(), "r", encoding="utf-8") as fh:
                defaults.update(json.load(fh))
        except (IOError, OSError, ValueError):
            pass
        return defaults

    def _save_settings(self):
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as fh:
                json.dump(self.settings, fh, indent=1)
        except OSError:
            pass

    def _persist_chip_setting(self, key, values):
        self.settings[key] = values
        self._save_settings()

    def _load_manifest_snapshot(self):
        # gog.load_manifest() -- not a raw JSON read -- so a legacy-only manifest
        # (no gog-manifest.json yet) is still picked up via its normal one-time
        # migration path, same as running any CLI command would do.
        try:
            self.manifest_items = gog.load_manifest()
        except Exception:
            self.manifest_items = []

    def _snapshot_stats(self, key):
        n = len(self.manifest_items)
        games_stat = ("Games in manifest", "{:,}".format(n))
        if key == "download":
            pending = sum(1 for r in self.download_queue.values() if r["phase"] in ("queued", "downloading"))
            total = sum(r["size"] or 0 for r in self.download_queue.values()
                        if r["phase"] in ("queued", "downloading"))
            pending_val = "{:,}".format(pending) if self.download_queue else "—"
            size_val = human_size(total) if self.download_queue else "—"
            return [games_stat, ("Pending downloads", pending_val), ("Estimated size", size_val)]
        if key == "verify":
            verified = 0
            total_files = 0
            for item in self.manifest_items:
                for k in ("downloads", "galaxyDownloads", "sharedDownloads", "extras"):
                    for d in item.get(k, []) or []:
                        total_files += 1
                        if d.get("prev_verified"):
                            verified += 1
            verified_val = "{:,} / {:,}".format(verified, total_files) if total_files else "—"
            return [games_stat, ("Verified clean", verified_val)]

        # update: one representative standalone file per game, filtered to the
        # currently configured OS/language, so it doesn't repeat the old bug of
        # summing every platform/language variant (which inflated it wildly).
        os_filter = set(self.settings["update_os"]) or set(gog.VALID_OS_TYPES)
        lang_filter = set(gog.LANG_TABLE[k] for k in
                          (self.settings["update_lang"] or gog.VALID_LANG_TYPES))
        total_bytes = 0
        for item in self.manifest_items:
            for d in item.get("downloads", []) or []:
                if d.get("os_type") in os_filter and d.get("lang") in lang_filter:
                    size = d.get("size")
                    if isinstance(size, (int, float)):
                        total_bytes += size
                    break
        size_val = human_size(total_bytes) if total_bytes else "—"
        manifest_path = gog.MANIFEST_JSON_FILENAME
        try:
            last_update_val = format_relative_time(os.path.getmtime(manifest_path))
        except OSError:
            last_update_val = "—"
        try:
            manifest_size_val = human_size(os.path.getsize(manifest_path))
        except OSError:
            manifest_size_val = "—"
        return [
            ("Game count", "{:,}".format(n)),
            ("Library size", size_val),
            ("Last update", last_update_val),
            ("Manifest size", manifest_size_val),
        ]

    # -- shell -----------------------------------------------------------
    def _build_shell(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=214, fg_color=SURFACE, border_width=0,
                                corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="SYNC", font=F(10.5, "bold"), text_color=TEXT_FAINT
                     ).pack(anchor="w", padx=16, pady=(16, 4))
        self.nav_buttons = {}
        for key, label, _desc in NAV_ITEMS:
            self.nav_buttons[key] = self._make_nav_button(sidebar, key, label)

        ctk.CTkLabel(sidebar, text="MAINTENANCE", font=F(10.5, "bold"), text_color=TEXT_FAINT
                     ).pack(anchor="w", padx=16, pady=(16, 4))
        for label in STUB_ITEMS:
            b = ctk.CTkButton(sidebar, text=label, anchor="w", fg_color="transparent",
                               hover_color=SURFACE_2, text_color=TEXT_FAINT, font=F(12.5),
                               state="disabled")
            b.pack(fill="x", padx=8, pady=1)

        ctk.CTkFrame(sidebar, fg_color="transparent").pack(fill="both", expand=True)
        ctk.CTkFrame(sidebar, height=1, fg_color=BORDER).pack(fill="x", padx=8, pady=(0, 6))
        settings_button = ctk.CTkButton(
            sidebar, text="Settings", anchor="w", font=F(12.5, "bold"), fg_color="transparent",
            hover_color=SURFACE_2, text_color=TEXT_DIM, command=self._open_settings_dialog)
        settings_button.pack(fill="x", padx=8, pady=1)

        main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)

        self.topbar = ctk.CTkFrame(main, fg_color=BG, corner_radius=0, height=64)
        self.topbar.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 8))

        self.snapshot_row = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        self.snapshot_row.grid(row=1, column=0, sticky="ew", padx=24)

        self.content_row = ctk.CTkFrame(main, fg_color=BG, corner_radius=0)
        self.content_row.grid(row=2, column=0, sticky="nsew", padx=24, pady=14)
        self.content_row.grid_columnconfigure(0, weight=3)
        self.content_row.grid_columnconfigure(1, weight=2)
        self.content_row.grid_rowconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        self._build_log_panel(main)

        self.panels = {}
        self.panel_builders = {
            "update": self._build_update_panel,
            "download": self._build_download_panel,
            "verify": self._build_verify_panel,
        }

    def _make_nav_button(self, sidebar, key, label):
        b = ctk.CTkButton(sidebar, text=label, anchor="w", font=F(12.5, "bold"),
                           fg_color="transparent", hover_color=SURFACE_2, text_color=TEXT_DIM,
                           command=lambda: self.show_panel(key))
        b.pack(fill="x", padx=8, pady=1)
        return b

    def _set_active_nav(self, key):
        for k, b in self.nav_buttons.items():
            active = (k == key)
            b.configure(fg_color=ACCENT_SOFT if active else "transparent",
                        text_color=TEXT if active else TEXT_DIM)

    def show_panel(self, key):
        self.current_panel_key = key
        self._set_active_nav(key)
        for child in self.topbar.winfo_children():
            child.destroy()
        for child in self.snapshot_row.winfo_children():
            child.destroy()
        for child in self.content_row.winfo_children():
            child.destroy()

        label, desc = PANEL_INFO[key]

        head = ctk.CTkFrame(self.topbar, fg_color="transparent")
        head.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(head, text=label, font=F(20, "bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(head, text=desc, font=F(12.5), text_color=TEXT_DIM).pack(anchor="w")

        actions = ctk.CTkFrame(self.topbar, fg_color="transparent")
        actions.pack(side="right")
        button_text = "▶  Sign in" if key == "login" else "▶  Run %s" % label.lower()
        self.run_button = ctk.CTkButton(
            actions, text=button_text, font=F(12.5, "bold"),
            fg_color=ACCENT, hover_color=ACCENT, text_color=ACCENT_INK,
            command=lambda: self._run_command(key))
        self.run_button.pack(side="right")

        self.dry_run_var = tk.BooleanVar(value=False)
        self.debug_var = tk.BooleanVar(value=False)
        if key == "download":
            ctk.CTkCheckBox(actions, text="Dry run", variable=self.dry_run_var, font=F(12),
                             text_color=TEXT_DIM, checkbox_width=15, checkbox_height=15,
                             fg_color=ACCENT, hover_color=ACCENT).pack(side="right", padx=(0, 16))
        elif key == "update":
            ctk.CTkCheckBox(actions, text="Debug logging", variable=self.debug_var, font=F(12),
                             text_color=TEXT_DIM, checkbox_width=15, checkbox_height=15,
                             fg_color=ACCENT, hover_color=ACCENT).pack(side="right", padx=(0, 16))

        self._refresh_snapshot_row()
        self.panel_builders[key](self.content_row)

    # -- command option panels ------------------------------------------
    def _options_panel(self, parent):
        outer = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        try:
            outer._scrollbar.configure(fg_color=BG, button_color=BG, button_hover_color=BG)
        except Exception:
            pass
        return outer

    def _issues_panel(self, parent, empty_text):
        """Right-hand status panel: reports warnings/errors from the run, not a
        static dump of the whole library -- this isn't a game-library browser."""
        p = ctk.CTkFrame(parent, fg_color=SURFACE, border_width=1, border_color=BORDER,
                          corner_radius=8)
        p.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(p, text="Issues", font=F(12, "bold"), text_color=TEXT
                     ).pack(anchor="w", padx=16, pady=(14, 8))
        self.issues_list_frame = ctk.CTkFrame(p, fg_color="transparent")
        self.issues_list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self.issues_empty_text = empty_text
        self._render_issues()
        return p

    def _queue_panel(self, parent):
        """Download-specific: real queued/working/downloading/done status per game,
        built from cmd_download's own scan + progress hooks -- not a static library
        listing. Falls back to an empty-state message before a run has happened."""
        p = ctk.CTkFrame(parent, fg_color=SURFACE, border_width=1, border_color=BORDER,
                          corner_radius=8)
        p.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        head = ctk.CTkFrame(p, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 8))
        ctk.CTkLabel(head, text="Download queue", font=F(12, "bold"), text_color=TEXT
                     ).pack(side="left")
        self.queue_count_label = ctk.CTkLabel(head, text="", font=F(11.5), text_color=TEXT_DIM)
        self.queue_count_label.pack(side="right")
        self.queue_list_frame = ctk.CTkFrame(p, fg_color="transparent")
        self.queue_list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self._render_download_queue()
        return p

    _QUEUE_PILLS = {
        "queued": ("queued", WARN_SOFT, WARN),
        "working": ("resuming", SURFACE_3, TEXT_DIM),
        "downloading": ("downloading", GOOD_SOFT, GOOD),
        "done": ("done", GOOD_SOFT, GOOD),
        "incomplete": ("incomplete", BAD_SOFT, BAD),
    }

    def _render_download_queue(self):
        frame = getattr(self, "queue_list_frame", None)
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        count_label = getattr(self, "queue_count_label", None)
        if not self.download_queue:
            if count_label is not None:
                count_label.configure(text="")
            ctk.CTkLabel(frame, text="No downloads queued yet. Run Download to see "
                                      "what's pending here.", font=F(11.5), text_color=TEXT_FAINT,
                         wraplength=260, justify="left").pack(anchor="w", padx=8, pady=8)
            return
        pending = sum(1 for r in self.download_queue.values() if r["phase"] in ("queued", "downloading"))
        if count_label is not None:
            count_label.configure(text="%d pending" % pending)
        for row_data in self.download_queue.values():
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=row_data["name"] or "?", font=F(12, "bold"), text_color=TEXT,
                         anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=human_size(row_data["size"]), font=F(11), text_color=TEXT_FAINT
                         ).pack(side="left", padx=(8, 8))
            label, bg, fg = self._QUEUE_PILLS.get(row_data["phase"], ("?", SURFACE_3, TEXT_DIM))
            ctk.CTkLabel(row, text=label, font=F(10, "bold"), fg_color=bg, text_color=fg,
                         corner_radius=999, width=76, height=20).pack(side="left")

    def _build_update_panel(self, parent):
        opts = self._options_panel(parent)
        self.upd = {}

        g = Group(opts, "Scope"); g.pack(fill="x", pady=(0, 10))
        self.upd["scope"] = RadioGroup(g, [
            ("standard", "Standard", "new and updated games only"),
            ("skipknown", "Skip known", "skip games already in manifest"),
            ("updateonly", "Updates only", "only games marked with the update tag"),
            ("full", "Full rebuild", "every game on your account"),
        ], default=0)
        g.add(self.upd["scope"], span=2); g.finish()

        g = Group(opts, "Filter by platform & language"); g.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(g, text="Operating systems", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=g._row, column=0, columnspan=2, sticky="w", padx=14)
        g._row += 1
        self.upd["os"] = EnumChipSelect(
            g, [(o, o.capitalize()) for o in gog.VALID_OS_TYPES],
            default_selected=self.settings["update_os"],
            on_change=lambda vals: self._persist_chip_setting("update_os", vals))
        g.add(self.upd["os"], span=2)
        ctk.CTkLabel(g, text="Languages", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=g._row, column=0, columnspan=2, sticky="w", padx=14)
        g._row += 1
        self.upd["lang"] = EnumChipSelect(
            g, [(k, gog.LANG_TABLE[k]) for k in gog.VALID_LANG_TYPES],
            default_selected=self.settings["update_lang"],
            on_change=lambda vals: self._persist_chip_setting("update_lang", vals))
        g.add(self.upd["lang"], span=2); g.finish()

        g = Group(opts, "Filter by game"); g.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(g, text="Only these games", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=g._row, column=0, sticky="w", padx=14); g._row += 1
        self.upd["ids"] = ChipInput(g); g.add(self.upd["ids"], span=2)
        ctk.CTkLabel(g, text="Exclude these games", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=g._row, column=0, sticky="w", padx=14); g._row += 1
        self.upd["skipids"] = ChipInput(g); g.add(self.upd["skipids"], span=2); g.finish()

        g = Group(opts, "Behavior"); g.pack(fill="x", pady=(0, 10))
        self.upd["skiphidden"] = CheckRow(g, "Skip hidden games", "omit titles marked hidden on GOG")
        g.add(self.upd["skiphidden"], span=2)
        self.upd["strictverify"] = CheckRow(g, "Strict verify", "clear verified flag unless MD5 matches")
        g.add(self.upd["strictverify"], span=2)
        g.finish()

        adv = Advanced(opts, 6); adv.pack(fill="x", pady=(0, 20))
        self.upd["strictdupe"] = CheckRow(adv.body, "Strict dupe matching",
                                           "missing MD5s only match other missing MD5s")
        self.upd["strictdupe"].pack(fill="x", pady=3)
        self.upd["strictextrasupdate"] = CheckRow(adv.body, "Strict extras update",
                                                    "mark extras updated on timestamp change alone")
        self.upd["strictextrasupdate"].pack(fill="x", pady=3)
        self.upd["lenientdownloadsupdate"] = CheckRow(adv.body, "Lenient downloads update",
                                                        "don't mark installers updated on timestamp alone",
                                                        default=True)
        self.upd["lenientdownloadsupdate"].pack(fill="x", pady=3)
        self.upd["md5xmls"] = CheckRow(adv.body, "Fetch MD5 XML files",
                                        "save per-file MD5 sidecars where available")
        self.upd["md5xmls"].pack(fill="x", pady=3)
        self.upd["nochangelogs"] = CheckRow(adv.body, "Skip changelogs",
                                             "don't save per-game changelog text")
        self.upd["nochangelogs"].pack(fill="x", pady=3)

        wait_row = ctk.CTkFrame(adv.body, fg_color="transparent"); wait_row.pack(fill="x", pady=3)
        ctk.CTkLabel(wait_row, text="Wait before running (hours)", font=F(12),
                     text_color=TEXT).pack(side="left")
        self.upd["wait"] = tk.StringVar(value="0")
        ctk.CTkEntry(wait_row, textvariable=self.upd["wait"], width=70, font=F(12)
                     ).pack(side="left", padx=8)

        self._issues_panel(parent, "No issues yet. Warnings and errors from the "
                                    "last update will appear here.")

    def _build_download_panel(self, parent):
        opts = self._options_panel(parent)
        self.dl = {}

        g = Group(opts, "Installer types"); g.pack(fill="x", pady=(0, 10))
        self.dl["standalone"] = CheckRow(g, "Standalone", "classic offline installers", default=True)
        self.dl["galaxy"] = CheckRow(g, "Galaxy", "Galaxy-format installers", default=False)
        self.dl["shared"] = CheckRow(g, "Shared", "files common to both formats", default=True)
        g.add_pair(self.dl["standalone"], self.dl["galaxy"])
        g.add(self.dl["shared"], span=2); g.finish()

        g = Group(opts, "Content"); g.pack(fill="x", pady=(0, 10))
        self.dl["skipextras"] = CheckRow(g, "Skip extras", "soundtracks, art books, wallpapers")
        self.dl["covers"] = CheckRow(g, "Download covers", "save cover art per game", default=True)
        self.dl["backgrounds"] = CheckRow(g, "Download backgrounds", "save background art per game")
        g.add_pair(self.dl["skipextras"], self.dl["covers"])
        g.add(self.dl["backgrounds"], span=2); g.finish()

        g = Group(opts, "Filter by platform & language"); g.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(g, text="Operating systems (empty = all)", font=F(11.5, "bold"),
                     text_color=TEXT_DIM).grid(row=g._row, column=0, columnspan=2, sticky="w", padx=14)
        g._row += 1
        self.dl["os"] = EnumChipSelect(
            g, [(o, o.capitalize()) for o in gog.VALID_OS_TYPES],
            default_selected=self.settings["download_os"],
            on_change=lambda vals: self._persist_chip_setting("download_os", vals))
        g.add(self.dl["os"], span=2)
        ctk.CTkLabel(g, text="Languages (empty = all)", font=F(11.5, "bold"),
                     text_color=TEXT_DIM).grid(row=g._row, column=0, columnspan=2, sticky="w", padx=14)
        g._row += 1
        self.dl["lang"] = EnumChipSelect(
            g, [(k, gog.LANG_TABLE[k]) for k in gog.VALID_LANG_TYPES],
            default_selected=self.settings["download_lang"],
            on_change=lambda vals: self._persist_chip_setting("download_lang", vals))
        g.add(self.dl["lang"], span=2); g.finish()

        g = Group(opts, "Filter by game"); g.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(g, text="Only these games", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=g._row, column=0, sticky="w", padx=14); g._row += 1
        self.dl["ids"] = ChipInput(g); g.add(self.dl["ids"], span=2)
        ctk.CTkLabel(g, text="Exclude these games", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=g._row, column=0, sticky="w", padx=14); g._row += 1
        self.dl["skipids"] = ChipInput(g); g.add(self.dl["skipids"], span=2); g.finish()

        adv = Advanced(opts, 4); adv.pack(fill="x", pady=(0, 20))
        self.dl["skippreallocation"] = CheckRow(adv.body, "Skip preallocation",
                                                 "don't pre-reserve disk space for files")
        self.dl["skippreallocation"].pack(fill="x", pady=3)
        self.dl["clean_old_images"] = CheckRow(adv.body, "Clean old images",
                                                "replace rather than keep stale cover/background art",
                                                default=True)
        self.dl["clean_old_images"].pack(fill="x", pady=3)
        skipfiles_row = ctk.CTkFrame(adv.body, fg_color="transparent"); skipfiles_row.pack(fill="x", pady=3)
        ctk.CTkLabel(skipfiles_row, text="Skip file patterns", font=F(12), text_color=TEXT
                     ).pack(side="left")
        self.dl["skipfiles"] = tk.StringVar(value="")
        ctk.CTkEntry(skipfiles_row, textvariable=self.dl["skipfiles"], width=200, font=F(12),
                     placeholder_text="*.pdf, soundtrack*").pack(side="left", padx=8)
        limit_row = ctk.CTkFrame(adv.body, fg_color="transparent"); limit_row.pack(fill="x", pady=3)
        ctk.CTkLabel(limit_row, text="Bandwidth limit (MB/s, 0 = unlimited)", font=F(12),
                     text_color=TEXT).pack(side="left")
        self.dl["downloadlimit"] = tk.StringVar(value="0")
        ctk.CTkEntry(limit_row, textvariable=self.dl["downloadlimit"], width=70, font=F(12)
                     ).pack(side="left", padx=8)

        self._queue_panel(parent)

    def _build_verify_panel(self, parent):
        opts = self._options_panel(parent)
        self.vf = {}

        g = Group(opts, "Checks to run"); g.pack(fill="x", pady=(0, 10))
        self.vf["md5"] = CheckRow(g, "MD5 checksum", "strongest, slowest check", default=True)
        self.vf["size"] = CheckRow(g, "File size", "fast sanity check", default=True)
        self.vf["zip"] = CheckRow(g, "Zip integrity", "open and test archive contents", default=True)
        g.add_pair(self.vf["md5"], self.vf["size"])
        g.add(self.vf["zip"], span=2); g.finish()

        g = Group(opts, "On failure"); g.pack(fill="x", pady=(0, 10))
        self.vf["onfail"] = RadioGroup(g, [
            ("moveaside", "Move aside", "quarantine failed files (default)"),
            ("delete", "Delete", "remove failed files permanently"),
            ("leave", "Leave in place", "report only, don't touch files"),
        ], default=0)
        g.add(self.vf["onfail"], span=2); g.finish()

        # No OS/language filter here on purpose -- verify checks whatever's already
        # on disk, so filtering by platform/language isn't meaningful the way it is
        # for update/download. Filtering to a specific game is still useful, though.
        g = Group(opts, "Filter by game"); g.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(g, text="Only these games", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=g._row, column=0, sticky="w", padx=14); g._row += 1
        self.vf["ids"] = ChipInput(g); g.add(self.vf["ids"], span=2)
        ctk.CTkLabel(g, text="Exclude these games", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=g._row, column=0, sticky="w", padx=14); g._row += 1
        self.vf["skipids"] = ChipInput(g); g.add(self.vf["skipids"], span=2); g.finish()

        adv = Advanced(opts, 3); adv.pack(fill="x", pady=(0, 20))
        self.vf["permissivechangeclear"] = CheckRow(
            adv.body, "Permissive change-clear", "clear change flag on any pass, not just MD5")
        self.vf["permissivechangeclear"].pack(fill="x", pady=3)
        self.vf["forceverify"] = CheckRow(
            adv.body, "Re-verify unchanged files", "don't trust the last verified flag")
        self.vf["forceverify"].pack(fill="x", pady=3)
        skipfiles_row = ctk.CTkFrame(adv.body, fg_color="transparent"); skipfiles_row.pack(fill="x", pady=3)
        ctk.CTkLabel(skipfiles_row, text="Skip file patterns", font=F(12), text_color=TEXT
                     ).pack(side="left")
        self.vf["skipfiles"] = tk.StringVar(value="")
        ctk.CTkEntry(skipfiles_row, textvariable=self.vf["skipfiles"], width=200, font=F(12),
                     placeholder_text="*.pdf").pack(side="left", padx=8)

        self._issues_panel(parent, "No issues yet. Files that fail integrity "
                                    "checks will appear here once you run Verify.")

    def _open_settings_dialog(self):
        """Settings is a place you visit occasionally to configure things, not a
        place you work -- same small-modal-window pattern as the old standalone
        Sign-in dialog (native OS title bar X, plus an explicit Close button),
        independent of the main nav/run machinery. Holds both the shared game
        library directory (used by Download and Verify) and GOG sign-in."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("440x560")
        dialog.resizable(False, False)
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        dialog.grab_set()

        body = ctk.CTkFrame(dialog, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(body, text="Settings", font=F(16, "bold"), text_color=TEXT
                     ).pack(anchor="w", pady=(0, 14))

        lib_group = Group(body, "Game library"); lib_group.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(lib_group, text="Used by Download and Verify", font=F(11), text_color=TEXT_FAINT
                     ).grid(row=lib_group._row, column=0, columnspan=2, sticky="w", padx=14)
        lib_group._row += 1
        dir_row = ctk.CTkFrame(lib_group, fg_color="transparent")
        dir_var = tk.StringVar(value=self.settings["game_dir"])
        ctk.CTkEntry(dir_row, textvariable=dir_var, font=F(12)).pack(side="left", fill="x", expand=True)

        def browse_dir():
            chosen = filedialog.askdirectory(title="Choose game library directory",
                                              initialdir=dir_var.get() or ".")
            if chosen:
                dir_var.set(chosen)

        ctk.CTkButton(dir_row, text="Browse", width=70, command=browse_dir, font=F(11.5),
                      fg_color=SURFACE_2, hover_color=SURFACE_3, text_color=TEXT,
                      border_width=1, border_color=BORDER).pack(side="left", padx=(8, 0))
        lib_group.add(dir_row, span=2); lib_group.finish()

        def on_dir_change(*_a):
            self.settings["game_dir"] = dir_var.get()
            self._save_settings()

        dir_var.trace_add("write", on_dir_change)

        acct_group = Group(body, "GOG account"); acct_group.pack(fill="x", pady=(0, 14))
        has_token = os.path.isfile(gog.TOKEN_FILENAME)
        token_status = ctk.CTkLabel(
            acct_group,
            text=("Signed in -- token already saved" if has_token else "Not signed in yet"),
            font=F(11.5, "bold"), text_color=(GOOD if has_token else TEXT_FAINT))
        token_status.grid(row=acct_group._row, column=0, columnspan=2, sticky="w", padx=14)
        acct_group._row += 1
        ctk.CTkLabel(acct_group, text="Username or email", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=acct_group._row, column=0, columnspan=2, sticky="w", padx=14, pady=(8, 0))
        acct_group._row += 1
        username_var = tk.StringVar(value="")
        acct_group.add(ctk.CTkEntry(acct_group, textvariable=username_var, font=F(12)), span=2)

        ctk.CTkLabel(acct_group, text="Password", font=F(11.5, "bold"), text_color=TEXT_DIM
                     ).grid(row=acct_group._row, column=0, columnspan=2, sticky="w", padx=14)
        acct_group._row += 1
        password_var = tk.StringVar(value="")
        acct_group.add(ctk.CTkEntry(acct_group, textvariable=password_var, font=F(12), show="•"), span=2)

        ctk.CTkLabel(
            acct_group, text="GOG or Galaxy accounts only -- Google/Discord sign-in isn't "
                             "supported by this API. A prompt will pop up here if GOG asks "
                             "for a security code or a reCAPTCHA sign-in link.",
            font=F(10.5), text_color=TEXT_FAINT, wraplength=370, justify="left"
        ).grid(row=acct_group._row, column=0, columnspan=2, sticky="w", padx=14, pady=(2, 0))
        acct_group._row += 1
        acct_group.finish()

        status_var = tk.StringVar(value="")
        ctk.CTkLabel(body, textvariable=status_var, font=F(11.5), text_color=TEXT_DIM,
                     wraplength=390, justify="left").pack(anchor="w", pady=(0, 10))

        btn_row = ctk.CTkFrame(body, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom")
        close_btn = ctk.CTkButton(btn_row, text="Close", width=90, font=F(12),
                                   fg_color=SURFACE_2, hover_color=SURFACE_3, text_color=TEXT,
                                   border_width=1, border_color=BORDER, command=dialog.destroy)
        close_btn.pack(side="right")
        sign_in_btn = ctk.CTkButton(btn_row, text="▶  Sign in", font=F(12, "bold"),
                                     fg_color=ACCENT, hover_color=ACCENT, text_color=ACCENT_INK)
        sign_in_btn.pack(side="right", padx=(0, 8))

        def do_sign_in():
            username = username_var.get().strip()
            password = password_var.get()
            if not username or not password:
                status_var.set("Username and password are both required.")
                return
            sign_in_btn.configure(state="disabled", text="Signing in…")
            close_btn.configure(state="disabled")
            status_var.set("Signing in…")

            def worker():
                prior_input = getattr(gog, "input", None)
                gog.input = self._gui_prompt
                err = None
                try:
                    gog.cmd_login(username, password)
                except BaseException as exc:  # noqa: BLE001 -- see _run_command
                    err = str(exc) or exc.__class__.__name__
                finally:
                    if prior_input is None:
                        try:
                            del gog.input
                        except AttributeError:
                            pass
                    else:
                        gog.input = prior_input

                def finish():
                    if not dialog.winfo_exists():
                        return
                    sign_in_btn.configure(state="normal", text="▶  Sign in")
                    close_btn.configure(state="normal")
                    status_var.set("Signed in -- token saved." if err is None
                                    else "Failed: %s" % err)
                    if err is None:
                        token_status.configure(text="Signed in -- token already saved",
                                                text_color=GOOD)

                self.after(0, finish)

            threading.Thread(target=worker, daemon=True).start()

        sign_in_btn.configure(command=do_sign_in)

    # -- log / progress panel --------------------------------------------
    def _build_log_panel(self, main):
        panel = ctk.CTkFrame(main, fg_color=SURFACE, border_width=1, border_color=BORDER,
                              corner_radius=8, height=140)
        panel.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 18))
        panel.grid_propagate(False)

        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(10, 4))
        self.status_label = ctk.CTkLabel(head, text="Idle", font=F(12.5, "bold"), text_color=TEXT_DIM)
        self.status_label.pack(side="left")
        ctk.CTkButton(head, text="Clear", width=60, font=F(11.5), fg_color="transparent",
                      hover_color=SURFACE_2, text_color=TEXT_DIM,
                      command=self._clear_log).pack(side="right")

        self.progress = ctk.CTkProgressBar(panel, fg_color=SURFACE_2, progress_color=ACCENT,
                                            height=5)
        self.progress.pack(fill="x", padx=16, pady=(0, 10))
        self.progress.set(0)

        self.log_body = ctk.CTkTextbox(panel, fg_color=MONO_BG, text_color=TEXT_DIM,
                                        font=MONO(11.5), border_width=1, border_color=BORDER,
                                        wrap="none")
        self.log_body.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self.log_body.configure(state="disabled")

    def _clear_log(self):
        self.log_body.configure(state="normal")
        self.log_body.delete("1.0", "end")
        self.log_body.configure(state="disabled")

    # -- running commands --------------------------------------------------
    @staticmethod
    def _parse_list(text):
        return [p.strip() for p in text.replace(",", " ").split() if p.strip()]

    def _run_command(self, key):
        if self.job_running:
            return
        try:
            if key == "update":
                kwargs = self._collect_update_args()
                target = gog.cmd_update
            elif key == "download":
                kwargs = self._collect_download_args()
                target = gog.cmd_download
            elif key == "verify":
                kwargs = self._collect_verify_args()
                target = gog.cmd_verify
            else:
                return
        except ValueError as exc:
            self._append_log("input error: %s" % exc)
            return

        self.job_running = True
        self.issues = []
        self._render_issues()
        self.log_handler.setLevel(
            logging.DEBUG if (key == "update" and self.debug_var.get()) else logging.INFO)
        if key == "download":
            self.download_queue = {}
            self._render_download_queue()
        for b in self.nav_buttons.values():
            b.configure(state="disabled")
        self.run_button.configure(state="disabled", text="Running…")
        self.status_label.configure(text="Running %s…" % key)
        self.progress.configure(mode="indeterminate")
        self.progress.start()

        extra_kwargs = {"on_event": self._on_download_event} if key == "download" else {}

        def worker():
            self.wakelock.take_wakelock()
            err = None
            try:
                target(*kwargs, **extra_kwargs)
            except BaseException as exc:  # noqa: BLE001 -- gogrepoc uses sys.exit() for
                # some failures (e.g. missing/invalid token); SystemExit must be caught
                # here too or a real failure gets reported to the GUI as "Done".
                err = str(exc) or exc.__class__.__name__
            finally:
                self.wakelock.release_wakelock()
                self.log_queue.put(("done", err is None, err))

        threading.Thread(target=worker, daemon=True).start()

    def _gui_prompt(self, prompt_text=""):
        """Bridges gogrepoc's bare input() calls (2FA / TOTP / reCAPTCHA-bypass URL
        during login) to a modal GUI dialog. Must only be called from a worker thread;
        blocks that thread while the dialog is shown on the main thread."""
        result = {}
        done = threading.Event()

        def show():
            dialog = ctk.CTkInputDialog(text=prompt_text or "Input needed:", title="gogrepo")
            result["value"] = dialog.get_input()
            done.set()

        self.after(0, show)
        done.wait()
        return result.get("value") or ""

    def _on_job_done(self, ok, err):
        self.job_running = False
        for b in self.nav_buttons.values():
            b.configure(state="normal")
        self.run_button.configure(state="normal", text="▶  Run")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1.0 if ok else 0.0)
        self.status_label.configure(text="Done" if ok else ("Failed: %s" % err))
        self._load_manifest_snapshot()
        # Rows that never reached "done" (e.g. a failure inside the transfer loop we
        # deliberately don't hook into) would otherwise stick on "downloading" forever.
        changed = False
        for row_data in self.download_queue.values():
            if row_data["phase"] not in ("done", "incomplete"):
                row_data["phase"] = "incomplete"
                changed = True
        if changed:
            self._render_download_queue()
        self._refresh_snapshot_row()

    def _refresh_snapshot_row(self):
        key = getattr(self, "current_panel_key", None)
        if key is None or key == "login":
            return
        for child in self.snapshot_row.winfo_children():
            child.destroy()
        # Mockup style: one flush strip, cells divided by 1px border-colored gaps
        # (not separate rounded cards), spanning the full width evenly.
        self.snapshot_row.configure(fg_color=BORDER)
        stats = self._snapshot_stats(key)
        for i in range(len(stats)):
            self.snapshot_row.grid_columnconfigure(i, weight=1, uniform="stat")
        for i, (lbl, val) in enumerate(stats):
            cell = ctk.CTkFrame(self.snapshot_row, fg_color=SURFACE, corner_radius=0)
            cell.grid(row=0, column=i, sticky="nsew", padx=(0, 1) if i < len(stats) - 1 else 0)
            ctk.CTkLabel(cell, text=lbl.upper(), font=F(10, "bold"), text_color=TEXT_FAINT
                         ).pack(anchor="w", padx=18, pady=(10, 0))
            ctk.CTkLabel(cell, text=val, font=F(16, "bold"), text_color=TEXT
                         ).pack(anchor="w", padx=18, pady=(1, 10))
        ctk.CTkFrame(self.snapshot_row, height=1, fg_color=BORDER
                     ).grid(row=1, column=0, columnspan=len(stats), sticky="ew", pady=(1, 0))

    # -- arg collection, mirrors main()'s dispatch (gogrepoc.py:4200-4287) --
    def _collect_update_args(self):
        f = self.upd
        scope = f["scope"].get()
        os_list = f["os"].get() or list(gog.DEFAULT_OS_LIST)
        lang_list = f["lang"].get() or list(gog.DEFAULT_LANG_LIST)
        ids = f["ids"].get()
        skipknown = (scope == "skipknown")
        updateonly = (scope == "updateonly")
        full = (scope == "full") or (ids and scope == "standard")
        partial = not full
        wait_hours = float(f["wait"].get() or 0)
        if wait_hours > 0:
            gog.info("sleeping for %.2fhr..." % wait_hours)
            time.sleep(wait_hours * 60 * 60)
        return (
            os_list, lang_list, skipknown, updateonly, partial, ids, f["skipids"].get(),
            f["skiphidden"].get(), "standalone", "resume", f["strictverify"].get(),
            f["strictdupe"].get(), f["lenientdownloadsupdate"].get(),
            f["strictextrasupdate"].get(), f["md5xmls"].get(), f["nochangelogs"].get(),
        )

    def _collect_download_args(self):
        f = self.dl
        os_list = f["os"].get() or list(gog.VALID_OS_TYPES)
        lang_list = f["lang"].get() or list(gog.VALID_LANG_TYPES)
        limit_mb = float(f["downloadlimit"].get() or 0)
        downloadlimit = (limit_mb * 1024.0 * 1024.0) if limit_mb > 0 else None
        wait_hours = float(f.get("wait", tk.StringVar(value="0")).get() or 0)
        if wait_hours > 0:
            gog.info("sleeping for %.2fhr..." % wait_hours)
            time.sleep(wait_hours * 60 * 60)
        return (
            self.settings["game_dir"], f["skipextras"].get(), f["skipids"].get(), self.dry_run_var.get(),
            f["ids"].get(), os_list, lang_list,
            not f["galaxy"].get(), not f["standalone"].get(), not f["shared"].get(),
            self._parse_list(f["skipfiles"].get()), f["covers"].get(), f["backgrounds"].get(),
            f["skippreallocation"].get(), f["clean_old_images"].get(), downloadlimit,
        )

    def _collect_verify_args(self):
        f = self.vf
        os_list = list(gog.VALID_OS_TYPES)  # no UI filter -- verify everything on disk
        lang_list = list(gog.VALID_LANG_TYPES)
        onfail = f["onfail"].get()
        delete_on_fail = (onfail == "delete")
        clean_on_fail = (onfail != "leave")
        return (
            self.settings["game_dir"], False, f["skipids"].get(),
            f["md5"].get(), f["size"].get(), f["zip"].get(),
            delete_on_fail, clean_on_fail, f["ids"].get(), os_list, lang_list,
            False, False, False, self._parse_list(f["skipfiles"].get()),
            f["forceverify"].get(), f["permissivechangeclear"].get(),
        )


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
