"""Mouse output via Win32 SendInput, plus a dry-run backend that only records."""
from __future__ import annotations

import ctypes
import sys
import time

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000


class DryRunMouse:
    """Records actions instead of performing them. Used by default and in tests."""

    live = False

    def __init__(self) -> None:
        self.actions: list[tuple] = []

    def move(self, x: int, y: int) -> None:
        self.actions.append(("move", x, y))

    def left_click(self, x: int, y: int) -> None:
        self.actions.append(("left", x, y))

    def right_click(self, x: int, y: int) -> None:
        self.actions.append(("right", x, y))


if sys.platform == "win32":
    from ctypes import wintypes

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT), ("_pad", ctypes.c_byte * 32)]

        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]


class Win32Mouse:
    """Real input. Moves with SetCursorPos, then sends button down/up via SendInput."""

    live = True

    def __init__(self, press_s: float = 0.03) -> None:
        if sys.platform != "win32":
            raise RuntimeError("live input is only supported on Windows")
        self.press_s = press_s
        self._u = ctypes.windll.user32

    def _buttons(self, down: int, up: int) -> None:
        for flag in (down, up):
            inp = _INPUT(type=0)
            inp.mi = _MOUSEINPUT(0, 0, 0, flag, 0, 0)
            self._u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
            if flag == down:
                time.sleep(self.press_s)

    def move(self, x: int, y: int) -> None:
        self._u.SetCursorPos(int(x), int(y))

    def left_click(self, x: int, y: int) -> None:
        self.move(x, y)
        time.sleep(0.02)  # let the game register the hover before pressing
        self._buttons(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)

    def right_click(self, x: int, y: int) -> None:
        self.move(x, y)
        time.sleep(0.02)
        self._buttons(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)


def cursor_pos() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


VK_CODES = {f"F{i}": 0x6F + i for i in range(1, 13)} | {"ESC": 0x1B, "PAUSE": 0x13, "END": 0x23}


def key_down(name: str) -> bool:
    """True while the named key is held (polled; works even when the game has focus)."""
    if sys.platform != "win32":
        return False
    vk = VK_CODES.get(name.upper())
    return bool(vk and ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
