# R2 target helper (wjdrnjs)

A small Windows desktop tool for the R2 mob-cluster screen. It left-clicks a sequence of
candidate points inside a search area (ROI) until it sees that a mob is selected: the white
nameplate **활동성 문지기** with green markers, which only appears after a left click. Then
it right-clicks, waits the interval you set, and repeats. It uses plain screenshot and pixel
rules, with no machine learning.

**DRY RUN is the default.** In dry run it only logs what it would click. Real clicks happen
only after you untick *DRY RUN* and confirm a dialog.

## Download and run (packaged)

1. Unzip `R2TargetHelper-<version>-win64.zip` anywhere you can write to.
2. Start `R2TargetHelper.exe` (keep the `_internal` folder next to it).
3. Read `README.txt` in the zip for a quick start.

The exe is not code-signed, so SmartScreen may warn ("More info" → "Run anyway").
No Python or other install is needed: everything the exe loads is in its folder.

### First run: minimal steps

1. Unzip the whole folder somewhere writable (Desktop, `D:\Tools`), not under
   `Program Files`. Start `R2TargetHelper.exe`. **DRY RUN** is ticked: nothing is clicked.
2. Start the game in a window (not minimized) at a 16:9 resolution, e.g. 1600x900 or
   1920x1080.
3. In the tool, set **Game window title contains** to a distinctive part of the game's title.
4. Click **Capture game screen**. If it fails, the message says why (window not found,
   covered, blank capture).
5. Drag the green **ROI** over the mob area. Optionally switch to **mob points** and click the
   mobs in the order to try them (otherwise the automatic grid is used).
6. Click **Save settings**, then **Preflight check**. Every line must be `ok`, `info` or
   `warn`; a `FAIL` line says what to fix, and Start is refused until it is fixed.
7. Click **Start** with DRY RUN still ticked. Read the log: the points it *would* click.
8. Only then untick DRY RUN and Start. The confirmation lists any preflight warnings, and the
   game window is brought to the front. Stop: **F12**, the cursor in the top-left screen
   corner, or **Stop**.

If the game runs as administrator, close the tool and start it with *Run as administrator*;
preflight reports this as `admin rights: FAIL` in live mode.

Updating: unzip the new version **over the old folder**. The zip never contains
`settings.json`, so your settings stay. If you unzip to a new folder instead, copy the old
`settings.json` into it.

Support: `R2TargetHelper.exe --preflight report.json` writes the same checks for the saved
settings to a file, without the GUI and without clicking. `--selftest out.json` checks the
installation offline.

## Run from source

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m r2clicker                     # GUI
.venv\Scripts\python -m r2clicker --selftest out.json # offline self-test, no GUI and no clicks
.venv\Scripts\python -m pytest -q tests               # offline test suite
```

Requires Windows 10 or newer and Python 3.10 or newer (releases are built with 3.12). The optional "Hide this window from screenshots" needs Windows 10 version 2004 or newer.

## Usage

Every button (Capture, Load, Test check, Save, Start) uses the values as currently typed. You
do not need to press Enter or *Apply* first. If a value is invalid, the button shows the
problem and does nothing, and the previous valid settings stay in effect.

1. Set **Game window title contains** (default `R2`). This tool's own window is never
   matched. If no window matches, or the window is minimized, capture and Start report an
   error. The tool never falls back to clicking the whole screen. Leave the field empty only
   to deliberately target the whole primary screen.
2. Click **Capture game screen** (or **Load screenshot...**; a sample 1600x900 screenshot is
   shown at start).
3. Choose a drag mode and drag on the preview:
   - **ROI**: the green rectangle over the mob cluster (default `350,130,1250,670`).
   - **player**: the red circle, which is never clicked.
   - **park point**: the blue X, where the cursor rests after every click so hover highlights
     are not mistaken for a selection. It must be outside the ROI.

   - **mob points**: each click on the preview adds a numbered manual candidate (see below).

   Yellow numbered dots show the click order. Only the first *Max left clicks per cycle* dots
   are used each cycle. Red areas are HUD regions that are never clicked. Orange areas are
   ignored by the nameplate check.

   **Manual mob points.** In *mob points* mode every click adds a point, numbered in click
   order (cyan circles; the list under the preview shows them). Clicking an existing point
   selects it; **Up**/**Down** reorder it, **Delete** removes it, **Clear all** empties the list.
   Points are stored as reference coordinates in `manual_points` (Save settings keeps them).
   While the list has at least one point, a run tries *only* these points, in list order (no
   pixel ranking, no "near last hit first"), capped by *Max left clicks per cycle*. With an
   empty list the automatic grid is used as before. Points outside the ROI, inside the player
   circle or on a HUD rectangle are not added. If a later ROI/avoid change makes a saved point
   unsafe, it is drawn as a red X, marked REFUSED in the list, and Start is refused until it is
   deleted or the settings are changed back. The usual mapping, focus, covered-point,
   dry-run and stop checks apply to manual points exactly as to grid points.
4. Set the timing (all in seconds):

   | GUI label | Setting | Meaning |
   |---|---|---|
   | **Wait after right click -> next cycle** | `wait_interval` | Pause from the end of a cycle to the start of the next one. After a successful cycle, the end is its right click. After a failed cycle, it is the last check. The pause is held to within a few ms; Stop/F12 interrupts it immediately. |
   | Check nameplate after left click | `verify_delay` | First check this long after each left click. |
   | Give up nameplate check after | `verify_timeout` | Keep re-checking until this long after the click. |
   | Delay before right click | `right_click_delay` | Between a successful check and the right click (default 0: at once). |
   | Rest on target before right click | `right_click_hover` | The cursor was parked after the left click; the right click glides back onto the point with real mouse-move input and rests this long first (default 0.03). |

   | Right button press time | `right_click_press` | How long the right button is held down (default 0.15; the left button 0.03). Raise it if the game ignores the right click. |

   Note that the time from one right click to the next is `wait_interval` *plus* the next
   cycle's own work: screenshot, scoring, and one check per attempt (about 0.1 s each, plus
   `verify_delay`).
5. Click **Save settings**. Settings are validated, and every problem is listed (for example
   "wait_interval must be a number in [0, 86400]" or "park point must be outside the ROI").
6. **Start** in dry run first and read the log. Untick *DRY RUN* only when ready.

**Stopping:** use the Stop button, hold **F12** (configurable), or push the cursor into the
top-left corner of the monitor it is on. This works on any monitor, including ones at
negative coordinates. Closing the window also stops the run.

## Capture: only the game's own pixels

Screen pixels would also include anything lying on top of the game. That includes this
helper's own window, which is how the preview used to show itself recursively inside the
capture. The **Capture backend** setting controls how frames are taken:

| Backend | How | When something overlaps the game |
|---|---|---|
| `auto` (default) | `window` first. If every `PrintWindow` mode is refused by Windows (each retried once) or returns a blank frame, falls back to `screen`, logs why once, and tries `window` again every 10 s. | as below |
| `window` | `PrintWindow` (fast `PW_CLIENTONLY`, or `+PW_RENDERFULLCONTENT` when the fast mode is refused or blank): the game window renders its own client area into memory. |\| PW_RENDERFULLCONTENT)`: the game window renders its own client area into memory. | Not included. The window's own pixels come back even when covered. If Windows refuses `PrintWindow` ("PrintWindow failed for the game window"), or the result is blank (some DirectX/OpenGL games and hardware-accelerated browsers), that is an error naming each mode's result, never a frame. |
| `screen` | Screen pixels via mss. | Before every grab, the windows above the game are checked. If one overlaps the client area, the grab fails and names that window. |

The helper's own window is shown normally and is **not** hidden from capture by default:
- **Window capture** (`auto`/`window`) never contains the helper anyway, so nothing needs
  hiding.
- **Screen capture** treats the helper like any other window. While the helper overlaps the
  game, the grab fails with a message naming the helper; it never returns a frame containing
  the helper. Move the helper off the game when using `screen`.

**Hide this window from screenshots** (opt-in, Windows 10 2004+) applies
`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, so the helper may overlap the game even
with `screen` capture. Use it only if you need that:
- On some PCs it also makes the window itself black, including its taskbar preview.
- Remote desktop and streaming tools (RDP, AnyDesk, TeamViewer, Discord/OBS) always show an
  excluded window as black or invisible.

To keep it from locking you out:
- When you tick it, a separate dialog asks whether the window is still shown normally. Any
  answer except **Yes** reverts it.
- It is ignored in Remote Desktop sessions (checked once at startup).
- Settings files from the previous release stored `true` here as the old default, not as a
  choice. They are migrated to off automatically.
- Last resort: start `R2TargetHelper.exe --show-window`. It turns the setting off for that
  session; save to keep it off.

The preview button and the running loop share the same capture object, so both follow the
same rules.

**Speed.** Measured on this development PC with a 1600x900 window at 60 Hz:

| Step | Median |
|---|---|
| Window capture | **11 ms**. The fast `PrintWindow` mode (`PW_CLIENTONLY`) is used whenever it returns real content. The slower full-content mode (one display frame, ~17 ms) is used only for windows whose fast mode is blank, such as DirectX. The working mode is remembered per window, so each steady-state grab is one call. |
| Screen capture | 17–30 ms (the old path, unchanged) |
| Occlusion check (screen backend only) | ~0.01 ms |
| Nameplate check | ~120 ms. This is the dominant cost and is unchanged. |

A failed `PrintWindow` call is retried once, immediately. No sleeps were added to the capture
path. Monitor enumeration, window placement and the remote-session check run once at
startup, never in the capture loop.

During a live run, each click point is checked with `WindowFromPoint` before clicking. If
the helper or any other window covers that point, the point is skipped and logged. If the
right-click point is covered, that cycle is abandoned without a right click.

## The helper window

At startup the window is fitted to the screen and brought to the front:
- **Size:** shrunk to fit the monitor's work area. The settings column scrolls, so laptops
  such as 1366x768 still show everything.
- **Position:** centred on the primary monitor. If a position was saved at the last close,
  it is reused only if the title bar is reachable on a monitor that exists now (including
  monitors at negative coordinates); otherwise the window is centred again. The window is
  always pulled fully inside that monitor.
- **Bringing to front:** de-minimize, raise, briefly topmost (400 ms) and focus. Each step is
  optional; if one fails, startup continues.

Closing the window saves only its geometry (`window_geometry` in `settings.json`), never
unsaved form edits. If startup itself fails, the error is written to `startup-error.log` in
the data folder and shown in a message box. A windowed exe has no console, so otherwise a
crash would look like "the process runs but no window".

## Safety and error handling

| Situation | Behaviour |
|---|---|
| Invalid settings (GUI or hand-edited `settings.json`) | Start is refused, and every problem is listed. |
| Any preflight `FAIL` (window, DPI, client size, capture, candidates, admin rights in live mode) | Start is refused before any mouse input is created; the dialog and log say what to fix. |
| Corrupt or unreadable `settings.json`, or wrong value types | Defaults are used for those values, and a warning is logged. An unreadable file is first copied to `settings.json.unreadable`. Saving is atomic (temp file + rename). Keys written by a newer release are kept on save. |
| Captured frame is blank (black/one colour) | Preflight fails; during a run the run stops before clicking. |
| Game window not found, minimized, or zero-size | The run stops with that message; nothing is clicked. |
| Game window not in the foreground (live mode) | The run pauses without clicking and resumes when the game is active again. Focus lost mid-cycle ends that cycle at once. |
| Screenshot fails, or its size does not match the client (DPI scaling, window resized) | The run stops with a message that mentions DPI. The process is DPI-aware. |
| Frame size changes between baseline and check | That attempt counts as not selected. |
| Window capture blank (hardware rendering) | `window` backend: error naming the cause. `auto`: falls back to `screen` (still occlusion-checked). |
| Another window, or the helper, overlaps the game (`screen` capture) | The capture fails and names the window, so its pixels never reach the check. |
| A click point is covered by another window (live) | That point is not clicked. |
| `SendInput` blocked (game running as administrator) | The run stops with "run this tool as administrator too". |
| Any unexpected error | The run stops, the traceback is logged, and both mouse buttons are released. A button-up is always sent after a button-down. |
| A click point would land outside the game client | It is skipped and logged. |
| The safety watchdog itself fails | The run stops (safety is never silently disabled). |
| N cycles in a row without a selection | The run stops (`max_consecutive_failed_cycles`, default 3). |
| Dry run on, but a live mouse is passed in | The live mouse is replaced with the recorder; no input is sent. |
| Live mode with neither a hotkey nor the corner failsafe | Rejected by validation. |
| Template file missing, unreadable, or without white text | Validation error, or a fallback to the box search with a warning. |

## Files and folders

| | From source | Packaged exe |
|---|---|---|
| Settings | `settings.json` in the repo root | `settings.json` next to the exe; if that folder is not writable, `%LOCALAPPDATA%\R2TargetHelper\` |
| Log | `logs\r2helper.log` (rotates at 2 MB, 3 backups) | the same, under the data folder |
| Failure screenshots (optional) | `logs\shots\` | the same |

The `R2_HELPER_HOME` environment variable overrides the data folder. **Open data folder** in
the GUI shows where it is. The release zip ships `settings.example.json` but never
`settings.json`, so unpacking an update does not overwrite your settings.

## How it works

- **Coordinates:** all settings use reference coordinates from the 1600x900 screenshot. At
  runtime they are scaled to the game's actual client size and offset by the window position
  (`geometry.py`).
- **Candidates** (`candidates.py`):
  - Manual points, when there are any, replace everything below and keep their order.
  - A staggered grid over the ROI.
  - Points inside the player circle or the HUD rectangles are removed.
  - Remaining points are ordered by `center_out`, `raster`, `snake` or `spiral`.
  - Bright, textured patches (likely a mob) are tried before flat floor.
  - Points near the last successful click are tried first.
- **Preflight** (`preflight.py`), before every Start and on **Preflight check**: settings and
  manual points, game window, DPI awareness and monitor scaling, client size/aspect, one
  capture (size, not blank), candidates inside the client, administrator rights of the game
  vs. this tool, DRY RUN/LIVE. Any `FAIL` refuses the run.
- **One cycle** (`engine.py`):
  1. Park the cursor and take a baseline screenshot.
  2. For each candidate: left-click, park, check.
  3. On success: right-click, park, then wait `wait_interval`.
- **Check** (`vision.py`, about 100 ms):
  1. Look in the ROI plus a margin, skipping HUD and ignore areas.
  2. Keep "white" pixels: bright and colourless, next to a dark outline, new since the
     baseline (`diff` mode), and not part of a long straight run (bars and frame rims are
     removed).
  3. Find a text-sized box with enough of these pixels that is not a solid blob.
  4. Require enough green marker pixels around it.
  5. Optional: a cropped PNG of the real nameplate enables template matching.

## Tests (offline only)

`tests/` uses the sample screenshot (`assets/sample_1600x900.png`), synthetic nameplates
(`r2clicker/fixtures.py`) and a `FakeGame`. FakeGame can only be selected near one mob, shows
a hover label without markers, and its nameplate drifts. The tests cover:

- coordinate mapping (offset, scaled and negative monitors)
- candidates and their ordering
- detection: hits; misses on motion, flashes, outlined boxes, green-only changes and HUD
  text; template mode
- the full loop: attempt count, wait interval, Stop and F12 (both mid-cycle and mid-wait),
  the per-monitor corner failsafe, window and capture errors, focus loss, mouse release
  after errors, the dry-run guard
- settings validation, load and save
- data paths for source, portable and read-only installs
- a headless GUI smoke test (form → settings, save, ROI drag, manual mob points: add,
  refuse, select, reorder, delete, clear, save/load, Start), including that every button
  uses the values as typed without Enter/Apply. Its windows stay withdrawn
  (`R2_HIDE_TEST_WINDOWS=1`); the two tests that check a visible window are desktop tests
- manual points: settings round trip, validation, order, mapping, covered points, focus loss
- preflight: every check with faked window/capture/Win32 probes, the GUI gate (no live input
  or prompt before it passes), `--preflight`, blank frames, unknown keys and unreadable
  settings files
- capture backend selection and occlusion logic (stubbed Win32 calls)
- desktop capture tests with real windows. A patterned "game" window runs in a separate
  process, with an external topmost window and the helper GUI over it. The tests check that:
  - preview and run-time captures contain only the target's pixels, on all three backends
  - `screen` capture refuses while an external window covers the target
  - the click guard sees covering windows

  These briefly show small windows; set `R2_SKIP_DESKTOP_TESTS=1` to skip them, the two
  visible-window GUI tests, and the self-test's PrintWindow step (`R2_SELFTEST_NO_WINDOW=1`,
  also used by `build.ps1` when that variable is set).
- source hygiene: UTF-8 with no U+FFFD, and ASCII-only GUI strings

None of the tests touch the game or the real mouse.

## Building the release zip

```powershell
build.bat                       # or: powershell -ExecutionPolicy Bypass -File packaging\build.ps1
build.bat -SkipTests -KeepVenv  # faster rebuild
```

`packaging/build.ps1` runs these steps:
1. Create a fresh `.build-venv` from the fully pinned `requirements-build.txt` (PyInstaller
   6.22.3, numpy 2.5.4, Pillow 13.0.0, mss 10.2.0).
2. Set `PYTHONHASHSEED=0` and `SOURCE_DATE_EPOCH` = the last commit time.
3. Run the tests.
4. Build with PyInstaller (`packaging/R2TargetHelper.spec`, one-folder, windowed, no UPX).
5. Run `R2TargetHelper.exe --selftest` against an isolated data folder. The build fails if
   the self-test fails or if a `settings.json` ended up in the output.
6. Zip the folder and write a SHA256 file.

Output:

```
dist\R2TargetHelper\                         R2TargetHelper.exe, _internal\, README.txt,
                                             README_FULL.md, settings.example.json
dist\R2TargetHelper-<version>-win64.zip      the download (~30 MB)
dist\R2TargetHelper-<version>-win64.zip.sha256
build\selftest.json                          the exe's self-test result
```

Byte-identical zips across machines are not guaranteed: PyInstaller output and zip
timestamps vary. The inputs are pinned so that rebuilds are functionally identical.

## Assumptions and limits

- **No real screenshot of a selected mob was available.** The nameplate look (white text
  with a dark outline, green markers) is an assumption, drawn synthetically for the tests.
  Before running live:
  1. Take a real screenshot with a mob selected.
  2. Use **Load screenshot... → Test check on image** and tune *Min white text px*,
     *Min green marker px* and the colour thresholds.
  3. Ideally, save a crop of the nameplate as the template.
- If the game keeps the previous target's nameplate visible, `diff` mode will not see it as
  new. Deselect in the game, or use `absolute` mode.
- A nameplate inside the orange ignore box over the player is not detected (a deliberate
  trade-off against skill-flash false positives).
- Whether the game accepts `SendInput` clicks, or blocks automation, is untested; there was
  no live testing. Check that the game's terms allow this kind of tool. Preflight can only
  detect the administrator-rights case; an anti-cheat that silently drops input is not
  detectable before a run.
- Whether `PrintWindow` can read the R2 client is unknown until it is tried on the real game.
  If the preview reports `[screen capture]`, the game is hardware-rendered. Then keep the
  game uncovered, including by the helper, or the capture fails safely.
- `PrintWindow` asks the game to redraw into memory on every grab. With some games that costs
  a few ms or causes flicker; if so, choose `screen`.
- The nameplate check is calibrated on three real screenshots from the customer's PC
  (`tests/real/`): nothing selected, after a left click (white "황동석 문지기" with a green HP
  bar above it), and after left + right click. The real nameplate has ~320 white px in its
  text box, a screen without one up to ~60, so *Min white text px* is 150 and the mode is
  `absolute` (a nameplate that stays visible still counts). A corpse nameplate without the
  green bar does not count; this has not been checked against a real corpse screenshot.
- **The cursor stays on the mob** from the left click to the right click (customer log: with the
  cursor moved away while checking and brought back for the right click, R2 ignored two right
  clicks in a row, while a right click with the cursor resting on the mob worked). Before the
  right press the cursor is nudged 1 px and back with real mouse input and rests
  *Rest on target before right click* (0.1 s). *Move cursor away while checking* restores the
  old behaviour.
- **Test right click (3 s)** sends one real right click where the mouse is 3 s later (no cursor
  movement), with *Right click input API* (`sendinput` or the older `mouse_event`, which a
  PowerShell test uses) and *Right button press time*, then logs whether the target panel appeared.
- **Right click confirmation:** a right click that registers shows the target panel at the
  bottom centre (dark box, mob name, green HP dots). After the right click the tool looks for
  it for *Wait for target panel* seconds and right clicks again (*Right click again if no
  panel*, default once) if it does not appear. The log says `right click confirmed` or
  `right click NOT confirmed`. Turn it off with *Confirm right click*.
- The nameplate must be within *Nameplate max distance from click* (default 250 reference
  px) of the clicked point. Another mob's or player's nameplate elsewhere on screen does not
  count. Set it to 0 to accept a nameplate anywhere (the behaviour before 0.3.0).
- The window title filter is a substring match. Use a distinctive part of the game's title
  so that, for example, a browser tab with "R2" in its title is not picked first.
