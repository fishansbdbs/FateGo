from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import time
from pathlib import Path

from fgo_guardian.config import AppConfig
from fgo_guardian.hotkey import EmergencyHotkey
from fgo_guardian.screen_capture import DesktopCapture, SafeCapture
from fgo_guardian.tools.common import (
    ensure_not_stopped,
    latch_stop,
    project_root,
    session_root,
    session_state_lock,
)
from fgo_guardian.viewport_mapper import ViewportMapper
from fgo_guardian.win32_api import PyWin32WindowApi
from fgo_guardian.window_guardian import WindowGuardian


class ViewportStateOwnershipError(RuntimeError):
    pass


class ViewportStateOwner:
    """Own one persistent viewport-state file through a write-denying handle."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.token = secrets.token_urlsafe(32)
        self._handle = self._open_write_denied(path)
        try:
            identity = os.fstat(self._handle.fileno())
            self._identity = (identity.st_dev, identity.st_ino)
            self._write(f"viewport_observable:{self.token}")
        except BaseException:
            self._handle.close()
            raise

    @staticmethod
    def _open_write_denied(path: Path):
        if os.name != "nt":
            return path.open("a+b", buffering=0)

        import ctypes

        descriptor = ctypes.c_int(-1)
        runtime = ctypes.CDLL("ucrtbase", use_errno=True)
        wsopen = runtime._wsopen_s
        wsopen.argtypes = (
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        )
        wsopen.restype = ctypes.c_int
        error = wsopen(
            ctypes.byref(descriptor),
            str(path),
            os.O_RDWR | os.O_CREAT | os.O_BINARY,
            0x20,
            0o600,
        )
        if error:
            raise OSError(error, os.strerror(error), str(path))
        return os.fdopen(descriptor.value, "r+b", buffering=0)

    def _owns_path(self) -> bool:
        if self._handle.closed:
            return False
        try:
            identity = self.path.stat()
            return (identity.st_dev, identity.st_ino) == self._identity
        except OSError:
            return False

    def _read(self) -> str:
        if not self._owns_path():
            raise ViewportStateOwnershipError("viewport state ownership lost")
        self._handle.seek(0)
        return self._handle.read().decode("utf-8")

    def _write(self, state: str) -> None:
        if not self._owns_path():
            raise ViewportStateOwnershipError("viewport state ownership lost")
        payload = state.encode("utf-8")
        self._handle.seek(0)
        self._handle.write(payload)
        self._handle.truncate()
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def pause(self, exception_type: str) -> None:
        current = self._read()
        observable = f"viewport_observable:{self.token}"
        paused_suffix = f":{self.token}"
        if current != observable and not (
            current.startswith("viewport_unobservable:") and current.endswith(paused_suffix)
        ):
            raise ViewportStateOwnershipError("viewport state content is not owned")
        self._write(f"viewport_unobservable:{exception_type}:{self.token}")

    def resume(self) -> None:
        current = self._read()
        observable = f"viewport_observable:{self.token}"
        paused_suffix = f":{self.token}"
        if current != observable and not (
            current.startswith("viewport_unobservable:") and current.endswith(paused_suffix)
        ):
            raise ViewportStateOwnershipError("viewport state content is not owned")
        if current != observable:
            self._write(observable)

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()


def transition_stop(stopped_path: Path, reason: str) -> bool:
    try:
        with session_state_lock(stopped_path.parent):
            return latch_stop(stopped_path, reason)
    except BaseException:
        try:
            return latch_stop(stopped_path, reason)
        except BaseException:
            return False


def construct_and_start_hotkey(hotkey_factory, value: str, callback, stopped_path: Path):
    try:
        hotkey = hotkey_factory(value, callback)
        hotkey.start()
    except BaseException as error:
        transition_stop(stopped_path, f"hotkey_startup:{type(error).__name__}")
        raise
    return hotkey


def latch_if_unsafe(
    guardian,
    baseline,
    stopped_path: Path,
) -> bool:
    try:
        report = guardian.check(baseline)
    except BaseException as error:
        transition_stop(stopped_path, f"guardian_check:{type(error).__name__}")
        return True
    if not report.safe:
        transition_stop(stopped_path, "guardian:" + ",".join(report.reasons))
        return True
    return False


def emit_signature_diagnostic(expected_signature, current_signature) -> None:
    print(
        f"viewport_signature_mismatch expected={expected_signature!r} current={current_signature!r}",
        file=sys.stderr,
        flush=True,
    )


def establish_viewport_signature(
    capture,
    baseline,
    mapper,
    *,
    attempts: int = 12,
    required_consecutive: int = 2,
    retry_delay_seconds: float = 0.1,
):
    if (
        required_consecutive < 1
        or attempts < required_consecutive
        or retry_delay_seconds < 0
    ):
        raise ValueError("invalid startup viewport confirmation settings")
    candidate = None
    consecutive = 0
    last_mapping_error: Exception | None = None
    for attempt in range(attempts):
        image = capture.capture(baseline).image
        try:
            signature = mapper.locate(image).signature
        except Exception as error:
            candidate = None
            consecutive = 0
            last_mapping_error = error
        else:
            last_mapping_error = None
            if signature == candidate:
                consecutive += 1
            else:
                candidate = signature
                consecutive = 1
            if consecutive >= required_consecutive:
                return signature
        if attempt + 1 < attempts and retry_delay_seconds:
            time.sleep(retry_delay_seconds)
    raise ValueError("startup viewport signature did not stabilize") from last_mapping_error


def run_monitor(
    config,
    guardian,
    capture,
    mapper,
    stopped_path: Path,
    hotkey_factory=EmergencyHotkey,
    stopped=None,
    state_owner_factory=None,
):
    try:
        hwnd = guardian.select_unique()
        baseline = guardian.establish_baseline(hwnd)
        required_consecutive = int(getattr(config, "startup_viewport_confirmations", 2))
        expected_viewport_signature = establish_viewport_signature(
            capture,
            baseline,
            mapper,
            attempts=int(getattr(config, "startup_viewport_attempts", 12)),
            required_consecutive=required_consecutive,
            retry_delay_seconds=float(
                getattr(config, "startup_viewport_retry_delay_seconds", 0.1)
            ),
        )
    except BaseException as error:
        transition_stop(stopped_path, f"sentinel_startup:{type(error).__name__}")
        raise

    stopped = threading.Event() if stopped is None else stopped
    signature_mismatch_candidate = None
    signature_mismatch_count = 0
    paused_path = stopped_path.with_name("VIEWPORT_PAUSED")
    state_owner_factory = ViewportStateOwner if state_owner_factory is None else state_owner_factory

    try:
        with session_state_lock(stopped_path.parent):
            ensure_not_stopped(stopped_path.parent, locked=True)
            state_owner = state_owner_factory(paused_path)
    except BaseException as error:
        reason = (
            f"viewport_state_io:{type(error).__name__}"
            if isinstance(error, (OSError, UnicodeError))
            else f"sentinel_startup:{type(error).__name__}"
        )
        transition_stop(stopped_path, reason)
        raise

    def latch() -> None:
        try:
            transition_stop(stopped_path, "emergency_stop")
        finally:
            stopped.set()

    try:
        hotkey = construct_and_start_hotkey(
            hotkey_factory,
            config.emergency_hotkey,
            latch,
            stopped_path,
        )
        try:
            interval = config.capture_interval_ms / 1000
            while not stopped.wait(timeout=interval):
                try:
                    hotkey.ensure_running()
                except BaseException as error:
                    transition_stop(stopped_path, f"hotkey_monitor:{type(error).__name__}")
                    raise
                try:
                    image = capture.capture(baseline).image
                except BaseException as error:
                    transition_stop(stopped_path, f"viewport_monitor:{type(error).__name__}")
                    raise
                try:
                    current_viewport_signature = mapper.locate(image).signature
                except Exception as error:
                    signature_mismatch_candidate = None
                    signature_mismatch_count = 0
                    if latch_if_unsafe(guardian, baseline, stopped_path):
                        stopped.set()
                        continue
                    try:
                        with session_state_lock(stopped_path.parent):
                            try:
                                stopped_path.stat()
                            except FileNotFoundError:
                                pass
                            else:
                                stopped.set()
                                continue
                            state_owner.pause(type(error).__name__)
                    except ViewportStateOwnershipError:
                        transition_stop(stopped_path, "viewport_state_ownership_lost")
                        stopped.set()
                    except (OSError, UnicodeError) as state_error:
                        transition_stop(
                            stopped_path, f"viewport_state_io:{type(state_error).__name__}"
                        )
                        stopped.set()
                        raise
                    continue
                except BaseException as error:
                    transition_stop(stopped_path, f"viewport_monitor:{type(error).__name__}")
                    raise
                if latch_if_unsafe(
                    guardian,
                    baseline,
                    stopped_path,
                ):
                    stopped.set()
                    continue
                if current_viewport_signature != expected_viewport_signature:
                    if current_viewport_signature == signature_mismatch_candidate:
                        signature_mismatch_count += 1
                    else:
                        signature_mismatch_candidate = current_viewport_signature
                        signature_mismatch_count = 1
                    try:
                        with session_state_lock(stopped_path.parent):
                            try:
                                stopped_path.stat()
                            except FileNotFoundError:
                                state_owner.pause("SignatureChanged")
                                try:
                                    emit_signature_diagnostic(
                                        expected_viewport_signature,
                                        current_viewport_signature,
                                    )
                                except BaseException as diagnostic_error:
                                    latch_stop(
                                        stopped_path,
                                        f"viewport_diagnostic:{type(diagnostic_error).__name__}",
                                    )
                                    stopped.set()
                                    raise
                                if signature_mismatch_count >= 3:
                                    latch_stop(stopped_path, "viewport_signature_changed")
                                    stopped.set()
                            else:
                                stopped.set()
                    except ViewportStateOwnershipError:
                        transition_stop(stopped_path, "viewport_state_ownership_lost")
                        stopped.set()
                    except (OSError, UnicodeError) as state_error:
                        transition_stop(
                            stopped_path, f"viewport_state_io:{type(state_error).__name__}"
                        )
                        stopped.set()
                        raise
                    continue
                signature_mismatch_candidate = None
                signature_mismatch_count = 0
                try:
                    with session_state_lock(stopped_path.parent):
                        try:
                            stopped_path.stat()
                        except FileNotFoundError:
                            state_owner.resume()
                        else:
                            stopped.set()
                except ViewportStateOwnershipError:
                    transition_stop(stopped_path, "viewport_state_ownership_lost")
                    stopped.set()
                except (OSError, UnicodeError) as state_error:
                    transition_stop(stopped_path, f"viewport_state_io:{type(state_error).__name__}")
                    stopped.set()
                    raise
        except KeyboardInterrupt:
            transition_stop(stopped_path, "keyboard_interrupt")
        finally:
            try:
                hotkey.stop()
            except BaseException as error:
                transition_stop(stopped_path, f"hotkey_shutdown:{type(error).__name__}")
                raise
    finally:
        try:
            state_owner.close()
        except (OSError, UnicodeError) as state_error:
            transition_stop(stopped_path, f"viewport_state_io:{type(state_error).__name__}")
            raise
    return hotkey


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()

    root = project_root()
    session = session_root(args.session)
    ensure_not_stopped(session)
    stopped_path = session / "STOPPED"
    try:
        config = AppConfig.load(root / "config" / "default.json")
        guardian = WindowGuardian(PyWin32WindowApi(), config)
        capture = SafeCapture(guardian, DesktopCapture())
        mapper = ViewportMapper()
    except BaseException as error:
        transition_stop(stopped_path, f"sentinel_startup:{type(error).__name__}")
        raise
    run_monitor(config, guardian, capture, mapper, stopped_path)


if __name__ == "__main__":
    main()
