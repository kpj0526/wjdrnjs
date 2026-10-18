"""Settings model.

All coordinates are *reference* coordinates in the 1600x900 game client the
screenshots were taken from. At runtime they are scaled to the real client
size (see geometry.py), so the same settings work at other resolutions.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

REF_W, REF_H = 1600, 900

Rect = tuple[int, int, int, int]  # x1, y1, x2, y2 (x2/y2 exclusive)

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

    # --- timing (seconds) ---
    wait_interval: float = 5.0        # exact wait between cycles (after right click)
    verify_delay: float = 0.25        # after left click, before verification screenshot
    verify_timeout: float = 0.6       # keep re-checking until this long after the click
    settle_delay: float = 0.08        # after moving cursor off, before the baseline shot
    right_click_delay: float = 0.10   # between successful verification and right click

    # --- limits ---
    max_attempts: int = 30            # left clicks per cycle before giving up the cycle
    max_cycles: int = 0               # 0 = unlimited
    max_consecutive_failed_cycles: int = 3  # stop the run after this many empty cycles

    # --- clicking ---
    dry_run: bool = True
    park_point: tuple[int, int] = (1480, 300)  # cursor rest point (empty floor, off ROI)
    right_click_target: str = "same"  # same | park  (where the right click lands)

    # --- verification (nameplate: white text + green markers) ---
    verify_mode: str = "diff"         # diff = only pixels new since baseline; absolute = as-is
    verify_margin: int = 80           # verify area = ROI grown by this (nameplate floats above mob)
    white_min: int = 215              # min channel value for "white"
    white_max_spread: int = 30        # max(R,G,B)-min(R,G,B) for "white"
    green_min_g: int = 150
    green_min_delta: int = 60         # G-R and G-B both at least this
    diff_min: int = 40                # per-pixel change needed to count as new (diff mode)
    require_outline: bool = True      # text pixels must touch dark outline/background (rejects glows)
    outline_dark_max: int = 100       # mean RGB at or below this counts as dark
    outline_radius: int = 2
    verify_ignore_rects: list[Rect] = field(default_factory=lambda: [(735, 345, 865, 480)])  # player HP bar + skill flash
    plate_w: int = 90                 # expected nameplate text box (reference px)
    plate_h: int = 16
    plate_min_white: int = 60         # min white pixels inside the best text box
    marker_search: int = 40           # look for green this far around the text box
    marker_min_green: int = 12        # min green pixels around the text box
    template_path: str = ""           # optional cropped nameplate PNG for template matching
    template_min_score: float = 0.55

    # --- safety ---
    emergency_hotkey: str = "F12"
    corner_failsafe: bool = True      # cursor in the top-left screen corner stops the run

    # --- logging ---
    log_dir: str = "logs"
    save_failure_shots: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        p = Path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        s = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            v = data[f.name]
            default = getattr(s, f.name)
            if isinstance(default, tuple):
                v = tuple(v)
            elif f.name in ("ui_rects", "verify_ignore_rects"):
                v = [tuple(r) for r in v]
            setattr(s, f.name, v)
        return s

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
