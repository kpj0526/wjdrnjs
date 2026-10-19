# R2 target helper (wjdrnjs)

A small Windows auto clicker for R2. You pick click points on a capture of the game. Every
cycle it goes through the points in order and gives each one a **left click and right after
it a right click**, then waits the interval you set and starts again. Nothing on screen is
checked: no colours, no nameplates, no search area.

**DRY RUN is the default.** In dry run it only logs what it would click. Real clicks happen
only after you untick *DRY RUN* and confirm a dialog.

## Download and run (packaged)

1. Unzip `R2TargetHelper-<version>-win64.zip` anywhere you can write to (Desktop, `D:\Tools`),
   not under `Program Files`. Keep the `_internal` folder next to the exe.
2. If the game runs as administrator, start `R2TargetHelper.exe` with *Run as administrator*
   too, or Windows drops its clicks (preflight reports `admin rights: FAIL`).
3. Start the game in a window (not minimized), at a 16:9 resolution such as 1600x900.
4. Set **Game window title contains** to part of the game's title, then **Capture game screen**.
5. Click the preview where the tool should click. Points are numbered in click order; click a
   point to select it, then **Up**/**Down**/**Delete**, or **Clear all**.
6. Set the timing, **Save settings**, then **Preflight check**.
7. **Start** with DRY RUN ticked and read the log. Then untick DRY RUN and Start. The game
   window is brought to the front automatically; clicks are only sent while it is active.

Stop: hold **F12**, push the cursor into the top-left corner of its monitor, or **Stop**.

The exe is not code-signed, so SmartScreen may warn ("More info" → "Run anyway").

Updating: unzip the new version **over the old folder**. The zip never contains
`settings.json`, so your settings and click points stay. Settings from 0.1.x keep their click
points and wait time; their search-area and nameplate settings are ignored and dropped on the
next save.

Support: `R2TargetHelper.exe --preflight report.json` writes the preflight checks for the
saved settings to a file, without the GUI and without clicking. `--selftest out.json` checks
the installation offline.

## Timing

| GUI label | Setting | Default | Meaning |
|---|---|---|---|
| Wait after the last point -> next cycle | `wait_interval` | 5.0 | From the last right click of a cycle to the first left click of the next. |
| Left click -> right click | `right_click_delay` | 0 | Gap between a point's left and right click. |
| Pause between points | `point_delay` | 0.1 | From one point's right click to the next point's left click. |
| Rest on point before right press | `right_click_hover` | 0.03 | The right click moves onto the point with real mouse-move input and waits this long before pressing. |
| Hold right button | `right_click_hold` | 0.1 | How long the right button stays down. Raise it (e.g. 0.3) if the game ignores the right click. |
| Max cycles | `max_cycles` | 0 | 0 = until stopped. |

The left click holds its button 30 ms. All times are in seconds; Stop and F12 interrupt any wait.

## Run from source

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m r2clicker                     # GUI
.venv\Scripts\python -m r2clicker --selftest out.json # offline self-test, no GUI and no clicks
.venv\Scripts\python -m pytest -q tests               # offline test suite
```

Requires Windows 10 or newer and Python 3.10 or newer (releases are built with 3.12).

## Preview capture

The capture is only used to show the game on the preview so you can place the points; a run
never takes screenshots. Backends: `window` reads the game's own pixels with `PrintWindow`,
`screen` copies the screen and refuses while another window (or this helper) covers the game,
and `auto` (default) uses `window` and falls back to `screen` when Windows refuses
`PrintWindow` or returns a blank image. **Load screenshot...** uses a saved 1600x900 image instead.

Points are stored in reference coordinates of a 1600x900 client and scaled to the real client
size and position at every cycle, so they follow the window when it moves or is resized.

## The helper window

At startup the window is fitted into a monitor's work area (the settings column scrolls) and
brought to the front. A saved position is reused only if it is on a monitor that exists now.
Closing the window saves only its geometry. If startup fails, the error is written to
`startup-error.log` in the data folder. If the window looks black, start it once with
`--show-window` and Save settings (this turns off the optional "Hide this window from screenshots").

## Preflight and safety

Preflight runs before every Start and on **Preflight check**: settings and click points, game
window, DPI awareness, client size, points inside the client, administrator rights. Any `FAIL`
refuses the start before any mouse input exists.

| Situation | Behaviour |
|---|---|
| No click points, or a point outside the game client | Start is refused; bad points are drawn as a red X. |
| Game window not found, minimized, or zero-size | The run stops with that message; nothing is clicked. |
| Game window not in the foreground (live) | The run pauses and resumes when the game is active again. Focus lost mid-cycle ends that cycle at once. |
| A point is covered by another window, e.g. this helper (live) | That point is not clicked. |
| `SendInput` blocked (game running as administrator) | The run stops with "run this tool as administrator too". |
| Any unexpected error | The run stops, the traceback is logged, and both mouse buttons are released. |
| The safety watchdog itself fails | The run stops (safety is never silently disabled). |
| Dry run on, but a live mouse is passed in | The live mouse is replaced with the recorder. |
| Live mode with neither a hotkey nor the corner failsafe | Rejected by validation. |
| Corrupt `settings.json` or wrong value types | Defaults for those values and a warning; an unreadable file is first copied to `settings.json.unreadable`. Saving is atomic. |

## Files and folders

| | From source | Packaged exe |
|---|---|---|
| Settings | `settings.json` in the repo root | `settings.json` next to the exe; if that folder is not writable, `%LOCALAPPDATA%\R2TargetHelper\` |
| Log | `logs\r2helper.log` (rotates at 2 MB, 3 backups) | the same, under the data folder |

The `R2_HELPER_HOME` environment variable overrides the data folder. **Open data folder** shows it.

## Tests (offline only)

`tests/` covers the click loop (order, left then right on every point, the three delays, the
wait interval, max cycles, Stop/F12 mid-cycle and mid-wait, the corner failsafe, focus loss,
covered points, window errors, blocked input, mouse release, the dry-run guard), the Win32
mouse input against a recording `user32`, settings (validation, load/save, files from 0.1.x),
preflight, capture backends and occlusion, data paths, the headless GUI, and source hygiene.
Desktop capture tests briefly show small windows; set `R2_SKIP_DESKTOP_TESTS=1` to skip them.
None of the tests touch the game or the real mouse.

## Building the release zip

```powershell
build.bat                       # or: powershell -ExecutionPolicy Bypass -File packaging\build.ps1
build.bat -SkipTests -KeepVenv  # faster rebuild
```

`packaging/build.ps1` creates a fresh `.build-venv` from the pinned `requirements-build.txt`,
runs the tests, builds with PyInstaller (one folder, windowed), runs the exe's `--selftest`,
and writes `dist\R2TargetHelper-<version>-win64.zip` plus its SHA256.

## Limits

- Not tested against the live game. Whether the game accepts `SendInput` clicks, or an
  anti-cheat drops them, can only be seen on the customer's PC. Check that the game's terms
  allow this kind of tool.
- The tool clicks blindly: if nothing is at a point, the click lands on the floor.
- The window title filter is a substring match; use a distinctive part of the game's title.
