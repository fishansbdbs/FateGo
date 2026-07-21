from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

from fgo_guardian.agent_models import Observation, ScreenKind
from fgo_guardian.models import Rect


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def session_root(session: str) -> Path:
    if not session or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in session
    ):
        raise ValueError("session must contain only letters, digits, dash, and underscore")
    return project_root() / "data" / "recordings" / session


_STATE_TOKEN = r"[A-Za-z0-9_-]{32,128}"
_OBSERVABLE_STATE = re.compile(rf"viewport_observable:{_STATE_TOKEN}")
_PAUSED_STATE = re.compile(rf"viewport_unobservable:[A-Za-z_][A-Za-z0-9_]*:{_STATE_TOKEN}")


def is_owned_unobservable_state(state: str) -> bool:
    return _PAUSED_STATE.fullmatch(state) is not None


def _best_effort_latch_stop(stopped_path: Path, reason: str) -> None:
    try:
        latch_stop(stopped_path, reason)
    except BaseException:
        pass


def _lock_windows_byte(handle):
    import ctypes
    import msvcrt

    class Overlapped(ctypes.Structure):
        _fields_ = (
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", ctypes.c_uint32),
            ("OffsetHigh", ctypes.c_uint32),
            ("hEvent", ctypes.c_void_p),
        )

    overlapped = Overlapped()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    lock_file = kernel32.LockFileEx
    lock_file.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(Overlapped),
    )
    lock_file.restype = ctypes.c_int
    ctypes.set_last_error(0)
    if not lock_file(
        ctypes.c_void_p(msvcrt.get_osfhandle(handle.fileno())),
        0x00000002 | 0x00000001,
        0,
        1,
        0,
        ctypes.byref(overlapped),
    ):
        error = ctypes.get_last_error()
        if error == 33:
            raise BlockingIOError(error, ctypes.FormatError(error))
        raise OSError(error, ctypes.FormatError(error))
    return overlapped


def _unlock_windows_byte(handle, overlapped) -> None:
    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    unlock_file = kernel32.UnlockFileEx
    unlock_file.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(type(overlapped)),
    )
    unlock_file.restype = ctypes.c_int
    ctypes.set_last_error(0)
    if not unlock_file(
        ctypes.c_void_p(msvcrt.get_osfhandle(handle.fileno())),
        0,
        1,
        0,
        ctypes.byref(overlapped),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, ctypes.FormatError(error))


@contextmanager
def session_state_lock(root: Path):
    """Serialize session safety-state transitions independently of recording I/O."""
    stopped_path = root / "STOPPED"
    handle = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        handle = (root / ".session-state.lock").open("a+b")
    except OSError as error:
        _best_effort_latch_stop(stopped_path, f"session_state_lock:{type(error).__name__}")
        raise
    try:
        if os.name == "nt":
            while True:
                try:
                    overlapped = _lock_windows_byte(handle)
                    break
                except BlockingIOError:
                    time.sleep(0.01)
                except OSError as error:
                    _best_effort_latch_stop(
                        stopped_path, f"session_state_lock:{type(error).__name__}"
                    )
                    raise
            try:
                try:
                    handle.seek(0)
                    if handle.read(1) == b"":
                        handle.seek(0)
                        handle.write(b"0")
                        handle.flush()
                        os.fsync(handle.fileno())
                except OSError as error:
                    _best_effort_latch_stop(
                        stopped_path, f"session_state_lock:{type(error).__name__}"
                    )
                    raise
                yield
            finally:
                try:
                    _unlock_windows_byte(handle, overlapped)
                except OSError as error:
                    _best_effort_latch_stop(
                        stopped_path, f"session_state_lock:{type(error).__name__}"
                    )
                    raise
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    handle.seek(0)
                    if handle.read(1) == b"":
                        handle.seek(0)
                        handle.write(b"0")
                        handle.flush()
                        os.fsync(handle.fileno())
                except OSError as error:
                    _best_effort_latch_stop(
                        stopped_path, f"session_state_lock:{type(error).__name__}"
                    )
                    raise
                yield
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError as error:
                    _best_effort_latch_stop(
                        stopped_path, f"session_state_lock:{type(error).__name__}"
                    )
                    raise
    finally:
        try:
            handle.close()
        except OSError as error:
            _best_effort_latch_stop(stopped_path, f"session_state_lock:{type(error).__name__}")
            raise


def _read_existing(path: Path) -> str | None:
    try:
        path.stat()
    except FileNotFoundError:
        return None
    return path.read_text(encoding="utf-8")


def ensure_not_stopped(root: Path, *, locked: bool = False) -> None:
    if not locked:
        with session_state_lock(root):
            ensure_not_stopped(root, locked=True)
        return

    stopped_path = root / "STOPPED"
    try:
        stopped_reason = _read_existing(stopped_path)
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"stopped_state_io:{type(error).__name__}") from error
    if stopped_reason is not None:
        raise RuntimeError(stopped_reason or "emergency_stop")

    state_path = root / "VIEWPORT_PAUSED"
    try:
        state = _read_existing(state_path)
    except (OSError, UnicodeError) as error:
        reason = f"viewport_state_io:{type(error).__name__}"
        latch_stop(stopped_path, reason)
        raise RuntimeError(reason) from error
    if state is None or _OBSERVABLE_STATE.fullmatch(state):
        return
    if is_owned_unobservable_state(state):
        raise RuntimeError(state)
    latch_stop(stopped_path, "viewport_state_invalid")
    raise RuntimeError("viewport_state_invalid")


def latch_stop(stopped_path: Path, reason: str) -> bool:
    """Durably create STOPPED once; an existing reason always wins."""
    try:
        with stopped_path.open("x", encoding="utf-8") as handle:
            handle.write(reason)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        return False
    return True


def parse_normalized_rect(values: list[float]) -> tuple[float, float, float, float]:
    if len(values) != 4:
        raise ValueError("target requires four normalized values")
    left, top, right, bottom = map(float, values)
    if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
        raise ValueError("target must remain inside normalized viewport")
    return left, top, right, bottom


def latest_observation(root: Path) -> Observation:
    records = [
        json.loads(line)
        for line in (root / "observations.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    if not records:
        raise RuntimeError("session has no observations")
    item = records[-1]
    return Observation(
        observation_id=item["observation_id"],
        screen=ScreenKind(item["screen"]),
        confidence=float(item["confidence"]),
        frame_sha256=item["frame_sha256"],
        viewport=Rect(*item["viewport"]),
        prohibited_regions=tuple(Rect(*values) for values in item.get("prohibited_regions", [])),
        labels=tuple(item["labels"]),
    )
