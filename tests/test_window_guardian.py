from pathlib import Path

import pytest

from fgo_guardian.config import AppConfig
from fgo_guardian.models import Rect, WindowSnapshot
from fgo_guardian.window_guardian import WindowGuardian


class FakeWindowApi:
    def __init__(self, windows: list[int], snapshots: dict[int, WindowSnapshot]) -> None:
        self.windows = windows
        self.snapshots = snapshots
        self.blockers: list[tuple[int, Rect]] = []
        self.find_error: Exception | None = None
        self.blocker_error: Exception | None = None

    def find_matching_windows(self, executable: Path, title: str) -> list[int]:
        if self.find_error is not None:
            raise self.find_error
        return list(self.windows)

    def snapshot(self, hwnd: int) -> WindowSnapshot:
        return self.snapshots[hwnd]

    def blockers_above(self, hwnd: int, protected_rect: Rect) -> list[tuple[int, Rect]]:
        if self.blocker_error is not None:
            raise self.blocker_error
        return list(self.blockers)


def make_snapshot(*, foreground: bool = True, minimized: bool = False) -> WindowSnapshot:
    return WindowSnapshot(
        hwnd=100,
        pid=7,
        process_path=Path(r"C:\LDPlayer\LDPlayer14\dnplayer.exe"),
        title="LDPlayer",
        outer_rect=Rect(-1920, 0, 0, 1040),
        client_rect=Rect(-1920, 32, -35, 1040),
        monitor_name=r"\\.\DISPLAY2",
        monitor_rect=Rect(-1920, 0, 0, 1080),
        windows_dpi=96,
        visible=True,
        minimized=minimized,
        foreground=foreground,
    )


@pytest.fixture
def config() -> AppConfig:
    return AppConfig.load(Path("config/default.json"))


def test_select_unique_rejects_multiple(config: AppConfig) -> None:
    api = FakeWindowApi([100, 101], {100: make_snapshot(), 101: make_snapshot()})
    with pytest.raises(RuntimeError, match="exactly one"):
        WindowGuardian(api, config).select_unique()


def test_baseline_requires_two_identical_samples(config: AppConfig) -> None:
    snapshot = make_snapshot()
    api = FakeWindowApi([100], {100: snapshot})
    guardian = WindowGuardian(api, config)
    baseline = guardian.establish_baseline(100, sample_count=2, delay_seconds=0)
    assert baseline.geometry_signature == snapshot.geometry_signature()


def test_baseline_rejects_multiple_matching_targets(config: AppConfig) -> None:
    api = FakeWindowApi([100, 101], {100: make_snapshot(), 101: make_snapshot()})

    with pytest.raises(RuntimeError, match="exactly one"):
        WindowGuardian(api, config).establish_baseline(100, sample_count=2, delay_seconds=0)


def test_baseline_rejects_unsafe_window(config: AppConfig) -> None:
    snapshot = make_snapshot(foreground=False)
    api = FakeWindowApi([100], {100: snapshot})
    with pytest.raises(RuntimeError, match="unsafe baseline:focus_lost"):
        WindowGuardian(api, config).establish_baseline(100, sample_count=2, delay_seconds=0)


def test_check_pauses_for_focus_loss_and_overlap(config: AppConfig) -> None:
    api = FakeWindowApi([100], {100: make_snapshot()})
    guardian = WindowGuardian(api, config)
    baseline = guardian.establish_baseline(100, sample_count=2, delay_seconds=0)
    api.snapshots[100] = make_snapshot(foreground=False)
    api.blockers = [(999, Rect(-100, 100, -10, 200))]
    report = guardian.check(baseline)
    assert not report.safe
    assert "focus_lost" in report.reasons
    assert "overlap" in report.reasons
    assert report.blockers == (999,)


def test_check_pauses_if_another_matching_ldplayer_appears(config: AppConfig) -> None:
    api = FakeWindowApi([100], {100: make_snapshot()})
    guardian = WindowGuardian(api, config)
    baseline = guardian.establish_baseline(100, sample_count=2, delay_seconds=0)
    api.windows = [100, 101]
    report = guardian.check(baseline)
    assert not report.safe
    assert report.reasons == ("target_count_changed",)


def test_check_pauses_when_target_enumeration_fails(config: AppConfig) -> None:
    api = FakeWindowApi([100], {100: make_snapshot()})
    guardian = WindowGuardian(api, config)
    baseline = guardian.establish_baseline(100, sample_count=2, delay_seconds=0)
    api.find_error = RuntimeError("enumeration failed")

    report = guardian.check(baseline)

    assert not report.safe
    assert report.reasons == ("target_enumeration_failed:RuntimeError",)
    assert report.snapshot is None


def test_check_pauses_when_overlap_enumeration_fails(config: AppConfig) -> None:
    api = FakeWindowApi([100], {100: make_snapshot()})
    guardian = WindowGuardian(api, config)
    baseline = guardian.establish_baseline(100, sample_count=2, delay_seconds=0)
    api.blocker_error = RuntimeError("overlap enumeration failed")

    report = guardian.check(baseline)

    assert not report.safe
    assert report.reasons == ("overlap_enumeration_failed:RuntimeError",)
