from __future__ import annotations

"""Standard Windows mouse input for one guarded LDPlayer window.

The rest of the project only ever *observed* the screen. This module adds the
missing half: sending real mouse input through the Windows ``SendInput`` API so
the agent can actually play. It uses nothing but public Win32 input -- no ADB,
injection, or emulator tampering -- keeping it inside the project's safety
boundary.

Coordinates handed to :meth:`InputController.tap_normalized` are in the 0..1
space of the mapped Android viewport (see ``viewport_mapper``). They convert to
absolute desktop pixels using the frame that was just captured, then to the
0..65535 virtual-desktop space ``SendInput`` expects.
"""

import ctypes
import random
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

from .models import Rect
from .viewport_mapper import ViewportMapping


MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
INPUT_MOUSE = 0

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    class _UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]


def _virtual_screen() -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def _send_mouse(flags: int, abs_x: int = 0, abs_y: int = 0) -> None:
    payload = _INPUT()
    payload.type = INPUT_MOUSE
    payload.mi = _MOUSEINPUT(dx=abs_x, dy=abs_y, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=None)
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(payload), ctypes.sizeof(payload))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())


@dataclass(frozen=True, slots=True)
class SafetyGate:
    """Wraps a callable that returns True only when it is safe to send input."""

    check: Callable[[], bool]

    def safe(self) -> bool:
        try:
            return bool(self.check())
        except Exception:
            return False


class InputController:
    """Send taps to absolute desktop coordinates via ``SendInput``.

    Every tap is re-validated against ``safety_gate`` immediately before the
    button-down, so we never click into a window that moved or lost focus
    between observation and action.
    """

    def __init__(self, safety_gate: SafetyGate | None = None) -> None:
        self.safety_gate = safety_gate

    def _to_absolute(self, screen_x: int, screen_y: int) -> tuple[int, int]:
        vx, vy, vw, vh = _virtual_screen()
        ax = int(round((screen_x - vx) * 65535 / (vw - 1))) if vw > 1 else 0
        ay = int(round((screen_y - vy) * 65535 / (vh - 1))) if vh > 1 else 0
        return max(0, min(65535, ax)), max(0, min(65535, ay))

    def tap_screen(self, screen_x: int, screen_y: int, *, settle: float = 0.0) -> bool:
        if self.safety_gate is not None and not self.safety_gate.safe():
            return False
        abs_x, abs_y = self._to_absolute(screen_x, screen_y)
        move = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        _send_mouse(move, abs_x, abs_y)
        time.sleep(0.012)
        _send_mouse(MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, abs_x, abs_y)
        time.sleep(0.03 + random.uniform(0.0, 0.02))
        _send_mouse(MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, abs_x, abs_y)
        if settle:
            time.sleep(settle)
        return True

    def tap_normalized(
        self,
        frame_rect: Rect,
        mapping: ViewportMapping,
        nx: float,
        ny: float,
        *,
        jitter: float = 0.004,
        settle: float = 0.0,
    ) -> bool:
        """Tap a point given in 0..1 viewport space, with a little random jitter."""

        nx = min(0.999, max(0.001, nx + random.uniform(-jitter, jitter)))
        ny = min(0.999, max(0.001, ny + random.uniform(-jitter, jitter)))
        img_x = mapping.viewport.left + nx * mapping.viewport.width
        img_y = mapping.viewport.top + ny * mapping.viewport.height
        screen_x = int(round(frame_rect.left + img_x))
        screen_y = int(round(frame_rect.top + img_y))
        return self.tap_screen(screen_x, screen_y, settle=settle)
