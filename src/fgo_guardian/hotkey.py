from __future__ import annotations

import ctypes
import ctypes.wintypes
import threading
from collections.abc import Callable

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_F12 = 0x7B
HOTKEY_ID = 0xF60


def parse_hotkey(value: str) -> tuple[int, int]:
    parts = {part.strip().lower() for part in value.split("+")}
    if parts != {"ctrl", "shift", "f12"}:
        raise ValueError("reconnaissance hotkey must be ctrl+shift+f12")
    return MOD_CONTROL | MOD_SHIFT, VK_F12


class EmergencyHotkey:
    def __init__(self, value: str, callback: Callable[[], None], user32=None, kernel32=None) -> None:
        self.modifiers, self.virtual_key = parse_hotkey(value)
        self.callback = callback
        self.user32 = user32
        self.kernel32 = kernel32
        self.thread: threading.Thread | None = None
        self.thread_id = 0
        self.ready = threading.Event()
        self.registered = threading.Event()
        self.stopping = threading.Event()
        self.error: BaseException | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        self.ready.clear()
        self.registered.clear()
        self.stopping.clear()
        self.error = None
        self.thread = threading.Thread(target=self._run, name="fgo-emergency-stop", daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout=2):
            self.stop()
            raise RuntimeError("emergency hotkey registration timed out")
        if self.error is not None:
            error = self.error
            self.thread.join(timeout=2)
            self.thread = None
            self.thread_id = 0
            if self.registered.is_set():
                raise RuntimeError("emergency hotkey listener failed") from error
            raise RuntimeError("emergency hotkey registration failed") from error

    def _run(self) -> None:
        user32 = ctypes.windll.user32 if self.user32 is None else self.user32
        kernel32 = ctypes.windll.kernel32 if self.kernel32 is None else self.kernel32
        registered = False
        try:
            self.thread_id = int(kernel32.GetCurrentThreadId())
            if not user32.RegisterHotKey(None, HOTKEY_ID, self.modifiers, self.virtual_key):
                self.error = ctypes.WinError(ctypes.get_last_error())
                return
            registered = True
            self.registered.set()
            self.ready.set()
            message = ctypes.wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result < 0:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    if not self.stopping.is_set():
                        self.error = RuntimeError("emergency hotkey listener exited")
                    return
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                    self.callback()
        except BaseException as error:
            self.error = error
        finally:
            self.ready.set()
            if registered:
                user32.UnregisterHotKey(None, HOTKEY_ID)

    def ensure_running(self) -> None:
        if self.error is not None:
            raise RuntimeError("emergency hotkey listener failed") from self.error
        if self.thread is None or not self.thread.is_alive():
            raise RuntimeError("emergency hotkey listener is not running")

    def stop(self) -> None:
        self.stopping.set()
        thread = self.thread
        if thread is not None and not thread.is_alive():
            self.thread = None
            self.thread_id = 0
            return
        user32 = ctypes.windll.user32 if self.user32 is None else self.user32
        if self.thread_id:
            try:
                posted = user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
            except BaseException as error:
                self.error = error
                raise RuntimeError("emergency hotkey shutdown post failed") from error
            if not posted:
                error = ctypes.WinError(ctypes.get_last_error())
                self.error = error
                raise RuntimeError("emergency hotkey shutdown post failed") from error
        if thread is not None:
            thread.join(timeout=2)
            if thread.is_alive():
                error = RuntimeError("emergency hotkey listener did not stop")
                self.error = error
                raise error
        self.thread = None
        self.thread_id = 0
