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
BUTTON_APIS = ("sendinput", "mouse_event")  # mouse_event: the older API (what a PowerShell test uses)


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

    def release(self) -> None:
        self.actions.append(("release",))


class InputBlocked(RuntimeError):
    """SendInput was rejected, typically because the game runs elevated (UIPI)."""


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


SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
GLIDE_STEPS = 4  # SendInput moves on the way to the right-click target


class Win32Mouse:
    """Real input. Moves with SetCursorPos, then sends button down/up via SendInput.

    The left button is pressed for press_s (30 ms), the right button for right_press_s
    (default 0.15 s, adjustable: some games only notice a right press that lasts a few frames).
    The right click first glides back onto the target with real SendInput mouse moves when the
    cursor is elsewhere (it was parked after the left click; some games only update what is
    under the cursor from mouse-move input, not from SetCursorPos) and rests right_hover_s.
    """

    live = True

    def __init__(self, press_s: float = 0.03, right_hover_s: float = 0.03, right_press_s: float = 0.15,
                 right_api: str = "sendinput") -> None:
        if sys.platform != "win32":
            raise RuntimeError("live input is only supported on Windows")
        if right_api not in BUTTON_APIS:
            raise ValueError(f"right_api must be one of {BUTTON_APIS}")
        self.right_api = right_api
        self.press_s = press_s
        self.right_hover_s = right_hover_s
        self.right_press_s = right_press_s
        self._u = ctypes.windll.user32

    def _send(self, flag: int, dx: int = 0, dy: int = 0) -> bool:
        inp = _INPUT(type=0)
        inp.mi = _MOUSEINPUT(dx, dy, 0, flag, 0, 0)
        return self._u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)) == 1

    def _legacy(self, flag: int) -> bool:
        """The same button event through the older mouse_event API (no return value to check)."""
        self._u.mouse_event(flag, 0, 0, 0, 0)
        return True

    def _buttons(self, down: int, up: int, press_s: float | None = None, api: str = "sendinput") -> None:
        send = self._legacy if api == "mouse_event" else self._send
        if not send(down):
            raise InputBlocked("SendInput was blocked; if the game runs as administrator, run this tool as administrator too")
        try:
            time.sleep(self.press_s if press_s is None else press_s)
        finally:
            send(up)  # never leave a button held down

    def _input_move(self, x: int, y: int) -> None:
        """One absolute SendInput mouse move to screen pixel (x, y) on the virtual desktop."""
        m = self._u.GetSystemMetrics
        vx, vy = m(SM_XVIRTUALSCREEN), m(SM_YVIRTUALSCREEN)
        vw, vh = max(2, m(SM_CXVIRTUALSCREEN)), max(2, m(SM_CYVIRTUALSCREEN))
        dx = round((x - vx) * 65535 / (vw - 1))
        dy = round((y - vy) * 65535 / (vh - 1))
        if not self._send(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, dx, dy):
            raise InputBlocked("SendInput was blocked; if the game runs as administrator, run this tool as administrator too")

    def glide(self, x: int, y: int) -> None:
        """Move onto (x, y) with SendInput mouse moves, then pin the exact pixel with SetCursorPos."""
        start = cursor_pos() or (x, y)
        for i in range(1, GLIDE_STEPS + 1):
            self._input_move(round(start[0] + (x - start[0]) * i / GLIDE_STEPS),
                             round(start[1] + (y - start[1]) * i / GLIDE_STEPS))
            time.sleep(0.005)
        self.move(x, y)

    def release(self) -> None:
        """Send button-up for both buttons (recovery after an error or stop)."""
        self._send(MOUSEEVENTF_LEFTUP)
        self._send(MOUSEEVENTF_RIGHTUP)

    def move(self, x: int, y: int) -> None:
        if not self._u.SetCursorPos(int(x), int(y)):
            raise InputBlocked(f"SetCursorPos({x}, {y}) failed")

    def left_click(self, x: int, y: int) -> None:
        self.move(x, y)
        time.sleep(0.02)  # let the game register the hover before pressing
        self._buttons(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)

    def right_click(self, x: int, y: int) -> None:
        if cursor_pos() != (x, y):
            self.glide(x, y)
        else:  # already there: a 1 px move and back, so the game sees real mouse input on the mob
            self._input_move(x + 1, y)
            time.sleep(0.005)
            self._input_move(x, y)
            self.move(x, y)
        if self.right_hover_s > 0:
            time.sleep(self.right_hover_s)  # let the game see the cursor on the mob before clicking
        self._buttons(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, self.right_press_s, self.right_api)

    def right_click_here(self) -> None:
        """Right click where the cursor is now, without moving it (the 'Test right click' button)."""
        self._buttons(MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, self.right_press_s, self.right_api)


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
