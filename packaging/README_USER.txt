R2 Target Helper - quick start
==============================

1. Unzip the whole folder anywhere you can write to (e.g. Desktop or D:\Tools).
   Keep R2TargetHelper.exe next to its _internal folder.
2. Start R2TargetHelper.exe. It opens in DRY RUN mode: it only logs what it would click.
3. Start the game, then in the tool:
   - "Game window title contains": part of the game window title (default R2).
   - "Capture game screen", then drag the green ROI over the mob cluster.
   - "Wait after right click -> next cycle (s)": the pause between cycles.
   - "Save settings".
4. Press Start in dry run and read the log. Untick DRY RUN only when ready.

Emergency stop: hold F12, or push the mouse into the top-left corner of the monitor,
or press Stop. Clicks are only sent while the game window is the active window.

If this window ever looks black (also in the taskbar preview), start it once with
  R2TargetHelper.exe --show-window
and press "Save settings". This turns off the optional "Hide this window from
screenshots", which some PCs and remote/streaming tools show as black.

Files:
  settings.json        your settings (created on first "Save settings")
  settings.example.json  default values for reference
  logs\r2helper.log    run log (rotates at 2 MB, 3 backups)
If the folder is not writable (e.g. under Program Files), settings and logs go to
%LOCALAPPDATA%\R2TargetHelper instead. "Open data folder" shows where.

If the game runs as administrator, run this tool as administrator too, or Windows
blocks its clicks (the log then says "SendInput was blocked").

Windows SmartScreen may warn about an unsigned app: "More info" -> "Run anyway".
See README_FULL.md for details and known limits.
