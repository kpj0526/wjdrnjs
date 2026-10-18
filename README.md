# R2 target helper (wjdrnjs)

A small Windows desktop tool for the R2 mob-cluster screen. It left-clicks a sequence of
candidate points inside a search area (ROI) until it sees that a mob is selected: the white
nameplate **활동성 문지기** with green markers, which only appears after a left click. Then
it right-clicks, waits an exact interval, and repeats. It uses plain screenshot and pixel
rules, with no machine learning.

**DRY RUN is the default.** In dry run it only logs what it would click. Real clicks happen
only after you untick *DRY RUN* and confirm a dialog.

## Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m r2clicker          # opens the GUI
.venv\Scripts\python -m pytest -q tests    # offline validation (47 tests)
```

Requires Windows and Python 3.10 or newer (developed on 3.12). Dependencies are numpy, Pillow,
mss and pytest. If the game runs elevated, the tool must run elevated too, or Windows drops
its input.

## Usage

1. Set **Game window title contains** (default `R2`). The tool finds that window's client
   area. If no window matches, it falls back to the primary screen.
2. Click **Capture game screen**, or use **Load screenshot…** (a sample 1600x900 screenshot
   is shown at start).
3. Choose a drag mode, then drag on the preview:
   - **ROI**: the green rectangle, roughly over the mob cluster (default `350,130,1250,670`).
   - **player**: the red circle, which is never clicked.
   - **park point**: the blue X, where the cursor rests after each click so hover
     highlights are not mistaken for a selection.

   Yellow numbered dots show the click order. Only the first *Max left clicks per cycle*
   dots are used each cycle. Red areas are HUD regions that are never clicked. Orange areas
   are ignored by the selection check.
4. Set **Wait between cycles** (seconds, measured from the end of the cycle) and the limits,
   then click **Save settings** (writes `settings.json`).
5. **Start** in dry run first and read the log. Untick *DRY RUN* only when you are ready
   to click for real.

**Stopping:** use the Stop button, hold **F12** (configurable), or push the cursor into the
top-left screen corner. The run also stops by itself after *N* cycles in a row with no
selection.

## How it works (current behaviour)

- **Coordinates:** all settings use reference coordinates from the 1600x900 screenshot. At
  runtime they are scaled to the game's actual client size and offset by the window position
  (`geometry.py`). The process is DPI-aware, so mouse coordinates match screenshot pixels.
- **Candidates** (`candidates.py`):
  - A staggered grid over the ROI (step 55 px).
  - Points inside the player circle or the HUD rectangles are removed.
  - Remaining points are ordered by `center_out` (nearest the player first), `raster`,
    `snake` or `spiral`.
  - Optionally, bright, textured patches (likely a mob) are tried before flat floor.
  - Points near the last successful click are tried first.
- **One cycle** (`engine.py`):
  1. Park the cursor and take a baseline screenshot.
  2. For each candidate: left-click, park the cursor, wait *verify_delay*, then re-check
     until *verify_timeout*.
  3. On success: right-click the same point (or the park point), park the cursor, then wait
     the interval.
  4. On failure: the latest frame becomes the baseline for the next attempt.

  Every attempt is logged to the GUI and to `logs/run-YYYYMMDD.log`, with reference and
  screen coordinates, the score and the verification details.
- **Verification** (`vision.py`, about 80 ms per check):
  1. Search the ROI plus a margin, skipping HUD and ignore areas.
  2. Keep "white" pixels: bright and colourless, next to a dark outline, and (in `diff`
     mode) new since the baseline.
  3. Find a text-sized box (90x16) that has enough of these white pixels but is not a solid
     flash.
  4. Require enough green marker pixels around that box.
  5. Optional template mode: give a cropped PNG of the real nameplate and a binary
     cosine-similarity match is required instead.

## Offline validation

Everything is tested without the game, using `tests/fixtures/r2_cluster_1600x900.png` plus
synthetic nameplates (`r2clicker/fixtures.py`) and a `FakeGame` simulation. FakeGame is
selectable only near one mob, shows a hover label with no markers, and its nameplate drifts.

The tests cover:
- coordinate mapping, including offset, scaled and negative-monitor cases
- candidate generation, exclusions, ordering and stickiness
- detection: nameplate detected in 7 positions; no false positive on the real busy screenshot
  or on 1 to 30 px animation shifts; text without green markers rejected; scaled 1920x1080
  client; template mode
- the full loop: attempt count, right-click placement, max attempts, failed-cycle stop, exact
  wait interval, stop during a wait, and dry run sending no clicks

## Assumptions and limits

- **No real screenshot of a selected mob was available.** The nameplate look (white text
  with a dark outline, green marker on each side) is an assumption, drawn synthetically for
  the tests. Before running live:
  1. Take a real screenshot with a mob selected.
  2. Use **Load screenshot… → Test check on image** and tune *Min white text px*,
     *Min green marker px* and the green thresholds in `settings.json`.
  3. Ideally, save a crop of the nameplate as the template.
- If the game keeps the previous target's nameplate visible, the `diff` check will not see
  it as new. Deselect in the game, or use `absolute` mode.
- A nameplate that falls inside the orange ignore box over the player is not detected.
- Some games ignore `SendInput` or protect themselves against automation. That has not been
  tested against the live game. Check that the game's terms allow this kind of tool.
