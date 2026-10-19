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
SETTINGS_VERSION = 3  # 2: hide_helper_from_capture is an explicit opt-in; 3: plain auto clicker

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 (x2/y2 exclusive)
Point = tuple[int, int]
MAX_MANUAL_POINTS = 200

# Settings of the old nameplate-checking releases. They mean nothing now and are dropped on load.
REMOVED_KEYS = frozenset({
    "roi", "grid_step", "order", "stagger", "player_center", "player_radius", "ui_rects",
    "prefer_mob_pixels", "mob_score_min", "sticky_radius", "verify_delay", "verify_timeout",
    "settle_delay", "max_attempts", "max_consecutive_failed_cycles", "park_point", "right_click_target",
    "verify_mode", "verify_margin", "white_min", "white_max_spread", "green_min_g", "green_min_delta",
    "diff_min", "require_outline", "outline_dark_max", "outline_radius", "max_stroke_run",
    "verify_ignore_rects", "plate_w", "plate_h", "plate_min_white", "marker_search", "marker_min_green",
    "template_path", "template_min_score", "save_failure_shots",
})


@dataclass
class Settings:
    """Auto clicker: every cycle clicks the picked points in order, each with a left click and right
    after it a right click, then waits wait_interval. Nothing on screen is checked."""

    # --- window / coordinate mapping ---
    window_title: str = "R2"          # substring of the game window title; "" = whole primary screen
    ref_w: int = REF_W
    ref_h: int = REF_H
    capture_backend: str = "auto"     # preview only: auto | window (PrintWindow) | screen (mss + occlusion check)

    # --- click points (reference coordinates), clicked in this order every cycle ---
    manual_points: list[Point] = field(default_factory=list)

    # --- timing (seconds) ---
    wait_interval: float = 5.0        # from the last right click of a cycle to the first left click of the next
    right_click_delay: float = 0.0    # between a point's left click and its right click
    point_delay: float = 0.1          # between one point's right click and the next point's left click
    right_click_hover: float = 0.03   # cursor rests on the point this long before the right press
    right_click_hold: float = 0.1     # right button held this long (games polling per frame miss shorter)

    # --- limits ---
    max_cycles: int = 0               # 0 = unlimited

    # --- clicking ---
    dry_run: bool = True

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
        if REMOVED_KEYS & data.keys():
            s.load_notes.append("old search-area/nameplate settings ignored: this version just clicks "
                                "the click points (they are kept)")
        version = data.get("settings_version") if isinstance(data.get("settings_version"), int) else 1
        # before version 3, right_click_delay was the pause after a nameplate check, not the gap
        # between left and right click: the new default (right away) applies instead
        skip = {"right_click_delay"} if version < 3 else set()
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

        include_manual=False leaves out manual_point_problems(): the GUI uses that so the form can
        be applied and saved while the point list is still empty.
        """
        from .capture import BACKENDS
        from .winput import VK_CODES

        e: list[str] = []
        if self.ref_w <= 0 or self.ref_h <= 0:
            e.append("reference size must be positive")
        rng = {
            "wait_interval": (0, 86400), "right_click_delay": (0, 10), "point_delay": (0, 60),
            "right_click_hover": (0, 2), "right_click_hold": (0.01, 2), "max_cycles": (0, 10**9),
        }
        for name, (lo, hi) in rng.items():
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (lo <= v <= hi):
                e.append(f"{name} must be a number in [{lo}, {hi}] (got {v!r})")
        if self.capture_backend not in BACKENDS:
            e.append(f"capture_backend must be one of {', '.join(BACKENDS)}")
        if self.emergency_hotkey and self.emergency_hotkey.upper() not in VK_CODES:
            e.append(f"emergency_hotkey must be one of {', '.join(VK_CODES)}")
        if not self.dry_run and not self.emergency_hotkey and not self.corner_failsafe:
            e.append("live mode needs an emergency hotkey or the corner failsafe")
        if include_manual:
            e.extend(self.manual_point_problems())
        return e

    def manual_point_problems(self) -> list[str]:
        """No points, too many, or points outside the game client."""
        if not self.manual_points:
            return ["no click points: choose 'click points' and click the preview to add them"]
        e: list[str] = []
        if len(self.manual_points) > MAX_MANUAL_POINTS:
            e.append(f"at most {MAX_MANUAL_POINTS} click points (got {len(self.manual_points)})")
        for i, p in enumerate(self.manual_points, 1):
            why = point_reason(p, self)
            if why:
                e.append(f"click point {i} {tuple(p)}: {why}")
        return e


def point_reason(p, s: Settings) -> str | None:
    """Why a click point cannot be used, or None."""
    if len(p) != 2:
        return "needs x,y"
    if not (0 <= p[0] < s.ref_w and 0 <= p[1] < s.ref_h):
        return f"outside the {s.ref_w}x{s.ref_h} game client"
    return None


_INTERNAL = ("load_warnings", "load_notes", "extra")


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
