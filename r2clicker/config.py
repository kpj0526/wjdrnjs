"""Settings model.

All coordinates are *reference* coordinates in the 1600x900 game client the
screenshots were taken from. At runtime they are scaled to the real client
size (see geometry.py), so the same settings work at other resolutions.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

REF_W, REF_H = 1600, 900
SETTINGS_VERSION = 6  # 2: hide_helper_from_capture is an explicit opt-in (default off)
                      # 5: right click right after a successful check (0.2.x files: auto clicker)
                      # 6: nameplate check calibrated on real R2 screenshots

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 (x2/y2 exclusive)
Point = tuple[int, int]
MAX_MANUAL_POINTS = 200

# HUD regions of the reference screenshot that must never be clicked.
DEFAULT_UI_RECTS: list[Rect] = [
    (0, 0, 170, 165),        # minimap
    (730, 0, 875, 32),       # clock
    (940, 0, 1600, 165),     # buff icons
    (0, 680, 400, 835),      # chat
    (0, 835, 535, 900),      # server/zone line, R2 logo
    (530, 750, 915, 900),    # level / HP / MP panel, quick slot
    (915, 695, 1320, 900),   # skill hotbar
]


@dataclass
class Settings:
    # --- window / coordinate mapping ---
    window_title: str = "R2"          # substring of the game window title; "" = whole primary screen
    ref_w: int = REF_W
    ref_h: int = REF_H
    capture_backend: str = "auto"     # auto | window (PrintWindow) | screen (mss + occlusion check)

    # --- search area and candidate pattern ---
    roi: Rect = (350, 130, 1250, 670)
    grid_step: int = 55
    order: str = "center_out"         # center_out | raster | snake | spiral
    stagger: bool = True              # offset every other row by step/2 (hex-like coverage)
    player_center: tuple[int, int] = (800, 440)
    player_radius: int = 75
    ui_rects: list[Rect] = field(default_factory=lambda: list(DEFAULT_UI_RECTS))
    prefer_mob_pixels: bool = True    # rank candidates by local colour/texture score
    mob_score_min: float = 0.0        # candidates scoring below this are dropped (0 = keep all)
    sticky_radius: int = 120          # try points near the last success first (0 = off)
    manual_points: list[Point] = field(default_factory=list)  # user-picked click points, tried in
                                      # this order; when non-empty they replace the automatic grid

    # --- timing (seconds) ---
    wait_interval: float = 5.0        # seconds from the end of a cycle (its right click, or its last
                                      # failed attempt) to the start of the next cycle
    verify_delay: float = 0.25        # after left click, before verification screenshot
    verify_timeout: float = 0.6       # keep re-checking until this long after the click
    settle_delay: float = 0.08        # after moving cursor off, before the baseline shot
    right_click_delay: float = 0.0    # between successful verification and right click (0 = at once)
    right_click_hover: float = 0.1    # cursor rests on the target this long before the right click
    right_click_press: float = 0.15   # how long the right button is held down (left: 0.03)

    # --- limits ---
    max_attempts: int = 30            # left clicks per cycle before giving up the cycle
    max_cycles: int = 0               # 0 = unlimited
    max_consecutive_failed_cycles: int = 3  # stop the run after this many empty cycles

    # --- clicking ---
    dry_run: bool = True
    park_point: tuple[int, int] = (1480, 300)  # cursor rest point (empty floor, off ROI)
    right_click_target: str = "same"  # same | park  (where the right click lands)
    park_during_check: bool = False   # move the cursor to the park point while checking the nameplate.
                                      # Off: it stays on the mob, which R2 needs for the right click

    # --- verification (nameplate: white text + green markers) ---
    verify_mode: str = "absolute"     # absolute = as-is (a still visible nameplate counts);
                                      # diff = only pixels new since the baseline
    verify_margin: int = 80           # verify area = ROI grown by this (nameplate floats above mob)
    white_min: int = 215              # min channel value for "white"
    white_max_spread: int = 30        # max(R,G,B)-min(R,G,B) for "white"
    green_min_g: int = 150
    green_min_delta: int = 60         # G-R and G-B both at least this
    diff_min: int = 40                # per-pixel change needed to count as new (diff mode)
    require_outline: bool = True      # text pixels must touch dark outline/background (rejects glows)
    outline_dark_max: int = 100       # mean RGB at or below this counts as dark
    outline_radius: int = 2
    max_stroke_run: int = 24          # straight white runs at least this long are bars/frames, not text
    verify_ignore_rects: list[Rect] = field(default_factory=lambda: [(735, 345, 865, 480)])  # player HP bar + skill flash
    plate_w: int = 90                 # expected nameplate text box (reference px)
    plate_h: int = 16
    plate_min_white: int = 150        # min white pixels inside the best text box (real R2 nameplate:
                                      # ~320; screen without one: up to ~60)
    marker_search: int = 40           # look for green this far around the text box
    marker_min_green: int = 12        # min green pixels around the text box
    plate_max_distance: int = 250     # nameplate centre at most this far from the clicked point (0 = anywhere);
                                      # rejects other mobs' or players' nameplates elsewhere on screen
    template_path: str = ""           # optional cropped nameplate PNG for template matching
    template_min_score: float = 0.55

    # --- safety ---
    emergency_hotkey: str = "F12"
    corner_failsafe: bool = True      # cursor in the top-left screen corner stops the run
    hide_helper_from_capture: bool = False  # opt-in: exclude the helper window from screenshots.
                                            # On some systems this also blanks the window itself
                                            # (black window/taskbar preview), and remote/streaming
                                            # viewers never show it. Window capture never needs it.

    # --- helper window ---
    window_geometry: str = ""         # last window size/position "WxH+X+Y"; corrected onto a monitor at start

    # --- logging ---
    log_dir: str = "logs"             # relative paths are resolved against the app data folder
    save_failure_shots: bool = False

    # --- right click confirmation: the target panel at the bottom centre ("<name>" + HP dots) ---
    confirm_right_click: bool = True  # after the right click, look for the target panel
    target_panel_rect: Rect = (690, 735, 910, 782)
    panel_timeout: float = 0.6        # wait this long for the panel after a right click
    right_click_retries: int = 1      # right click again this many times when no panel appears

    settings_version: int = SETTINGS_VERSION
    load_warnings: list[str] = field(default_factory=list, repr=False, compare=False)
    load_notes: list[str] = field(default_factory=list, repr=False, compare=False)  # migrations
    # keys this version does not know (written by a newer release): kept on save, never dropped
    extra: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        """Load settings; a missing, unreadable or corrupt file gives defaults (never raises).

        Problems are recorded in `load_warnings` so the GUI can show them.
        """
        p = Path(path)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("top level is not an object")
        except (OSError, ValueError) as e:
            s = cls()
            s.load_warnings.append(f"{p.name} could not be read ({e}); using defaults")
            # keep the unreadable file: a later "Save settings" overwrites it with the form values
            try:
                backup = _backup_unreadable(p)
                s.load_warnings.append(f"a copy of the unreadable file is kept as {backup.name}")
            except OSError:
                pass
            return s
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Settings from a dict. Values of the wrong type keep the default and add a warning."""
        s = cls()
        known = {f.name for f in fields(cls)}
        s.extra = {k: v for k, v in data.items() if k not in known and k not in REMOVED_KEYS}
        version = data.get("settings_version") if isinstance(data.get("settings_version"), int) else 1
        # before 5 the right click waited 0.1 s after the check (0.1.x) or meant something else (0.2.x):
        # the new defaults (right away) apply
        skip = {"right_click_delay", "right_click_hover"} if version < 5 else set()
        if version < 6:  # guessed before real screenshots: the calibrated defaults apply
            skip |= {"verify_mode", "plate_min_white", "plate_max_distance"}
        for f in fields(cls):
            if f.name not in data or f.name in _INTERNAL or f.name in skip:
                continue
            default = getattr(s, f.name)
            try:
                v = _coerce(data[f.name], default, f.name)
            except (TypeError, ValueError):
                s.load_warnings.append(f"{f.name}: invalid value {data[f.name]!r}; using {default!r}")
                continue
            setattr(s, f.name, v)
        if version < 2:
            # Version 1 files stored hide_helper_from_capture=True as the old default, not as a user
            # choice, and it can leave the window black on screen: reset it to the safe default.
            if s.hide_helper_from_capture:
                s.load_notes.append("hide_helper_from_capture reset to off (it was the old default, "
                                    "not a choice; it can make this window black)")
            s.hide_helper_from_capture = False
        s.settings_version = SETTINGS_VERSION
        return s

    def save(self, path: str | Path) -> None:
        """Atomic write: a crash mid-save never leaves a truncated settings file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        for k in _INTERNAL:
            d.pop(k, None)
        d = {**{k: v for k, v in self.extra.items() if k not in d}, **d}
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    def validate(self, include_manual: bool = True) -> list[str]:
        """Human-readable problems that must be fixed before a run. Empty list = OK.

        include_manual=False leaves out manual_point_problems(): the GUI uses that so changing
        the ROI is still possible while it marks the manual points the change made unsafe.
        """
        from .candidates import ORDERS
        from .winput import VK_CODES

        e: list[str] = []
        W, H = self.ref_w, self.ref_h
        if W <= 0 or H <= 0:
            e.append("reference size must be positive")
        if len(self.roi) != 4:
            e.append("ROI needs x1,y1,x2,y2")
        else:
            x1, y1, x2, y2 = self.roi
            if not (0 <= x1 < x2 <= W and 0 <= y1 < y2 <= H):
                e.append(f"ROI must satisfy 0 <= x1 < x2 <= {W} and 0 <= y1 < y2 <= {H}")
            elif x2 - x1 < self.grid_step or y2 - y1 < self.grid_step:
                e.append("ROI is smaller than one grid step")
        for name in ("player_center", "park_point"):
            pt = getattr(self, name)
            if len(pt) != 2:
                e.append(f"{name} needs x,y")
            elif not (0 <= pt[0] < W and 0 <= pt[1] < H):
                e.append(f"{name} must be inside the {W}x{H} game client")
        if len(self.park_point) == 2 and len(self.roi) == 4:
            x1, y1, x2, y2 = self.roi
            px, py = self.park_point
            if x1 <= px < x2 and y1 <= py < y2:
                e.append("park point must be outside the ROI (the cursor would hover mobs)")
        r = self.target_panel_rect
        if len(r) != 4 or not (0 <= r[0] < r[2] <= W and 0 <= r[1] < r[3] <= H):
            e.append(f"target_panel_rect must be x1,y1,x2,y2 inside the {W}x{H} game client")
        for name in ("ui_rects", "verify_ignore_rects"):
            for r in getattr(self, name):
                if len(r) != 4 or r[0] >= r[2] or r[1] >= r[3]:
                    e.append(f"{name}: bad rect {r!r}")
        rng = {
            "grid_step": (5, 500), "player_radius": (0, 800), "sticky_radius": (0, 2000),
            "wait_interval": (0, 86400), "verify_delay": (0, 10), "verify_timeout": (0, 30),
            "settle_delay": (0, 5), "right_click_delay": (0, 10),
            "right_click_hover": (0, 2), "right_click_press": (0.01, 2), "plate_max_distance": (0, 2000),
            "max_attempts": (1, 1000), "max_cycles": (0, 10**9), "max_consecutive_failed_cycles": (0, 10**6),
            "verify_margin": (0, 400), "white_min": (0, 255), "white_max_spread": (0, 255),
            "green_min_g": (0, 255), "green_min_delta": (0, 255), "diff_min": (0, 255),
            "outline_dark_max": (0, 255), "outline_radius": (0, 10), "max_stroke_run": (0, 400),
            "plate_w": (4, 800), "plate_h": (4, 200), "plate_min_white": (1, 10**6),
            "panel_timeout": (0, 10), "right_click_retries": (0, 10),
            "marker_search": (0, 400), "marker_min_green": (0, 10**6), "template_min_score": (0, 1),
        }
        for name, (lo, hi) in rng.items():
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (lo <= v <= hi):
                e.append(f"{name} must be a number in [{lo}, {hi}] (got {v!r})")
        numeric = all(isinstance(v, (int, float)) for v in (self.verify_timeout, self.verify_delay))
        if numeric and self.verify_timeout < self.verify_delay:
            e.append("verify_timeout must be >= verify_delay")
        from .capture import BACKENDS

        choices = {"capture_backend": BACKENDS, "order": ORDERS, "verify_mode": ("diff", "absolute"),
                   "right_click_target": ("same", "park")}
        for name, ok in choices.items():
            if getattr(self, name) not in ok:
                e.append(f"{name} must be one of {', '.join(ok)}")
        if self.emergency_hotkey and self.emergency_hotkey.upper() not in VK_CODES:
            e.append(f"emergency_hotkey must be one of {', '.join(VK_CODES)}")
        if not self.dry_run and not self.emergency_hotkey and not self.corner_failsafe:
            e.append("live mode needs an emergency hotkey or the corner failsafe")
        if self.template_path and not Path(self.template_path).is_file():
            e.append(f"template file not found: {self.template_path}")
        if include_manual:
            e.extend(self.manual_point_problems())
        return e

    def manual_point_problems(self) -> list[str]:
        """Manual points that would be refused at run time (outside the ROI, player or HUD)."""
        from .candidates import manual_point_reason

        e: list[str] = []
        if len(self.manual_points) > MAX_MANUAL_POINTS:
            e.append(f"at most {MAX_MANUAL_POINTS} manual points (got {len(self.manual_points)})")
        if len(self.roi) != 4:
            return e
        for i, p in enumerate(self.manual_points, 1):
            why = manual_point_reason(p, self)
            if why:
                e.append(f"manual point {i} {tuple(p)}: {why}")
        return e


_INTERNAL = ("load_warnings", "load_notes", "extra")
REMOVED_KEYS = frozenset({"right_click_hold", "point_delay"})  # settings of earlier releases that no longer exist


def _backup_unreadable(p: Path) -> Path:
    """Copy p to <name>.unreadable (timestamped if a different copy is already there). Loading the
    same broken file again (the GUI reloads it on close) does not create more copies."""
    data = p.read_bytes()
    backup = p.with_name(p.name + ".unreadable")
    if backup.exists() and backup.read_bytes() != data:
        backup = p.with_name(f"{p.name}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}")
    if not backup.exists():
        shutil.copy2(p, backup)
    return backup


def _coerce(v, default, name):
    """Convert a JSON value to the type of the default (tuples, rect lists, bool, int, float, str)."""
    if name in ("ui_rects", "verify_ignore_rects"):
        return [tuple(int(x) for x in r) for r in v]
    if name == "manual_points":
        pts = [tuple(int(x) for x in p) for p in v]
        if any(len(p) != 2 for p in pts):
            raise ValueError(name)
        return pts
    if isinstance(default, bool):
        if not isinstance(v, bool):
            raise TypeError(name)
        return v
    if isinstance(default, tuple):
        out = tuple(int(x) for x in v)
        if len(out) != len(default):
            raise ValueError(name)
        return out
    if isinstance(default, int):
        if isinstance(v, bool) or float(v) != int(float(v)):
            raise ValueError(name)
        return int(float(v))
    if isinstance(default, float):
        if isinstance(v, bool):
            raise TypeError(name)
        return float(v)
    if isinstance(default, str):
        if not isinstance(v, str):
            raise TypeError(name)
        return v
    return v
