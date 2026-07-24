from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Callable, Protocol

import win32api
import win32con
import win32gui
import win32process

from .models import Rect, WindowSnapshot


PROCESS_ACCESS = win32con.PROCESS_QUERY_LIMITED_INFORMATION
DWMWA_CLOAKED = 14
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_TRUSTED_CONTROL_OVERLAY_PATH_SUFFIX = (
    "@oai",
    "sky",
    "bin",
    "windows",
    "codex-computer-use.exe",
)
# The Windows taskbar (primary + per-monitor) is a topmost shell window that
# overlaps the bottom edge of a maximised LDPlayer window. It does not cover the
# game's controls, so it must not count as an "overlap" blocker or the agent can
# never arm on a normal multi-monitor setup.
_IGNORED_OVERLAP_CLASSES = frozenset(
    {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
)
_TRUSTED_CONTROL_OVERLAY_CLASS = "CodexComputerUseCursorOverlay"
_TRUSTED_CONTROL_OVERLAY_TITLES = frozenset(
    {
        "ChatGPT is using your computer. Esc to cancel",
        "Codex Computer Use Cursor Overlay",
    }
)
_TRUSTED_CONTROL_OVERLAY_STYLES = (
    win32con.WS_EX_TOPMOST
    | win32con.WS_EX_LAYERED
    | win32con.WS_EX_TRANSPARENT
    | win32con.WS_EX_NOACTIVATE
    | win32con.WS_EX_TOOLWINDOW
)


def enable_per_monitor_v2() -> None:
    user32 = ctypes.windll.user32
    user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    result = user32.SetProcessDpiAwarenessContext(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    if not result and ctypes.get_last_error() not in {0, 5}:
        raise ctypes.WinError(ctypes.get_last_error())
    current = ctypes.c_void_p(user32.GetThreadDpiAwarenessContext())
    if not user32.AreDpiAwarenessContextsEqual(
        current, _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    ):
        raise RuntimeError("process is not per-monitor DPI aware v2")


class WindowApi(Protocol):
    def find_matching_windows(self, executable: Path, title: str) -> list[int]: ...

    def snapshot(self, hwnd: int) -> WindowSnapshot: ...

    def blockers_above(self, hwnd: int, protected_rect: Rect) -> list[tuple[int, Rect]]: ...


class PyWin32WindowApi:
    def __init__(self, *, is_cloaked: Callable[[int], bool] | None = None) -> None:
        enable_per_monitor_v2()
        self._is_cloaked_query = self._is_cloaked if is_cloaked is None else is_cloaked

    def _process_path(self, hwnd: int) -> tuple[int, Path]:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(PROCESS_ACCESS, False, pid)
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            query_image_name = kernel32.QueryFullProcessImageNameW
            query_image_name.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            query_image_name.restype = wintypes.BOOL
            if not query_image_name(
                wintypes.HANDLE(int(handle)), 0, buffer, ctypes.byref(length)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            path = Path(buffer[: length.value]).resolve()
        finally:
            handle.Close()
        return pid, path

    @staticmethod
    def _rect(values: tuple[int, int, int, int]) -> Rect:
        return Rect(*map(int, values))

    @staticmethod
    def _is_cloaked(hwnd: int) -> bool:
        value = ctypes.c_int(0)
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_CLOAKED,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        return result == 0 and value.value != 0

    def find_matching_windows(self, executable: Path, title: str) -> list[int]:
        matches: list[int] = []
        expected = executable.resolve()

        def visit(hwnd: int, _: object) -> None:
            if (
                not win32gui.IsWindowVisible(hwnd)
                or self._is_cloaked_query(hwnd)
                or win32gui.GetWindowText(hwnd) != title
            ):
                return
            try:
                _, path = self._process_path(hwnd)
            except win32api.error:
                return
            if path == expected:
                matches.append(hwnd)

        win32gui.EnumWindows(visit, None)
        return matches

    def snapshot(self, hwnd: int) -> WindowSnapshot:
        pid, process_path = self._process_path(hwnd)
        outer = self._rect(win32gui.GetWindowRect(hwnd))
        client_local = win32gui.GetClientRect(hwnd)
        client_origin = win32gui.ClientToScreen(hwnd, (0, 0))
        client = Rect(
            client_origin[0],
            client_origin[1],
            client_origin[0] + client_local[2],
            client_origin[1] + client_local[3],
        )
        monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        monitor_info = win32api.GetMonitorInfo(monitor)
        dpi = int(ctypes.windll.user32.GetDpiForWindow(hwnd))
        visible = bool(win32gui.IsWindowVisible(hwnd)) and not self._is_cloaked_query(hwnd)
        return WindowSnapshot(
            hwnd=hwnd,
            pid=pid,
            process_path=process_path,
            title=win32gui.GetWindowText(hwnd),
            outer_rect=outer,
            client_rect=client,
            monitor_name=str(monitor_info["Device"]),
            monitor_rect=self._rect(monitor_info["Monitor"]),
            windows_dpi=dpi,
            visible=visible,
            minimized=bool(win32gui.IsIconic(hwnd)),
            foreground=win32gui.GetForegroundWindow() == hwnd,
            work_rect=self._rect(monitor_info["Work"]),
        )

    def _is_trusted_control_overlay(self, hwnd: int) -> bool:
        try:
            _, process_path = self._process_path(hwnd)
            path_suffix = tuple(part.casefold() for part in process_path.parts[-5:])
            return (
                path_suffix == _TRUSTED_CONTROL_OVERLAY_PATH_SUFFIX
                and win32gui.GetClassName(hwnd) == _TRUSTED_CONTROL_OVERLAY_CLASS
                and win32gui.GetWindowText(hwnd) in _TRUSTED_CONTROL_OVERLAY_TITLES
                and win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                == _TRUSTED_CONTROL_OVERLAY_STYLES
            )
        except Exception:
            return False

    def blockers_above(self, hwnd: int, protected_rect: Rect) -> list[tuple[int, Rect]]:
        blockers: list[tuple[int, Rect]] = []
        current = win32gui.GetWindow(hwnd, win32con.GW_HWNDPREV)
        while current:
            if (
                win32gui.IsWindowVisible(current)
                and not win32gui.IsIconic(current)
                and not self._is_cloaked_query(current)
            ):
                rect = self._rect(win32gui.GetWindowRect(current))
                try:
                    window_class = win32gui.GetClassName(current)
                except Exception:
                    window_class = ""
                if (
                    rect.width > 0
                    and rect.height > 0
                    and rect.intersects(protected_rect)
                    and window_class not in _IGNORED_OVERLAP_CLASSES
                    and not self._is_trusted_control_overlay(current)
                ):
                    blockers.append((current, rect))
            current = win32gui.GetWindow(current, win32con.GW_HWNDPREV)
        return blockers
