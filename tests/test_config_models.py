from pathlib import Path

import pytest

from fgo_guardian.config import AppConfig
from fgo_guardian.models import Rect, SafetyStatus, VisualState, WindowSnapshot


def test_rect_geometry_and_intersection() -> None:
    left = Rect(-1920, 0, 0, 1040)
    blocker = Rect(-100, 50, 40, 200)
    separate = Rect(10, 10, 20, 20)
    assert left.width == 1920
    assert left.height == 1040
    assert left.intersects(blocker)
    assert not left.intersects(separate)


def test_window_snapshot_derives_logical_geometry_from_dpi() -> None:
    snapshot = WindowSnapshot(
        hwnd=1,
        pid=2,
        process_path=Path("dnplayer.exe"),
        title="LDPlayer",
        outer_rect=Rect(-1920, 0, 0, 1080),
        client_rect=Rect(-1920, 32, 0, 1080),
        monitor_name="DISPLAY2",
        monitor_rect=Rect(-1920, 0, 0, 1080),
        windows_dpi=192,
        visible=True,
        minimized=False,
        foreground=True,
    )
    assert snapshot.logical_outer_rect == Rect(-960, 0, 0, 540)


def test_default_config_matches_inspection() -> None:
    config = AppConfig.load(Path("config/default.json"))
    assert config.target_executable == Path(r"C:\LDPlayer\LDPlayer14\dnplayer.exe")
    assert config.ldplayer_version == "14.0.15.0"
    assert config.game_tab_title == "Fate/GO"
    assert config.game_package == "com.aniplex.fategrandorder.en"
    assert config.game_version == "2.90.2"
    assert config.android_resolution == (1920, 1080)
    assert config.android_dpi == 280
    assert config.confidence_threshold == pytest.approx(0.92)
    assert config.emergency_hotkey == "ctrl+shift+f12"
    assert VisualState.UNKNOWN.value == "UNKNOWN"
    assert SafetyStatus.DISARMED.value == "DISARMED"


def test_config_rejects_out_of_range_confidence(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        '{"target_executable":"C:\\\\LDPlayer\\\\LDPlayer14\\\\dnplayer.exe",'
        '"target_title":"LDPlayer","android_resolution":[1920,1080],'
        '"android_dpi":280,"orientation":"landscape",'
        '"confidence_threshold":1.2,"stale_timeout_seconds":10.0,'
        '"emergency_hotkey":"ctrl+shift+f12","capture_interval_ms":250}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="confidence_threshold"):
        AppConfig.load(path)
