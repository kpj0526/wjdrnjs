"""Offline self-test, also run against the packaged exe: `R2TargetHelper.exe --selftest out.json`.

It never touches the game or the real mouse. It checks:
- bundled sample image and Tk are present
- candidates are generated
- the nameplate check finds a synthetic nameplate and nothing in the real screenshot
- a dry-run cycle against a simulated screen
- settings can be saved and loaded in the data folder

Results go to a JSON file because a windowed exe has no console. Exit code 0 = all passed.
"""
from __future__ import annotations

import json
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

    def tk():
        import tkinter

        r = tkinter.Tk()
        r.withdraw()
        r.update()
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

    def settings_io():
        p = settings_path().with_name("settings.selftest.json")
        s = Settings(wait_interval=2.5)
        s.save(p)
        assert Settings.load(p).wait_interval == 2.5
        p.unlink()
        return str(data_dir())

    for name, fn in [("sample", sample), ("tk", tk), ("candidates", cands), ("detect", detect),
                     ("dry_cycle", dry_cycle), ("settings_io", settings_io)]:
        check(name, fn)
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
