from pathlib import Path
from types import SimpleNamespace

import pytest

from fgo_guardian.hotkey import EmergencyHotkey, parse_hotkey
from fgo_guardian.tools.recon_sentinel import run_monitor


def _run_with_hotkey_factory(tmp_path: Path, factory, value: str = "ctrl+shift+f12"):
    guardian = SimpleNamespace(
        select_unique=lambda: 7,
        establish_baseline=lambda hwnd: "baseline",
        check=lambda baseline: SimpleNamespace(safe=True, reasons=()),
    )
    capture = SimpleNamespace(capture=lambda baseline: SimpleNamespace(image=object()))
    mapper = SimpleNamespace(locate=lambda image: SimpleNamespace(signature=("stable",)))
    stopped = SimpleNamespace(wait=lambda timeout=None: True, set=lambda: None)
    config = SimpleNamespace(
        emergency_hotkey=value,
        capture_interval_ms=250,
        startup_viewport_confirmations=1,
    )
    return run_monitor(config, guardian, capture, mapper, tmp_path / "STOPPED", factory, stopped)


def test_parse_hotkey_matches_default(tmp_path: Path) -> None:
    assert parse_hotkey("ctrl+shift+f12") == (0x0002 | 0x0004, 0x7B)
    with pytest.raises(ValueError, match=r"ctrl\+shift\+f12"):
        _run_with_hotkey_factory(tmp_path, EmergencyHotkey, "alt+f4")
    assert (tmp_path / "STOPPED").read_text(encoding="utf-8") == "hotkey_startup:ValueError"


def test_registration_failure_is_surfaced(tmp_path: Path) -> None:
    class FailingUser32:
        @staticmethod
        def RegisterHotKey(hwnd, hotkey_id, modifiers, virtual_key):
            return 0

    class Kernel32:
        @staticmethod
        def GetCurrentThreadId():
            return 123

    stopped = tmp_path / "STOPPED"

    def failing_factory(value, callback):
        return EmergencyHotkey(value, callback, FailingUser32(), Kernel32())

    with pytest.raises(RuntimeError, match="registration failed"):
        _run_with_hotkey_factory(tmp_path, failing_factory)
    assert stopped.read_text(encoding="utf-8") == "hotkey_startup:RuntimeError"

    class FakeThread:
        def __init__(self, alive: bool) -> None:
            self.alive = alive
            self.joined = False

        def join(self, timeout=None):
            self.joined = True

        def is_alive(self):
            return self.alive

    class PostUser32:
        post_result = 0

        @classmethod
        def PostThreadMessageW(cls, thread_id, message, wparam, lparam):
            return cls.post_result

    hotkey = EmergencyHotkey("ctrl+shift+f12", lambda: None, PostUser32(), Kernel32())
    failed_thread = FakeThread(True)
    hotkey.thread = failed_thread
    hotkey.thread_id = 123
    with pytest.raises(RuntimeError, match="post"):
        hotkey.stop()
    assert hotkey.thread is failed_thread and hotkey.thread_id == 123 and hotkey.error is not None

    PostUser32.post_result = 1
    live_thread = FakeThread(True)
    hotkey.thread = live_thread
    hotkey.thread_id = 123
    hotkey.error = None
    with pytest.raises(RuntimeError, match="did not stop"):
        hotkey.stop()
    assert hotkey.thread is live_thread and hotkey.thread_id == 123 and hotkey.error is not None
