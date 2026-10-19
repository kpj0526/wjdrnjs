"""Tkinter front end: settings, ROI calibration preview, start/stop, log."""
from __future__ import annotations

import logging
import logging.handlers
import math
import os
import queue
import sys
import threading
import tkinter as tk
from dataclasses import fields, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from .candidates import ORDERS, build_candidates, manual_point_reason
from . import __version__
from .capture import BACKENDS, CaptureError, Grabber
from .config import MAX_MANUAL_POINTS, Settings
from .engine import Bot
from .geometry import Mapping, WindowNotFound, enable_dpi_awareness, resolve_mapping
from .paths import data_dir, resolve_in_data_dir, sample_image, settings_path
from .preflight import run_preflight
from .vision import load_template, verify
from .winplace import fit_geometry, is_remote_session, monitor_work_areas
from .winput import DryRunMouse, Win32Mouse

log = logging.getLogger("r2clicker")
PREVIEW_W = 800
PICK_RADIUS = 7  # canvas px: clicking this close to a manual point selects it instead of adding one

# (field, label, kind) - kind: str|int|float|bool|tuple|rects|choice:<a>|<b>
FORM = [
    ("Window / coordinates", None, None),
    ("window_title", "Game window title contains", "str"),
    ("capture_backend", "Capture backend", "choice:" + "|".join(BACKENDS)),
    ("hide_helper_from_capture", "Hide this window from screenshots", "bool"),
    ("roi", "Search ROI x1,y1,x2,y2", "tuple"),
    ("Candidates", None, None),
    ("grid_step", "Grid step (px)", "int"),
    ("order", "Order", "choice:" + "|".join(ORDERS)),
    ("stagger", "Stagger rows", "bool"),
    ("prefer_mob_pixels", "Try busy/bright spots first", "bool"),
    ("sticky_radius", "Try near last hit first (radius, 0=off)", "int"),
    ("player_center", "Player center x,y (avoid)", "tuple"),
    ("player_radius", "Player avoid radius", "int"),
    ("ui_rects", "UI rects to avoid (x1,y1,x2,y2; ...)", "rects"),
    ("park_point", "Cursor park point x,y", "tuple"),
    ("Timing (seconds) / limits", None, None),
    ("wait_interval", "Wait after right click -> next cycle (s)", "float"),
    ("verify_delay", "Check nameplate after left click (s)", "float"),
    ("verify_timeout", "Give up nameplate check after (s)", "float"),
    ("right_click_delay", "Delay before right click (s)", "float"),
    ("max_attempts", "Max left clicks per cycle", "int"),
    ("max_cycles", "Max cycles (0=unlimited)", "int"),
    ("max_consecutive_failed_cycles", "Stop after N empty cycles", "int"),
    ("right_click_target", "Right click at", "choice:same|park"),
    ("Verification", None, None),
    ("verify_mode", "Mode", "choice:diff|absolute"),
    ("plate_min_white", "Min white text px", "int"),
    ("marker_min_green", "Min green marker px", "int"),
    ("require_outline", "Text must have dark outline", "bool"),
    ("verify_ignore_rects", "Ignore in check (x1,y1,x2,y2; ...)", "rects"),
    ("template_path", "Nameplate template PNG (optional)", "str"),
    ("Safety", None, None),
    ("emergency_hotkey", "Emergency stop key", "choice:F12|F11|F10|F9|PAUSE|END"),
    ("save_failure_shots", "Save screenshots of failed checks", "bool"),
]


def _fmt(v, kind):
    if kind == "tuple":
        return ", ".join(str(x) for x in v)
    if kind == "rects":
        return "; ".join(",".join(str(x) for x in r) for r in v)
    return str(v)


def _parse(text, kind):
    if kind == "int":
        return int(float(text))
    if kind == "float":
        return float(text)
    if kind == "tuple":
        return tuple(int(float(x)) for x in text.replace(" ", "").split(",") if x)
    if kind == "rects":
        out = []
        for part in text.split(";"):
            nums = [int(float(x)) for x in part.replace(" ", "").split(",") if x]
            if nums:
                if len(nums) != 4:
                    raise ValueError(f"rect needs 4 numbers: {part!r}")
                out.append(tuple(nums))
        return out
    return text


class QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue) -> None:
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(self.format(record))


class App:
    def __init__(self, root: tk.Tk, show: bool = True, force_visible: bool = False) -> None:
        self.root = root
        root.title(f"R2 target helper {__version__}")
        self.settings_file = settings_path()
        self.settings = Settings.load(self.settings_file)
        if force_visible and self.settings.hide_helper_from_capture:  # --show-window recovery flag
            self.settings.hide_helper_from_capture = False
            self.settings.load_notes.append("--show-window: hide_helper_from_capture turned off")
        self.remote_session = is_remote_session()  # checked once at startup
        self.grabber = Grabber(self.settings.capture_backend)
        self.vars: dict[str, tuple[tk.Variable, str]] = {}
        self.frame: np.ndarray | None = None
        self.frame_mapping: Mapping | None = None
        self.bot: Bot | None = None
        self.thread: threading.Thread | None = None
        self.log_q: queue.Queue = queue.Queue()
        self.drag_start = None
        self.verify_box = None
        self._build()
        self._setup_logging()
        for w in self.settings.load_warnings:
            log.warning("settings: %s", w)
        for n in self.settings.load_notes:
            log.info("settings: %s", n)
        log.info("settings file: %s", self.settings_file)
        self._load_initial_frame()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.place_window()
        # Automated smoke tests can set this flag to keep every helper window
        # withdrawn while still exercising the full Tk layout and callbacks.
        if show and os.environ.get("R2_HIDE_TEST_WINDOWS") != "1":
            self.bring_to_front()
        self._sync_capture_exclusion()
        self.root.after(100, self._poll)

    # ---------- layout ----------
    def _build(self):
        left = ttk.Frame(self.root)
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        right = ttk.Frame(self.root)
        right.pack(side="right", fill="y", padx=6, pady=6)

        bar = ttk.Frame(left)
        bar.pack(fill="x")
        ttk.Button(bar, text="Capture game screen", command=self.capture_preview).pack(side="left")
        ttk.Button(bar, text="Load screenshot...", command=self.load_image).pack(side="left", padx=4)
        ttk.Button(bar, text="Test check on image", command=self.test_verify).pack(side="left")
        ttk.Button(bar, text="Preflight check", command=self.preflight_check).pack(side="left", padx=4)
        ttk.Label(bar, text="  Drag sets:").pack(side="left")
        self.drag_mode = tk.StringVar(value="roi")
        for v, t in (("roi", "ROI"), ("player", "player"), ("park", "park point"), ("manual", "mob points")):
            ttk.Radiobutton(bar, text=t, value=v, variable=self.drag_mode).pack(side="left")

        self.canvas = tk.Canvas(left, width=PREVIEW_W, height=PREVIEW_W * 9 // 16, bg="#222", highlightthickness=0)
        self.canvas.pack(pady=4)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.status = ttk.Label(left, text="", foreground="#555")
        self.status.pack(fill="x")

        # manual candidates: picked on the preview in "mob points" mode, tried in list order
        mf = ttk.Frame(left)
        mf.pack(fill="x", pady=(4, 0))
        self.manual_list = tk.Listbox(mf, height=4, width=40, exportselection=False, activestyle="none",
                                      font=("Consolas", 9))
        self.manual_list.pack(side="left")
        self.manual_list.bind("<<ListboxSelect>>", lambda e: self.redraw())
        mb = ttk.Frame(mf)
        mb.pack(side="left", padx=4)
        for i, (text, cmd) in enumerate((("Up", lambda: self.move_manual_point(-1)),
                                         ("Down", lambda: self.move_manual_point(1)),
                                         ("Delete", self.delete_manual_point),
                                         ("Clear all", self.clear_manual_points))):
            ttk.Button(mb, text=text, width=9, command=cmd).grid(row=i // 2, column=i % 2)
        self.manual_info = ttk.Label(mf, text="", foreground="#555", wraplength=330, justify="left")
        self.manual_info.pack(side="left", fill="x", expand=True)

        ctl = ttk.Frame(left)
        ctl.pack(fill="x", pady=4)
        self.dry_var = tk.BooleanVar(value=self.settings.dry_run)
        ttk.Checkbutton(ctl, text="DRY RUN (no clicks)", variable=self.dry_var).pack(side="left")
        self.start_btn = ttk.Button(ctl, text="Start", command=self.start)
        self.start_btn.pack(side="left", padx=6)
        self.stop_btn = ttk.Button(ctl, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left")
        self.hotkey_lbl = ttk.Label(ctl, text="")
        self.hotkey_lbl.pack(side="left", padx=8)
        ttk.Button(ctl, text="Save settings", command=self.save).pack(side="right")
        ttk.Button(ctl, text="Open data folder", command=lambda: os.startfile(data_dir())).pack(side="right", padx=4)
        ttk.Button(ctl, text="Apply / redraw", command=self.apply).pack(side="right", padx=4)

        self.logbox = tk.Text(left, height=12, font=("Consolas", 9), state="disabled")
        self.logbox.pack(fill="both", expand=True)

        # the form scrolls, so the window still fits on small screens (e.g. 1366x768)
        fcanvas = tk.Canvas(right, highlightthickness=0, width=1, height=1)
        fscroll = ttk.Scrollbar(right, orient="vertical", command=fcanvas.yview)
        fcanvas.configure(yscrollcommand=fscroll.set)
        fscroll.pack(side="right", fill="y")
        fcanvas.pack(side="left", fill="both", expand=True)
        form = ttk.Frame(fcanvas)
        fcanvas.create_window((0, 0), window=form, anchor="nw")

        def fit_form(_e=None):
            fcanvas.configure(scrollregion=fcanvas.bbox("all"), width=form.winfo_reqwidth())

        form.bind("<Configure>", fit_form)
        fcanvas.bind("<Enter>", lambda e: fcanvas.bind_all(
            "<MouseWheel>", lambda ev: fcanvas.yview_scroll(-ev.delta // 120, "units")))
        fcanvas.bind("<Leave>", lambda e: fcanvas.unbind_all("<MouseWheel>"))
        self.form_canvas = fcanvas
        r = 0
        for name, label, kind in FORM:
            if label is None:
                ttk.Label(form, text=name, font=("Segoe UI", 9, "bold")).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))
                r += 1
                continue
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="w")
            val = getattr(self.settings, name)
            if kind == "bool":
                var = tk.BooleanVar(value=val)
                ttk.Checkbutton(form, variable=var, command=self.apply).grid(row=r, column=1, sticky="w")
            elif kind.startswith("choice:"):
                var = tk.StringVar(value=val)
                cb = ttk.Combobox(form, textvariable=var, values=kind[7:].split("|"), width=24, state="readonly")
                cb.grid(row=r, column=1, sticky="w")
                cb.bind("<<ComboboxSelected>>", lambda e: self.apply())
            else:
                var = tk.StringVar(value=_fmt(val, kind))
                e = ttk.Entry(form, textvariable=var, width=28)
                e.grid(row=r, column=1, sticky="w")
                e.bind("<Return>", lambda e: self.apply())
            self.vars[name] = (var, kind)
            r += 1

    def _setup_logging(self):
        fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s %(message)s", "%H:%M:%S")
        qh = QueueHandler(self.log_q)
        qh.setFormatter(fmt)
        handlers: list[logging.Handler] = [qh]
        self.log_file = None
        try:
            d = resolve_in_data_dir(self.settings.log_dir)
            d.mkdir(parents=True, exist_ok=True)
            self.log_file = d / "r2helper.log"
            fh = logging.handlers.RotatingFileHandler(self.log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
            handlers.append(fh)
        except OSError as e:
            self.log_q.put(f"WARNING log file disabled: {e}")
        for h in log.handlers:
            h.close()
        log.handlers[:] = handlers
        log.setLevel(logging.INFO)
        log.propagate = False

    # ---------- window placement ----------
    def _work_areas(self):
        areas = monitor_work_areas()
        if not areas:  # non-Windows or query failed: the Tk screen size is the best guess
            areas = [(0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())]
        return areas

    def place_window(self):
        """Size and position the window fully inside a monitor's work area.

        A saved position is reused only if its title bar is reachable on a current monitor
        (monitors may have been unplugged or rearranged); otherwise the window is centred on
        the primary monitor. The size is shrunk to fit (the settings form scrolls).
        """
        self.root.update_idletasks()
        req_w, req_h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        areas = self._work_areas()
        w, h, x, y = fit_geometry(req_w, req_h, areas, self.settings.window_geometry)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.update_idletasks()
        log.info("window %dx%d at (%d,%d); monitors: %s", w, h, x, y, areas)

    def bring_to_front(self):
        """Make sure the window is shown, not minimized, and in front. Every step is optional."""
        for step in (self.root.deiconify, self.root.lift):
            try:
                step()
            except tk.TclError as e:
                log.warning("window %s failed: %s", step.__name__, e)
        try:  # briefly topmost: beats focus-stealing prevention without staying on top
            self.root.attributes("-topmost", True)
            self.root.after(400, self._drop_topmost)
        except tk.TclError:
            pass
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def _drop_topmost(self):
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _remember_geometry(self):
        """Store only the window geometry (never unsaved form edits) for the next start."""
        try:
            if self.root.state() != "normal":
                return
            geometry = self.root.geometry()
            s = Settings.load(self.settings_file)
            if s.load_warnings:  # never overwrite a file we could not read
                return
            s.window_geometry = geometry
            s.save(self.settings_file)
        except (tk.TclError, OSError) as e:
            log.warning("could not remember window position: %s", e)

    def _sync_capture_exclusion(self):
        """Apply the opt-in "hide from screenshots" setting to this window.

        Off by default: on some systems WDA_EXCLUDEFROMCAPTURE also blanks the window itself
        (black content and taskbar preview), and remote-desktop/streaming viewers never show it.
        It is not needed for correctness: window capture never contains this window, and the
        screen backend refuses to capture while this window overlaps the game.
        Always off under Remote Desktop.
        """
        self.root.update_idletasks()
        try:
            hwnd = int(self.root.wm_frame(), 16)
        except (tk.TclError, ValueError):
            return
        remote = self.remote_session
        if not self.settings.hide_helper_from_capture or remote:
            if hwnd in self.grabber.excluded or hwnd not in self.grabber.own:
                self.grabber.include_window(hwnd)
                why = "Remote Desktop session" if remote else "disabled in settings"
                log.info("helper window is visible to screen capture (%s)", why)
        elif hwnd not in self.grabber.excluded:
            if self.grabber.exclude_window(hwnd):
                log.info("helper window is hidden from screenshots (untick 'Hide this window from "
                         "screenshots' if remote/streaming tools show it blank)")
            else:
                log.warning("this Windows version cannot exclude the helper from screen capture; "
                            "screen-backend captures fail while it overlaps the game")

    # ---------- settings ----------
    def read_form(self) -> Settings | None:
        s = Settings.from_dict({f.name: getattr(self.settings, f.name) for f in fields(Settings)})
        s.extra = dict(self.settings.extra)  # keys of a newer release survive a save
        try:
            for name, (var, kind) in self.vars.items():
                v = var.get()
                if kind not in ("bool",) and not kind.startswith("choice:"):
                    v = _parse(v, kind)
                setattr(s, name, v)
        except ValueError as e:
            messagebox.showerror("Invalid setting", str(e))
            return None
        s.dry_run = bool(self.dry_var.get())
        # unsafe manual points do not block editing (they are drawn red); start() refuses them
        problems = s.validate(include_manual=False)
        if problems:
            messagebox.showerror("Invalid settings", "\n".join(problems))
            return None
        return s

    def _commit_form(self) -> Settings | None:
        """Read the form as typed (no Enter/Apply needed), validate, and make it current.

        Every action button goes through this, so it always uses what is on screen.
        On invalid input the error is shown, self.settings is left unchanged and None is returned.
        """
        s = self.read_form()
        if s:
            changed = s.hide_helper_from_capture != self.settings.hide_helper_from_capture
            self.settings = s
            if changed:  # Win32 affinity call only when the checkbox actually changed
                self._sync_capture_exclusion()
                if s.hide_helper_from_capture and not self._confirm_still_visible():
                    s.hide_helper_from_capture = False
                    self.vars["hide_helper_from_capture"][0].set(False)
                    self._sync_capture_exclusion()
                    log.warning("'Hide this window from screenshots' reverted: the window was not visible")
        return s

    def _confirm_still_visible(self) -> bool:
        """Like a display-mode change: keep the setting only if the user can still see this window.
        The question is a separate dialog, which is never excluded, so it stays readable."""
        return bool(messagebox.askyesno(
            "Check the window",
            "Is the R2 target helper window (behind this message) still shown normally?\n\n"
            "Answer No if it turned black or invisible; the setting is then reverted.",
            default="no",
        ))

    def apply(self):
        if self._commit_form():
            self.redraw()

    def save(self):
        s = self._commit_form()
        if s:
            try:
                s.save(self.settings_file)
                log.info("settings saved to %s (%d manual points)", self.settings_file, len(s.manual_points))
                for p in s.manual_point_problems():
                    log.warning("saved, but a run is refused until fixed: %s", p)
            except OSError as e:
                messagebox.showerror("Save failed", f"Could not write {self.settings_file}:\n{e}")

    def _set_field(self, name, value):
        var, kind = self.vars[name]
        var.set(_fmt(value, kind))

    # ---------- preview ----------
    def _load_initial_frame(self):
        sample = sample_image()
        if sample:
            self._set_frame(np.asarray(Image.open(sample).convert("RGB")), f"sample: {sample.name}")
        else:
            self.redraw()

    def _set_frame(self, arr: np.ndarray, desc: str, mapping: Mapping | None = None):
        self.frame = arr
        h, w = arr.shape[:2]
        s = self.settings
        self.frame_mapping = mapping or Mapping(0, 0, w, h, s.ref_w, s.ref_h)
        self.verify_box = None
        self.status.config(text=f"{desc} ({w}x{h}); coordinates are reference {s.ref_w}x{s.ref_h}")
        self.redraw()

    def capture_preview(self):
        s = self._commit_form()
        if not s:
            return
        self.grabber.backend = s.capture_backend
        try:
            m, desc = resolve_mapping(s.window_title, s.ref_w, s.ref_h)
            frame = self.grabber.grab(m)
            desc += f" [{self.grabber.last_backend} capture]"
        except (WindowNotFound, CaptureError) as e:
            messagebox.showerror("Capture failed", str(e))
            return
        self._set_frame(frame, desc, Mapping(0, 0, m.width, m.height, m.ref_w, m.ref_h))

    def load_image(self):
        if not self._commit_form():
            return
        p = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.bmp"), ("All", "*.*")])
        if p:
            try:
                arr = np.asarray(Image.open(p).convert("RGB"))
            except (OSError, ValueError) as e:
                messagebox.showerror("Cannot open image", str(e))
                return
            self._set_frame(arr, Path(p).name)

    def test_verify(self):
        s = self._commit_form()
        if not s or self.frame is None:
            return
        s = replace(s, verify_mode="absolute")  # a single image has no baseline
        m = self.frame_mapping
        tmpl = load_template(s.template_path, s, (m.sx + m.sy) / 2) if s.template_path else None
        res = verify(self.frame, s, m, template=tmpl)
        self.verify_box = res.box
        log.info("check on preview image: %s", res.summary())
        self.redraw()

    def _k(self):
        """Reference -> canvas scale."""
        return PREVIEW_W / self.settings.ref_w

    def redraw(self):
        c = self.canvas
        c.delete("all")
        s = self.settings
        k = self._k()
        if self.frame is not None:
            img = Image.fromarray(self.frame).resize((PREVIEW_W, round(s.ref_h * k)), Image.BILINEAR)
            self._tk_img = ImageTk.PhotoImage(img)
            c.create_image(0, 0, image=self._tk_img, anchor="nw")
        for (x1, y1, x2, y2) in s.ui_rects:
            c.create_rectangle(x1 * k, y1 * k, x2 * k, y2 * k, outline="#ff4040", stipple="gray25", fill="#ff4040")
        for (x1, y1, x2, y2) in s.verify_ignore_rects:
            c.create_rectangle(x1 * k, y1 * k, x2 * k, y2 * k, outline="#ffa500", dash=(3, 3))
        px, py = s.player_center
        rr = s.player_radius
        c.create_oval((px - rr) * k, (py - rr) * k, (px + rr) * k, (py + rr) * k, outline="#ff4040", width=2)
        x1, y1, x2, y2 = s.roi
        c.create_rectangle(x1 * k, y1 * k, x2 * k, y2 * k, outline="#40ff40", width=2)
        n = s.max_attempts
        if s.manual_points:
            footer = self._draw_manual_points()
        else:
            cands = build_candidates(s, self.frame, self.frame_mapping) if self.frame is not None else build_candidates(s)
            for i, cd in enumerate(cands):
                col = "#ffff00" if i < n else "#808080"
                cx, cy = cd.x * k, cd.y * k
                c.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=col, outline="")
                if i < min(n, 40):
                    c.create_text(cx + 3, cy - 6, text=str(i + 1), fill=col, font=("Segoe UI", 7), anchor="w")
            footer = f"{len(cands)} candidates, first {min(n, len(cands))} used per cycle (yellow). "
        qx, qy = s.park_point
        c.create_line(qx * k - 6, qy * k - 6, qx * k + 6, qy * k + 6, fill="#40a0ff", width=2)
        c.create_line(qx * k - 6, qy * k + 6, qx * k + 6, qy * k - 6, fill="#40a0ff", width=2)
        if self.verify_box:
            bx1, by1, bx2, by2 = self.verify_box
            c.create_rectangle(bx1 * k, by1 * k, bx2 * k, by2 * k, outline="#00ffff", width=2)
        c.create_text(6, c.winfo_reqheight() - 8, anchor="sw", fill="#fff", font=("Segoe UI", 8),
                      text=footer + "Green=ROI, red=avoid, blue X=park, orange=ignored by check")
        self._refresh_manual_list()

    def _draw_manual_points(self) -> str:
        """Numbered manual points: cyan = used, grey = beyond max_attempts, red X = refused."""
        c, s, k = self.canvas, self.settings, self._k()
        sel = self._manual_selected()
        used = bad = 0
        for i, p in enumerate(s.manual_points):
            cx, cy = p[0] * k, p[1] * k
            if manual_point_reason(p, s):
                bad += 1
                col = "#ff3030"
                c.create_line(cx - 5, cy - 5, cx + 5, cy + 5, fill=col, width=2, tags="manual")
                c.create_line(cx - 5, cy + 5, cx + 5, cy - 5, fill=col, width=2, tags="manual")
            else:
                col = "#00e5ff" if used < s.max_attempts else "#808080"
                used += 1
                c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, outline=col, width=2, tags="manual")
            if i == sel:
                c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, outline="#ffffff", tags="manual")
            c.create_text(cx + 7, cy - 8, text=str(i + 1), fill=col, font=("Segoe UI", 8, "bold"),
                          anchor="w", tags=("manual", "manual_label"))
        refused = f", {bad} REFUSED (red X: outside ROI or in an avoid area)" if bad else ""
        return (f"{len(s.manual_points)} manual points{refused}; first {min(s.max_attempts, used)} valid used "
                "per cycle in list order, auto grid off. ")

    # ---------- manual candidates ----------
    def _manual_selected(self) -> int | None:
        sel = self.manual_list.curselection()
        return sel[0] if sel else None

    def _refresh_manual_list(self):
        s, lb = self.settings, self.manual_list
        keep = self._manual_selected()
        lb.delete(0, "end")
        for i, p in enumerate(s.manual_points):
            why = manual_point_reason(p, s)
            lb.insert("end", f"{i + 1:>3}. ({p[0]}, {p[1]})" + (f"  REFUSED: {why}" if why else ""))
            if why:
                lb.itemconfig("end", foreground="#c00000")
        if keep is not None and keep < lb.size():
            lb.selection_set(keep)
            lb.see(keep)
        if not s.manual_points and not self.manual_info.cget("text"):
            self.manual_info.config(text="No manual points: the automatic grid is used. Choose 'mob points' "
                                         "above and click the preview to add points in click order.")

    def _set_manual_points(self, pts, select: int | None = None):
        # a new Settings object: a running Bot keeps the settings it was started with
        self.settings = replace(self.settings, manual_points=[tuple(p) for p in pts])
        self.manual_list.selection_clear(0, "end")
        if select is not None and 0 <= select < len(pts):
            self._refresh_manual_list()
            self.manual_list.selection_set(select)
            self.manual_list.see(select)
        self.redraw()

    def _manual_message(self, text: str, warn: bool = False):
        self.manual_info.config(text=text, foreground="#c00000" if warn else "#555")
        (log.warning if warn else log.info)("manual points: %s", text)

    def add_manual_point(self, x: int, y: int) -> bool:
        """Append a reference point. Refused (nothing added) wherever a run would refuse it."""
        s = self.settings
        why = manual_point_reason((x, y), s)
        if why:
            self._manual_message(f"point ({x}, {y}) not added: {why}", warn=True)
            return False
        if len(s.manual_points) >= MAX_MANUAL_POINTS:
            self._manual_message(f"point not added: at most {MAX_MANUAL_POINTS} manual points", warn=True)
            return False
        self._set_manual_points(list(s.manual_points) + [(x, y)], select=len(s.manual_points))
        self._manual_message(f"point {len(self.settings.manual_points)} added at ({x}, {y}); "
                             "Save settings to keep it")
        return True

    def delete_manual_point(self):
        i = self._manual_selected()
        if i is None:
            self._manual_message("select a point in the list (or click it on the preview) to delete it")
            return
        pts = list(self.settings.manual_points)
        x, y = pts.pop(i)
        self._set_manual_points(pts, select=min(i, len(pts) - 1))
        self._manual_message(f"point {i + 1} ({x}, {y}) deleted")

    def clear_manual_points(self):
        n = len(self.settings.manual_points)
        if not n or not messagebox.askyesno(
                "Clear manual points",
                f"Delete all {n} manual points?\n\nThe automatic grid is used again when the list is empty."):
            return
        self._set_manual_points([])
        self._manual_message(f"all {n} manual points deleted; the automatic grid is used")

    def move_manual_point(self, delta: int):
        i = self._manual_selected()
        pts = list(self.settings.manual_points)
        if i is None or not 0 <= i + delta < len(pts):
            return
        j = i + delta
        pts[i], pts[j] = pts[j], pts[i]
        self._set_manual_points(pts, select=j)
        self._manual_message(f"point moved to position {j + 1}")

    def _manual_point_near(self, ex, ey) -> int | None:
        """Index of the manual point within PICK_RADIUS canvas px of (ex, ey), nearest first."""
        k = self._k()
        near = [(math.hypot(x * k - ex, y * k - ey), i) for i, (x, y) in enumerate(self.settings.manual_points)]
        near = [d for d in near if d[0] <= PICK_RADIUS]
        return min(near)[1] if near else None

    def _on_press(self, e):
        self.drag_start = (e.x, e.y)

    def _on_drag(self, e):
        if self.drag_mode.get() != "roi" or not self.drag_start:
            return
        self.canvas.delete("drag")
        self.canvas.create_rectangle(*self.drag_start, e.x, e.y, outline="#80ff80", dash=(4, 2), tags="drag")

    def _on_release(self, e):
        k = self._k()
        ref = lambda x, y: (round(x / k), round(y / k))
        mode = self.drag_mode.get()
        if mode == "manual":
            self.drag_start = None
            if not self._commit_form():  # check the point against the ROI/avoid areas as typed
                return
            hit = self._manual_point_near(e.x, e.y)
            if hit is not None:  # clicking an existing point selects it (for Delete/Up/Down)
                self.manual_list.selection_clear(0, "end")
                self.manual_list.selection_set(hit)
                self.redraw()
            else:
                self.add_manual_point(*ref(e.x, e.y))
            return
        if mode == "roi" and self.drag_start:
            (ax, ay), (bx, by) = ref(*self.drag_start), ref(e.x, e.y)
            if abs(bx - ax) > 20 and abs(by - ay) > 20:
                self._set_field("roi", (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)))
        elif mode == "player":
            self._set_field("player_center", ref(e.x, e.y))
        elif mode == "park":
            self._set_field("park_point", ref(e.x, e.y))
        self.drag_start = None
        self.apply()

    # ---------- run ----------
    def _preflight(self, s: Settings):
        """Run the preflight checks for s and write every item to the log. Never clicks."""
        self.grabber.backend = s.capture_backend
        report = run_preflight(s, self.grabber.grab, live=not s.dry_run, resolve=resolve_mapping)
        for item in report.items:
            (log.error if item.status == "FAIL" else log.warning if item.status == "warn" else log.info)(
                "preflight %s", item.line())
        log.info("preflight %s", "passed" if report.ok else "FAILED: the run is not started")
        return report

    def preflight_check(self):
        s = self._commit_form()
        if not s:
            return
        report = self._preflight(s)  # its settings check includes the manual points
        lines = [i.line() for i in report.items]
        if report.ok:
            messagebox.showinfo("Preflight passed", "\n\n".join(lines))
        else:
            messagebox.showerror("Preflight failed", "Start is refused until these are fixed:\n\n" + "\n\n".join(lines))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        s = self._commit_form()
        if not s:
            return
        problems = s.manual_point_problems()
        if problems:
            messagebox.showerror("Manual points refused", "Delete or move these manual points (red X on the "
                                 "preview) before starting:\n\n" + "\n".join(problems))
            return
        report = self._preflight(s)
        if not report.ok:
            messagebox.showerror("Preflight failed - not started",
                                 "Nothing was clicked. Fix these first:\n\n"
                                 + "\n\n".join(f"{i.name}: {i.message}" for i in report.failures))
            return
        if not s.dry_run:
            warn = "".join(f"\n- {i.name}: {i.message}" for i in report.warnings if i.name != "mode")
            ok = messagebox.askyesno(
                "Live mode",
                f"Dry run is OFF: the tool will really click inside '{s.window_title or 'the screen'}'.\n\n"
                + (f"Preflight warnings:{warn}\n\n" if warn else "")
                + f"Emergency stop: hold {s.emergency_hotkey}, or move the cursor into the top-left corner.\n\nContinue?",
            )
            if not ok:
                return
            # Constructing the Win32 backend can fail before the worker thread
            # exists (for example when a source checkout is run on a non-Windows
            # host, or when the Win32 API is unavailable).  Treat that as a
            # refused start and leave the GUI usable instead of letting a Tk
            # callback traceback escape with no visible explanation.
            try:
                mouse = Win32Mouse()
            except Exception as e:
                log.exception("could not initialise live mouse input")
                messagebox.showerror("Live mode unavailable", str(e))
                return
        else:
            mouse = DryRunMouse()
        self.grabber.backend = s.capture_backend
        log.info("wait after right click -> next cycle: %.3f s", s.wait_interval)
        if s.manual_points:
            log.info("using %d manual points in list order (automatic grid off)", len(s.manual_points))
        self.bot = Bot(s, self.grabber.grab, mouse)
        self.thread = threading.Thread(target=self.bot.run, daemon=True)
        self.thread.start()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.hotkey_lbl.config(text=f"RUNNING ({'dry run' if s.dry_run else 'LIVE'}) - {s.emergency_hotkey} stops",
                               foreground="#c00" if not s.dry_run else "#060")

    def stop(self):
        if self.bot:
            self.bot.stop("Stop button")

    def _poll(self):
        while True:
            try:
                line = self.log_q.get_nowait()
            except queue.Empty:
                break
            self.logbox.config(state="normal")
            self.logbox.insert("end", line + "\n")
            if int(self.logbox.index("end-1c").split(".")[0]) > 2000:
                self.logbox.delete("1.0", "500.0")
            self.logbox.see("end")
            self.logbox.config(state="disabled")
        if self.thread and not self.thread.is_alive():
            self.thread = None
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            reason = self.bot.stop_reason if self.bot else ""
            self.hotkey_lbl.config(text=f"stopped: {reason}", foreground="#555")
        self.root.after(100, self._poll)


    def on_close(self):
        if self.bot:
            self.bot.stop("window closed")
        if self.thread:
            self.thread.join(timeout=3)
        self._remember_geometry()
        self.root.destroy()


def _report_startup_crash(exc: BaseException) -> None:
    """A windowed exe has no console: write the traceback to a file and try to show it."""
    import traceback

    text = "".join(traceback.format_exception(exc))
    path = None
    try:
        path = data_dir() / "startup-error.log"
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass
    try:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("R2 target helper could not start", f"{exc}\n\nDetails: {path or text[-1500:]}")
        r.destroy()
    except Exception:
        pass


def main(force_visible: bool = False):
    enable_dpi_awareness()
    try:
        root = tk.Tk()
        root.report_callback_exception = lambda et, ev, tb: log.error("GUI error", exc_info=(et, ev, tb))
        App(root, force_visible=force_visible)
    except Exception as e:
        _report_startup_crash(e)
        raise
    root.mainloop()


if __name__ == "__main__" and sys.argv:
    main()
