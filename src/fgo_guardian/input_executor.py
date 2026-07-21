from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import secrets
from threading import RLock
from time import monotonic
from typing import Callable, Protocol

import win32api
import win32con

from .agent_models import ActionProposal, Observation
from .controller import AutomationController, RunInvalidatedError, RunState
from .models import Baseline, GuardReport
from .policy import PolicyGate


class GuardianLike(Protocol):
    def check(self, baseline: Baseline) -> GuardReport: ...


class MouseLike(Protocol):
    def click(self, x: int, y: int) -> None: ...


class CurrentActionVerifier(Protocol):
    def verify(self, state: Observation, proposal: ActionProposal) -> bool: ...

    def still_current(self, state: Observation, proposal: ActionProposal) -> bool: ...


class RunLease:
    """Run-scoped cancellation gate that is atomic with the final input call."""

    def __init__(self) -> None:
        self._active = True
        self._lock = RLock()

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def invalidate(self) -> None:
        with self._lock:
            self._active = False

    def perform_if_active(self, action: Callable[[], None]) -> bool:
        with self._lock:
            if not self._active:
                return False
            action()
            return True


class StandardMouse:
    """Visible standard Windows cursor movement and one left-button click."""

    def click(self, x: int, y: int) -> None:
        win32api.SetCursorPos((x, y))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)


@dataclass(frozen=True, slots=True)
class _TokenBinding:
    frame_sha256: str
    proposal_sha256: str
    controller_revision: int
    expires_at: float


class LiveTokenAuthority:
    """Issues short-lived, revision-bound, one-shot policy tokens."""

    def __init__(
        self,
        policy: PolicyGate,
        controller: AutomationController,
        *,
        ttl_seconds: float,
        lease: RunLease | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("live token TTL must be positive")
        self.policy = policy
        self.controller = controller
        self.ttl_seconds = ttl_seconds
        self.lease = lease or RunLease()
        self._tokens: dict[str, _TokenBinding] = {}
        self._lock = RLock()

    @staticmethod
    def _proposal_digest(proposal: ActionProposal) -> str:
        payload = {
            "observation_id": proposal.observation_id,
            "kind": proposal.kind.value,
            "target": None if proposal.target is None else proposal.target.as_tuple(),
            "labels": proposal.labels,
            "resource": proposal.resource.value,
            "resource_cost": proposal.resource_cost,
            "mandatory": proposal.mandatory,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()

    def authorize(self, state: Observation, proposal: ActionProposal) -> str:
        if not self.lease.is_active():
            raise RunInvalidatedError("run is no longer active")
        snapshot = self.controller.snapshot()
        if snapshot.state is not RunState.RUNNING:
            raise PermissionError("controller is not running")
        decision = self.policy.evaluate(state, proposal)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if not self.lease.is_active():
            raise RunInvalidatedError("run is no longer active")
        current = self.controller.snapshot()
        if current.revision != snapshot.revision:
            raise RunInvalidatedError("controller run changed during authorization")
        if current.state is not RunState.RUNNING:
            raise PermissionError("controller is not running")
        token = secrets.token_urlsafe(32)
        binding = _TokenBinding(
            frame_sha256=state.frame_sha256,
            proposal_sha256=self._proposal_digest(proposal),
            controller_revision=snapshot.revision,
            expires_at=monotonic() + self.ttl_seconds,
        )
        with self._lock:
            while token in self._tokens:
                token = secrets.token_urlsafe(32)
            self._tokens[token] = binding
        return token

    def consume(self, token: str, state: Observation, proposal: ActionProposal) -> None:
        if not self.lease.is_active():
            raise RunInvalidatedError("run is no longer active")
        with self._lock:
            binding = self._tokens.get(token)
            if binding is None:
                raise PermissionError("authorization token is missing or already consumed")
            if binding.expires_at < monotonic():
                del self._tokens[token]
                raise PermissionError("authorization token expired")
            if binding.frame_sha256 != state.frame_sha256:
                raise PermissionError("authorization token frame does not match the observation")
            if binding.proposal_sha256 != self._proposal_digest(proposal):
                raise PermissionError("authorization token proposal does not match")
            snapshot = self.controller.snapshot()
            if snapshot.revision != binding.controller_revision:
                raise RunInvalidatedError("authorization token belongs to an inactive run")
            if snapshot.state is not RunState.RUNNING:
                raise PermissionError("controller is not running")
            del self._tokens[token]


class GuardedInputExecutor:
    def __init__(
        self,
        controller: AutomationController,
        tokens: LiveTokenAuthority,
        guardian: GuardianLike,
        baseline: Baseline,
        mouse: MouseLike,
        current_action: CurrentActionVerifier,
        lease: RunLease,
    ) -> None:
        self.controller = controller
        self.tokens = tokens
        self.guardian = guardian
        self.baseline = baseline
        self.mouse = mouse
        self.current_action = current_action
        self.lease = lease

    def _pause_current_run(self) -> None:
        if not self.lease.perform_if_active(self.controller.pause):
            raise RunInvalidatedError("run is no longer active")

    def _safe_report(self) -> GuardReport:
        report = self.guardian.check(self.baseline)
        if not report.safe or report.snapshot is None:
            self._pause_current_run()
            reason = ",".join(report.reasons) or "window safety check failed"
            raise PermissionError(reason)
        return report

    @staticmethod
    def _inside(inner, outer) -> bool:
        return (
            outer.left <= inner.left < inner.right <= outer.right
            and outer.top <= inner.top < inner.bottom <= outer.bottom
        )

    def execute_one(
        self,
        token: str,
        state: Observation,
        proposal: ActionProposal,
    ) -> None:
        if not self.lease.is_active():
            raise RunInvalidatedError("run is no longer active")
        if self.controller.snapshot().state is not RunState.RUNNING:
            raise PermissionError("controller is not running")
        if proposal.target is None:
            raise PermissionError("visible input requires a verified target")
        if not self._inside(proposal.target, state.viewport):
            raise PermissionError("target is outside the recognized Android viewport")
        if any(proposal.target.intersects(blocked) for blocked in state.prohibited_regions):
            raise PermissionError("target intersects a prohibited region")

        first = self._safe_report()
        self.tokens.consume(token, state, proposal)
        try:
            current = self.current_action.verify(state, proposal)
        except Exception as error:
            self._pause_current_run()
            raise PermissionError("fresh visible-action verification failed") from error
        if not current:
            self._pause_current_run()
            raise PermissionError("visible action is stale on the fresh captured frame")
        second = self._safe_report()
        if second.snapshot != first.snapshot:
            self._pause_current_run()
            raise PermissionError("window snapshot changed between input checks")
        if self.controller.snapshot().state is not RunState.RUNNING:
            raise PermissionError("controller is not running")
        try:
            final_current = self.current_action.still_current(state, proposal)
        except Exception as error:
            self._pause_current_run()
            raise PermissionError("final visible-action verification failed") from error
        if not final_current:
            self._pause_current_run()
            raise PermissionError("target pixels changed during verification")

        snapshot = second.snapshot
        assert snapshot is not None
        if state.viewport.right > snapshot.outer_rect.width or state.viewport.bottom > snapshot.outer_rect.height:
            self._pause_current_run()
            raise PermissionError("recognized viewport no longer fits the LDPlayer window")
        relative_x = proposal.target.left + proposal.target.width // 2
        relative_y = proposal.target.top + proposal.target.height // 2
        desktop_x = snapshot.outer_rect.left + relative_x
        desktop_y = snapshot.outer_rect.top + relative_y
        clicked = False

        def click_if_leased() -> None:
            nonlocal clicked
            clicked = self.lease.perform_if_active(
                lambda: self.mouse.click(desktop_x, desktop_y)
            )

        if not self.controller.perform_if_running(click_if_leased):
            raise PermissionError("controller is not running")
        if not clicked:
            raise RunInvalidatedError("run is no longer active")

        self._safe_report()
