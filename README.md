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

## Run from source

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m r2clicker                     # GUI
.venv\Scripts\python -m r2clicker --selftest out.json # offline self-test, no GUI and no clicks
.venv\Scripts\python -m pytest -q tests               # offline test suite
```

Requires Windows and Python 3.10 or newer (releases are built with 3.12).

## Usage

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

   Yellow numbered dots show the click order. Only the first *Max left clicks per cycle* dots
   are used each cycle. Red areas are HUD regions that are never clicked. Orange areas are
   ignored by the nameplate check.
4. Set the timing (all in seconds):

   | GUI label | Setting | Meaning |
   |---|---|---|
   | **Wait after right click -> next cycle** | `wait_interval` | Pause from the end of a cycle to the start of the next one. After a successful cycle, the end is its right click. After a failed cycle, it is the last check. The pause is held to within a few ms; Stop/F12 interrupts it immediately. |
   | Check nameplate after left click | `verify_delay` | First check this long after each left click. |
   | Give up nameplate check after | `verify_timeout` | Keep re-checking until this long after the click. |
   | Delay before right click | `right_click_delay` | Between a successful check and the right click. |

   Note that the time from one right click to the next is `wait_interval` *plus* the next
   cycle's own work: screenshot, scoring, and one check per attempt (about 0.1 s each, plus
   `verify_delay`).
5. Click **Save settings**. Settings are validated, and every problem is listed (for example
   "wait_interval must be a number in [0, 86400]" or "park point must be outside the ROI").
6. **Start** in dry run first and read the log. Untick *DRY RUN* only when ready.

**Stopping:** use the Stop button, hold **F12** (configurable), or push the cursor into the
top-left corner of the monitor it is on. This works on any monitor, including ones at
negative coordinates. Closing the window also stops the run.

## Safety and error handling

| Situation | Behaviour |
|---|---|
| Invalid settings (GUI or hand-edited `settings.json`) | Start is refused, and every problem is listed. |
| Corrupt or unreadable `settings.json`, or wrong value types | Defaults are used for those values, and a warning is logged. Saving is atomic (temp file + rename). |
| Game window not found, minimized, or zero-size | The run stops with that message; nothing is clicked. |
| Game window not in the foreground (live mode) | The run pauses without clicking and resumes when the game is active again. Focus lost mid-cycle ends that cycle at once. |
| Screenshot fails, or its size does not match the client (DPI scaling, window resized) | The run stops with a message that mentions DPI. The process is DPI-aware. |
| Frame size changes between baseline and check | That attempt counts as not selected. |
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
  - A staggered grid over the ROI.
  - Points inside the player circle or the HUD rectangles are removed.
  - Remaining points are ordered by `center_out`, `raster`, `snake` or `spiral`.
  - Bright, textured patches (likely a mob) are tried before flat floor.
  - Points near the last successful click are tried first.
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
- a headless GUI smoke test (form → settings, save, ROI drag)
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
  no live testing. Check that the game's terms allow this kind of tool.
- The window title filter is a substring match. Use a distinctive part of the game's title
  so that, for example, a browser tab with "R2" in its title is not picked first.
