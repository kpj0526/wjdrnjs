"""Helper process for capture integration tests: a plain top-level window in its own process.

Usage: python tests/winfixture.py TITLE X Y W H RRGGBB [--topmost] [--pattern]
Prints "ready <hwnd>" once mapped, then stays open until stdin is closed or 60 s pass.
--pattern draws a 4x4 checkerboard of two colours so a capture can be checked for exactness.
"""
import ctypes
import sys
import threading
import tkinter as tk


def main():
    title, x, y, w, h, color = sys.argv[1], *map(int, sys.argv[2:6]), sys.argv[6]
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    root = tk.Tk()
    root.title(title)
    root.geometry(f"{w}x{h}+{x}+{y}")
    if "--topmost" in sys.argv:
        root.attributes("-topmost", True)
    c = tk.Canvas(root, width=w, height=h, highlightthickness=0, bg="#" + color)
    c.pack(fill="both", expand=True)
    if "--pattern" in sys.argv:
        for i in range(4):
            for j in range(4):
                if (i + j) % 2:
                    c.create_rectangle(i * w // 4, j * h // 4, (i + 1) * w // 4, (j + 1) * h // 4,
                                       fill="#202060", outline="")
    root.update()
    hwnd = int(root.wm_frame(), 16)
    print(f"ready {hwnd}", flush=True)

    def watch_stdin():
        sys.stdin.read()
        root.after(0, root.destroy)

    threading.Thread(target=watch_stdin, daemon=True).start()
    root.after(60000, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
