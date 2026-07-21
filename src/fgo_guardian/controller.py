from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Callable


class RunInvalidatedError(PermissionError):
    """Raised when work belongs to a live run that has been cancelled."""


class RunState(StrEnum):
    DISARMED = "DISARMED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"


class StopReason(StrEnum):
    USER_STOP = "USER_STOP"
    CONFIGURED_STOP = "CONFIGURED_STOP"
    UNKNOWN_SCREEN = "UNKNOWN_SCREEN"
    BATTLE_DEFEAT = "BATTLE_DEFEAT"
    POLICY_REJECTED = "POLICY_REJECTED"
    WINDOW_UNSAFE = "WINDOW_UNSAFE"
    EMERGENCY_STOP = "EMERGENCY_STOP"


@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    state: RunState
    reason: StopReason | None
    revision: int


@dataclass(frozen=True, slots=True)
class ActionPermit:
    revision: int


Observer = Callable[[ControllerSnapshot], None]


class AutomationController:
    """Thread-safe lifecycle gate for every autonomous gameplay action."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._state = RunState.DISARMED
        self._reason: StopReason | None = None
        self._revision = 0
        self._observers: list[Observer] = []

    def snapshot(self) -> ControllerSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def subscribe(self, observer: Observer) -> None:
        with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)

    def start(self) -> ControllerSnapshot:
        with self._lock:
            if self._state is RunState.EMERGENCY_STOPPED:
                raise RuntimeError("emergency stop is terminal for this controller")
            snapshot, observers = self._transition_locked(RunState.RUNNING, None)
        self._notify(observers, snapshot)
        return snapshot

    def pause(self) -> ControllerSnapshot:
        with self._lock:
            if self._state is not RunState.RUNNING:
                return self._snapshot_locked()
            snapshot, observers = self._transition_locked(RunState.PAUSED, None)
        self._notify(observers, snapshot)
        return snapshot

    def resume(self) -> ControllerSnapshot:
        with self._lock:
            if self._state is not RunState.PAUSED:
                raise RuntimeError("controller is not paused")
            snapshot, observers = self._transition_locked(RunState.RUNNING, None)
        self._notify(observers, snapshot)
        return snapshot

    def stop(self, reason: StopReason = StopReason.USER_STOP) -> ControllerSnapshot:
        if reason is StopReason.EMERGENCY_STOP:
            return self.emergency_stop()
        with self._lock:
            if self._state is RunState.EMERGENCY_STOPPED:
                return self._snapshot_locked()
            snapshot, observers = self._transition_locked(RunState.STOPPED, reason)
        self._notify(observers, snapshot)
        return snapshot

    def emergency_stop(self) -> ControllerSnapshot:
        with self._lock:
            snapshot, observers = self._transition_locked(
                RunState.EMERGENCY_STOPPED,
                StopReason.EMERGENCY_STOP,
            )
        self._notify(observers, snapshot)
        return snapshot

    def may_act(self) -> bool:
        with self._lock:
            return self._state is RunState.RUNNING

    def issue_permit(self) -> ActionPermit | None:
        with self._lock:
            if self._state is not RunState.RUNNING:
                return None
            return ActionPermit(self._revision)

    def permit_is_current(self, permit: ActionPermit) -> bool:
        with self._lock:
            return (
                self._state is RunState.RUNNING
                and permit.revision == self._revision
            )

    def require_running(self, permit: ActionPermit | None = None) -> None:
        with self._lock:
            if permit is not None and permit.revision != self._revision:
                raise RunInvalidatedError("action permit belongs to an inactive run")
            if self._state is not RunState.RUNNING:
                raise PermissionError(f"controller is {self._state.value.lower()}")

    def step(self, stepper: Callable[[], None]) -> bool:
        permit = self.issue_permit()
        if permit is None:
            return False
        self.require_running(permit)
        stepper()
        return True

    def perform_if_running(self, action: Callable[[], None]) -> bool:
        """Keep lifecycle transitions atomic with a very short external action."""
        with self._lock:
            if self._state is not RunState.RUNNING:
                return False
            action()
            return True

    def _snapshot_locked(self) -> ControllerSnapshot:
        return ControllerSnapshot(self._state, self._reason, self._revision)

    def _transition_locked(
        self,
        state: RunState,
        reason: StopReason | None,
    ) -> tuple[ControllerSnapshot, tuple[Observer, ...]]:
        if state is self._state and reason is self._reason:
            return self._snapshot_locked(), ()
        self._state = state
        self._reason = reason
        self._revision += 1
        return self._snapshot_locked(), tuple(self._observers)

    @staticmethod
    def _notify(
        observers: tuple[Observer, ...],
        snapshot: ControllerSnapshot,
    ) -> None:
        for observer in observers:
            observer(snapshot)
