from __future__ import annotations

"""Console entry point for the autonomous FGO player.

Usage (from the project root, with the venv active)::

    python -m fgo_guardian.app          # Do-All / Story auto-play
    fgo-guardian                        # same, via the installed script

Before starting: open FGO in the single LDPlayer window, make it the focused
window, and leave it un-covered. Then press Enter here to arm.

Controls while running:
    p + Enter  -> pause        r + Enter -> resume
    s + Enter  -> stop         Ctrl+Shift+F12 -> emergency stop (global)
"""

import argparse
import sys
import threading
import time
from pathlib import Path

from .auto_player import AutoPlayer, LoopTuning
from .config import AppConfig
from .hotkey import EmergencyHotkey
from .screen_capture import DesktopCapture, SafeCapture
from .viewport_mapper import ViewportMapper
from .win32_api import PyWin32WindowApi
from .window_guardian import WindowGuardian


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _log(message: str) -> None:
    print(f"[fgo] {message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous FGO player for one LDPlayer window")
    parser.add_argument("--config", default=str(project_root() / "config" / "default.json"))
    parser.add_argument("--interval-ms", type=int, default=None,
                        help="override base decision interval in milliseconds (lower = faster)")
    args = parser.parse_args()

    config = AppConfig.load(Path(args.config))
    guardian = WindowGuardian(PyWin32WindowApi(), config)
    capture = SafeCapture(guardian, DesktopCapture())
    mapper = ViewportMapper()

    _log("locating the single LDPlayer window...")
    _log(">>> Click the LDPlayer window now so it is the focused window. <<<")
    _log("    (Waiting up to 60s for LDPlayer to be focused, then it arms.)")
    baseline = None
    last_error: Exception | None = None
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            hwnd = guardian.select_unique()
            baseline = guardian.establish_baseline(hwnd)
            break
        except Exception as error:
            last_error = error
            time.sleep(0.7)
    if baseline is None:
        _log(f"could not arm: {last_error}")
        _log("make sure exactly one LDPlayer window is open, focused, and not covered.")
        sys.exit(1)
    _log("armed. FGO window locked.")

    tuning = LoopTuning()
    if args.interval_ms is not None:
        tuning.decision_interval = max(0.05, args.interval_ms / 1000)

    player = AutoPlayer(guardian, capture, mapper, baseline, tuning=tuning, log=_log)

    stop = threading.Event()
    paused = threading.Event()

    def emergency() -> None:
        _log("EMERGENCY STOP")
        stop.set()

    hotkey = EmergencyHotkey(config.emergency_hotkey, emergency)
    try:
        hotkey.start()
    except Exception as error:
        _log(f"warning: emergency hotkey unavailable ({error}); use 's' to stop.")

    worker = threading.Thread(target=player.run, args=(stop, paused), name="fgo-auto-player", daemon=True)
    worker.start()
    _log("playing. commands: p=pause r=resume s=stop")

    try:
        while not stop.is_set():
            line = sys.stdin.readline()
            if not line:
                break
            cmd = line.strip().lower()
            if cmd == "p":
                paused.set()
                _log("paused")
            elif cmd == "r":
                paused.clear()
                _log("resumed")
            elif cmd in {"s", "q", "stop", "quit"}:
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join(timeout=3)
        try:
            hotkey.stop()
        except Exception:
            pass
        _log("stopped.")


if __name__ == "__main__":
    main()
