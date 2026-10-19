R2 Target Helper - quick start
==============================

This is a simple auto clicker: every cycle it left clicks and then right clicks each of your
click points, in order, then waits. It does not look at the screen.

1. Unzip the whole folder anywhere you can write to (e.g. Desktop or D:\Tools).
   Keep R2TargetHelper.exe next to its _internal folder.
2. If the game runs as administrator, right click R2TargetHelper.exe -> "Run as administrator".
   It opens in DRY RUN mode: it only logs what it would click.
3. Start the game in a window (not minimized), 16:9 resolution (e.g. 1600x900), then in the tool:
   - "Game window title contains": part of the game window title (default R2).
   - "Capture game screen".
   - Click the preview where it should click. Points are numbered in click order.
     Click a point to select it, then Up / Down / Delete, or Clear all.
   - Timing (seconds):
       "Wait after the last point -> next cycle"
       "Left click -> right click"        (0 = right away)
       "Pause between points"
   - "Save settings".
4. Press "Preflight check". Fix every FAIL line (Start is refused while any is left).
5. Press Start in dry run and read the log. Untick DRY RUN only when ready.
   The game window is brought to the front by itself; clicks only go to the game while it
   is the active window.

If the game ignores the right click, raise "Hold right button" (e.g. 0.3) and
"Rest on point before right press" (e.g. 0.1).

Updating: unzip the new version over the old folder. The zip has no settings.json,
so your settings and click points are kept. In a new folder, copy the old settings.json into it.
For support: R2TargetHelper.exe --preflight report.json  (checks only, never clicks).

Emergency stop: hold F12, or push the mouse into the top-left corner of the monitor,
or press Stop.

If this window ever looks black (also in the taskbar preview), start it once with
  R2TargetHelper.exe --show-window
and press "Save settings".

Files:
  settings.json        your settings (created on first "Save settings")
  settings.example.json  default values for reference
  logs\r2helper.log    run log (rotates at 2 MB, 3 backups)
If the folder is not writable (e.g. under Program Files), settings and logs go to
%LOCALAPPDATA%\R2TargetHelper instead. "Open data folder" shows where.

Windows SmartScreen may warn about an unsigned app: "More info" -> "Run anyway".
See README_FULL.md for details and known limits.
