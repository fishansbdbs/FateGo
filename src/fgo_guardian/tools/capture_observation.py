from __future__ import annotations

import argparse
import sys
import time

from fgo_guardian.agent_models import ScreenKind
from fgo_guardian.config import AppConfig
from fgo_guardian.privacy import PrivacyPolicy
from fgo_guardian.recording import RecordingStore
from fgo_guardian.screen_capture import DesktopCapture, SafeCapture
from fgo_guardian.tools.common import (
    ensure_not_stopped,
    project_root,
    session_root,
    session_state_lock,
)
from fgo_guardian.viewport_mapper import ViewportMapper
from fgo_guardian.win32_api import PyWin32WindowApi
from fgo_guardian.window_guardian import WindowGuardian


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument(
        "--screen",
        required=True,
        choices=[item.value for item in ScreenKind if item is not ScreenKind.UNKNOWN],
    )
    parser.add_argument("--confidence", required=True, type=float)
    parser.add_argument("--label", action="append", default=[])
    args = parser.parse_args()
    if not 0.92 <= args.confidence <= 1.0:
        parser.error("--confidence must be between 0.92 and 1.0")

    root = project_root()
    session = session_root(args.session)
    config = AppConfig.load(root / "config" / "default.json")
    guardian = WindowGuardian(PyWin32WindowApi(), config)
    print(
        "Focus the unobstructed LDPlayer window; capture starts in 3 seconds",
        file=sys.stderr,
        flush=True,
    )
    time.sleep(3)
    with session_state_lock(session):
        ensure_not_stopped(session, locked=True)
        hwnd = guardian.select_unique()
        baseline = guardian.establish_baseline(hwnd)
        frame = SafeCapture(guardian, DesktopCapture()).capture(baseline)
        mapping = ViewportMapper().locate(frame.image)
        store = RecordingStore(session, PrivacyPolicy.load(root / "config" / "privacy.json"))
        record = store.record_observation(
            frame.image,
            mapping,
            ScreenKind(args.screen),
            args.confidence,
            tuple(args.label),
        )
    print(record.observation_id)


if __name__ == "__main__":
    main()
