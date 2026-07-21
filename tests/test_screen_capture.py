from pathlib import Path

import numpy as np
import pytest

from fgo_guardian.models import Baseline, GuardReport, Rect, WindowSnapshot
from fgo_guardian.screen_capture import CaptureBlocked, SafeCapture


def snapshot() -> WindowSnapshot:
    return WindowSnapshot(
        hwnd=100,
        pid=7,
        process_path=Path(r"C:\\LDPlayer\\LDPlayer14\\dnplayer.exe"),
        title="LDPlayer",
        outer_rect=Rect(0, 0, 1920, 1040),
        client_rect=Rect(0, 32, 1885, 1040),
        monitor_name="DISPLAY2",
        monitor_rect=Rect(0, 0, 1920, 1080),
        windows_dpi=96,
        visible=True,
        minimized=False,
        foreground=True,
    )


class SequencedGuardian:
    def __init__(self, reports: list[GuardReport]) -> None:
        self.reports = reports

    def check(self, baseline: Baseline) -> GuardReport:
        return self.reports.pop(0)


class FakeDesktop:
    def capture(self, rect: Rect) -> np.ndarray:
        return np.full((rect.height, rect.width, 3), 127, dtype=np.uint8)


class WrongSizeDesktop:
    def capture(self, rect: Rect) -> np.ndarray:
        return np.zeros((rect.height - 1, rect.width, 3), dtype=np.uint8)


def baseline() -> Baseline:
    item = snapshot()
    return Baseline(
        item.hwnd,
        item.pid,
        item.process_path,
        item.title,
        item.geometry_signature(),
        (1920, 1080),
        280,
        "landscape",
    )


def test_capture_succeeds_only_when_both_checks_are_safe() -> None:
    item = snapshot()
    safe = GuardReport(True, (), item)
    frame = SafeCapture(SequencedGuardian([safe, safe]), FakeDesktop()).capture(baseline())
    assert frame.image.shape == (1040, 1920, 3)


def test_capture_discards_frame_when_post_check_finds_overlap() -> None:
    item = snapshot()
    pre = GuardReport(True, (), item)
    post = GuardReport(False, ("overlap",), item, (999,))
    with pytest.raises(CaptureBlocked, match="overlap"):
        SafeCapture(SequencedGuardian([pre, post]), FakeDesktop()).capture(baseline())


def test_capture_rejects_unexpected_pixel_dimensions() -> None:
    item = snapshot()
    safe = GuardReport(True, (), item)
    with pytest.raises(CaptureBlocked, match="capture_dimensions_changed"):
        SafeCapture(SequencedGuardian([safe, safe]), WrongSizeDesktop()).capture(
            baseline()
        )
