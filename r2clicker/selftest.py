"""Offline self-test, also run against the packaged exe: `R2TargetHelper.exe --selftest out.json`.

It never touches the game or the real mouse. It checks:
- bundled sample image and Tk are present; PrintWindow capture and capture exclusion work
- candidates are generated
- the nameplate check finds a synthetic nameplate and nothing in the real screenshot
- a dry-run cycle against a simulated screen, also with manual points
- the preflight refuses a blank frame and an unsafe manual point (simulated game window)
- settings can be saved and loaded in the data folder, and the self-test never creates or
  changes the user's settings.json

Results go to a JSON file because a windowed exe has no console. Exit code 0 = all passed.
R2_SELFTEST_NO_WINDOW=1 skips the one step that shows a small window (PrintWindow needs a
mapped window); Tk itself is still started, hidden.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def run_checks() -> dict:
    import numpy as np
    from PIL import Image

    from . import __version__
    from .candidates import build_candidates
    from .config import Settings
    from .engine import Bot
    from .fixtures import frame_with_nameplate
    from .geometry import Mapping
    from .paths import data_dir, is_frozen, sample_image, settings_path
    from .vision import verify
    from .winput import DryRunMouse

    checks: dict[str, str] = {}

    def check(name, fn):
        try:
            out = fn()
            checks[name] = "ok" + (f": {out}" if out else "")
        except Exception as e:
            checks[name] = f"FAIL: {e!r}\n{traceback.format_exc(limit=3)}"

    state: dict = {}

    def sample():
        p = sample_image()
        assert p, "bundled sample image missing"
        state["img"] = Image.open(p).convert("RGB")
        assert state["img"].size == (1600, 900)
        return p.name

    def tk_and_window_capture():
        """Tk works, PrintWindow reads a window's own pixels, and capture exclusion is available."""
        import tkinter

        from .capture import Grabber, print_window

        r = tkinter.Tk()
        if os.environ.get("R2_SELFTEST_NO_WINDOW") == "1":
            r.withdraw()  # before the first update: the window is never mapped
            r.update()
            r.destroy()
            return "Tk ok; window capture skipped (R2_SELFTEST_NO_WINDOW=1)"
        try:
            r.title("R2 selftest")
            r.geometry("120x80+40+40")
            tkinter.Canvas(r, bg="#c0c000", width=120, height=80, highlightthickness=0).pack()
            r.update()
            hwnd = int(r.wm_frame(), 16)
            if sys.platform != "win32":
                return "skipped (not Windows)"
            client = int(r.winfo_id())  # Tk's client window inside the frame
            w, h = r.winfo_width(), r.winfo_height()
            img = None
            for _ in range(20):
                r.update()
                img = print_window(client, w, h)
                if img[h // 2, w // 2].tolist() == [192, 192, 0]:
                    break
                time.sleep(0.05)
            assert img is not None and img[h // 2, w // 2].tolist() == [192, 192, 0], img[h // 2, w // 2]
            excluded = Grabber().exclude_window(hwnd)
            return f"PrintWindow ok, exclude-from-capture {'ok' if excluded else 'UNSUPPORTED'}"
        finally:
            r.destroy()

    m = Mapping(0, 0, 1600, 900)

    def cands():
        c = build_candidates(Settings(), np.asarray(state["img"]), m)
        assert len(c) > 50
        return f"{len(c)} candidates"

    def detect():
        s = Settings()
        base = np.asarray(state["img"])
        hit = verify(frame_with_nameplate(state["img"], (700, 250)), s, m, before=base)
        miss = verify(base, Settings(verify_mode="absolute"), m)
        assert hit.ok, hit.summary()
        assert not miss.ok, miss.summary()
        return f"hit {hit.ms:.0f} ms"

    def dry_cycle():
        mouse = DryRunMouse()
        s = Settings(settle_delay=0, verify_delay=0, verify_timeout=0, max_attempts=3, max_cycles=1,
                     emergency_hotkey="", corner_failsafe=False)
        frame = np.asarray(state["img"])
        bot = Bot(s, lambda _m: frame, mouse, mapping_fn=lambda: (m, "selftest"))
        bot.run()
        lefts = [a for a in mouse.actions if a[0] == "left"]
        assert len(lefts) == 3, mouse.actions
        return bot.stop_reason

    def manual_cycle():
        mouse = DryRunMouse()
        pts = [(600, 300), (1000, 250)]
        s = Settings(settle_delay=0, verify_delay=0, verify_timeout=0, max_cycles=1, emergency_hotkey="",
                     corner_failsafe=False, manual_points=pts)
        frame = np.asarray(state["img"])
        Bot(s, lambda _m: frame, mouse, mapping_fn=lambda: (m, "selftest")).run()
        lefts = [a[1:] for a in mouse.actions if a[0] == "left"]
        assert lefts == pts, lefts
        return f"{len(lefts)} manual points recorded in order (dry run, no clicks)"

    def preflight():
        from .preflight import run_preflight

        frame = np.asarray(state["img"])
        fake = dict(resolve=lambda t, w, h: (m, "selftest window"), dpi_awareness=lambda: 2,
                    me_elevated=lambda: False, game_elevated=lambda h: False)
        good = run_preflight(Settings(), lambda _m: frame, live=False, **fake)
        assert good.ok, good.text()
        blank = run_preflight(Settings(), lambda _m: np.zeros_like(frame), live=True, **fake)
        assert not blank.ok and blank.failures[0].name == "capture", blank.text()
        unsafe = run_preflight(Settings(manual_points=[(800, 440)]), lambda _m: frame, live=False, **fake)
        assert not unsafe.ok and unsafe.failures[0].name == "settings", unsafe.text()
        return f"{len(good.items)} checks"

    def dpi_awareness():
        """The real process: coordinates must be physical pixels, as the GUI sets up at start."""
        from .geometry import enable_dpi_awareness
        from .preflight import process_dpi_awareness

        enable_dpi_awareness()
        aw = process_dpi_awareness()
        if sys.platform == "win32":
            assert aw in (1, 2), f"DPI awareness is {aw} after enable_dpi_awareness()"
        return f"awareness {aw}"

    def settings_io():
        p = settings_path().with_name("settings.selftest.json")
        s = Settings(wait_interval=2.5)
        s.save(p)
        assert Settings.load(p).wait_interval == 2.5
        p.unlink()
        return str(data_dir())

    user_settings = settings_path()
    before = user_settings.read_bytes() if user_settings.exists() else None
    for name, fn in [("sample", sample), ("tk_and_window_capture", tk_and_window_capture), ("candidates", cands),
                     ("detect", detect), ("dry_cycle", dry_cycle), ("manual_cycle", manual_cycle),
                     ("preflight", preflight), ("dpi_awareness", dpi_awareness), ("settings_io", settings_io)]:
        check(name, fn)
    after = user_settings.read_bytes() if user_settings.exists() else None
    checks["settings_untouched"] = "ok" if after == before else f"FAIL: {user_settings} was created or changed"
    return {"version": __version__, "frozen": is_frozen(), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "checks": checks, "passed": all(v.startswith("ok") for v in checks.values())}


def main(out: str) -> int:
    try:
        result = run_checks()
    except Exception:
        result = {"passed": False, "error": traceback.format_exc()}
    Path(out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if sys.stdout:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("passed") else 1
