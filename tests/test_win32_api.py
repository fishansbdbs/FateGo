from pathlib import Path
import sys

import pytest
import win32con
import win32gui

from fgo_guardian.win32_api import (
    PROCESS_ACCESS,
    PyWin32WindowApi,
    enable_per_monitor_v2,
)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only API")
def test_enable_per_monitor_v2_is_idempotent() -> None:
    enable_per_monitor_v2()
    enable_per_monitor_v2()


def test_process_metadata_access_does_not_include_memory_read_rights() -> None:
    assert PROCESS_ACCESS == win32con.PROCESS_QUERY_LIMITED_INFORMATION


def test_cloaked_window_is_not_a_matching_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fgo_guardian.win32_api.enable_per_monitor_v2", lambda: None)
    api = PyWin32WindowApi(is_cloaked=lambda hwnd: True)
    monkeypatch.setattr(
        win32gui, "EnumWindows", lambda visit, _: visit(100, None)
    )
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "GetWindowText", lambda hwnd: "LDPlayer")
    monkeypatch.setattr(
        api,
        "_process_path",
        lambda hwnd: (7, Path(r"C:\LDPlayer\LDPlayer14\dnplayer.exe").resolve()),
    )

    assert api.find_matching_windows(
        Path(r"C:\LDPlayer\LDPlayer14\dnplayer.exe"), "LDPlayer"
    ) == []


def test_blockers_above_exempts_only_exact_trusted_control_overlays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fgo_guardian.win32_api.enable_per_monitor_v2", lambda: None)
    api = PyWin32WindowApi(is_cloaked=lambda hwnd: False)
    trusted_path = Path(
        r"C:\Codex\resources\app\node_modules\@oai\sky\bin\windows\codex-computer-use.exe"
    )
    required_styles = (
        win32con.WS_EX_TOPMOST
        | win32con.WS_EX_LAYERED
        | win32con.WS_EX_TRANSPARENT
        | win32con.WS_EX_NOACTIVATE
        | win32con.WS_EX_TOOLWINDOW
    )
    overlay = {
        "path": trusted_path,
        "class": "CodexComputerUseCursorOverlay",
        "title": "ChatGPT is using your computer. Esc to cancel",
        "styles": required_styles,
    }
    ordinary = {
        "path": Path(r"C:\Windows\System32\notepad.exe"),
        "class": "Notepad",
        "title": "notes.txt - Notepad",
        "styles": 0,
    }
    windows = {200: overlay, 300: ordinary}
    rects = {200: (100, 100, 500, 500), 300: (200, 200, 600, 600)}

    def metadata(hwnd: int, key: str) -> object:
        value = windows[hwnd][key]
        if value is None:
            raise OSError(f"{key} metadata unavailable")
        return value

    monkeypatch.setattr(
        win32gui,
        "GetWindow",
        lambda hwnd, relation: {100: 200, 200: 300, 300: 0}[hwnd],
    )
    monkeypatch.setattr(win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(win32gui, "IsIconic", lambda hwnd: False)
    monkeypatch.setattr(win32gui, "GetWindowRect", lambda hwnd: rects[hwnd])
    monkeypatch.setattr(win32gui, "GetClassName", lambda hwnd: metadata(hwnd, "class"))
    monkeypatch.setattr(win32gui, "GetWindowText", lambda hwnd: metadata(hwnd, "title"))
    monkeypatch.setattr(
        win32gui, "GetWindowLong", lambda hwnd, index: metadata(hwnd, "styles")
    )

    def process_path(hwnd: int) -> tuple[int, Path]:
        path = metadata(hwnd, "path")
        assert isinstance(path, Path)
        return hwnd, path

    monkeypatch.setattr(api, "_process_path", process_path)
    protected = api._rect((0, 0, 1000, 1000))
    cases = [
        ("trusted", {}, [(300, api._rect(rects[300]))]),
        (
            "trusted cursor title",
            {"title": "Codex Computer Use Cursor Overlay"},
            [(300, api._rect(rects[300]))],
        ),
        (
            "wrong runtime path",
            {"path": Path(r"C:\Temp\codex-computer-use.exe")},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
        (
            "wrong basename",
            {"path": trusted_path.with_name("computer-use.exe")},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
        (
            "wrong class",
            {"class": "CodexComputerUseOverlay"},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
        (
            "wrong title",
            {"title": "Codex is using your computer"},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
        (
            "process metadata error",
            {"path": None},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
        (
            "class metadata error",
            {"class": None},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
        (
            "title metadata error",
            {"title": None},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
        (
            "style metadata error",
            {"styles": None},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
        (
            "unreviewed extra style",
            {"styles": required_styles | win32con.WS_EX_APPWINDOW},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        ),
    ]
    cases.extend(
        (
            f"missing style {style}",
            {"styles": required_styles & ~style},
            [(200, api._rect(rects[200])), (300, api._rect(rects[300]))],
        )
        for style in (
            win32con.WS_EX_TOPMOST,
            win32con.WS_EX_LAYERED,
            win32con.WS_EX_TRANSPARENT,
            win32con.WS_EX_NOACTIVATE,
            win32con.WS_EX_TOOLWINDOW,
        )
    )

    original = overlay.copy()
    for label, changes, expected in cases:
        overlay.clear()
        overlay.update(original, **changes)
        assert api.blockers_above(100, protected) == expected, label
