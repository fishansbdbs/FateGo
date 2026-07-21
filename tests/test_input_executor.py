from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

import pytest

from fgo_guardian.agent_models import ActionKind, ActionProposal, Observation, ResourceKind, ScreenKind
from fgo_guardian.controller import AutomationController, RunInvalidatedError, RunState, StopReason
from fgo_guardian.input_executor import GuardedInputExecutor, LiveTokenAuthority, RunLease
from fgo_guardian.models import Baseline, GuardReport, Rect, WindowSnapshot
from fgo_guardian.policy import PolicyGate


def _snapshot() -> WindowSnapshot:
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
        minimized=False,
        foreground=True,
    )


def _baseline() -> Baseline:
    snapshot = _snapshot()
    return Baseline(
        hwnd=snapshot.hwnd,
        pid=snapshot.pid,
        process_path=snapshot.process_path,
        title=snapshot.title,
        geometry_signature=snapshot.geometry_signature(),
        android_resolution=(1920, 1080),
        android_dpi=280,
        orientation="landscape",
    )


def _observation(digest: str = "a" * 64) -> Observation:
    return Observation(
        observation_id=digest,
        screen=ScreenKind.STORY,
        confidence=0.99,
        frame_sha256=digest,
        viewport=Rect(55, 40, 1819, 1032),
        prohibited_regions=(),
        labels=("skip",),
    )


def _proposal(digest: str = "a" * 64) -> ActionProposal:
    return ActionProposal(
        observation_id=digest,
        kind=ActionKind.SKIP_STORY,
        target=Rect(1537, 70, 1784, 189),
        labels=("Skip",),
        resource=ResourceKind.NONE,
        resource_cost=0,
        mandatory=False,
    )


class _Guardian:
    def __init__(self) -> None:
        self.reports = [GuardReport(True, (), _snapshot())] * 3
        self.calls = 0

    def check(self, baseline) -> GuardReport:
        del baseline
        result = self.reports[min(self.calls, len(self.reports) - 1)]
        self.calls += 1
        return result


class _Mouse:
    def __init__(self) -> None:
        self.clicks = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class _CurrentActionVerifier:
    def __init__(self, current: bool = True, final_current: bool = True) -> None:
        self.current = current
        self.final_current = final_current
        self.calls = []

    def verify(self, state, proposal) -> bool:
        self.calls.append((state, proposal))
        return self.current

    def still_current(self, state, proposal) -> bool:
        self.calls.append(("final", state, proposal))
        return self.final_current


class _FailingCurrentActionVerifier:
    def verify(self, state, proposal) -> bool:
        del state, proposal
        raise RuntimeError("capture failed")

    def still_current(self, state, proposal) -> bool:
        del state, proposal
        raise AssertionError("final check must not run after verification failure")


class _BlockingCurrentActionVerifier:
    def __init__(self) -> None:
        self.entered = Event()
        self.release = Event()

    def verify(self, state, proposal) -> bool:
        del state, proposal
        self.entered.set()
        assert self.release.wait(2.0)
        return False

    def still_current(self, state, proposal) -> bool:
        del state, proposal
        raise AssertionError("final check must not run after stale semantic verification")


def _executor(*, current: bool = True, final_current: bool = True):
    controller = AutomationController()
    controller.start()
    lease = RunLease()
    authority = LiveTokenAuthority(
        PolicyGate(0.92),
        controller,
        ttl_seconds=2.0,
        lease=lease,
    )
    guardian = _Guardian()
    mouse = _Mouse()
    verifier = _CurrentActionVerifier(current, final_current)
    executor = GuardedInputExecutor(
        controller,
        authority,
        guardian,
        _baseline(),
        mouse,
        verifier,
        lease,
    )
    return controller, authority, guardian, mouse, executor


def test_executor_emits_exactly_one_absolute_click_for_current_safe_state() -> None:
    _, authority, guardian, mouse, executor = _executor()
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)

    executor.execute_one(token, state, proposal)

    assert mouse.clicks == [(-260, 129)]
    assert guardian.calls == 3


def test_executor_rejects_stale_observation_without_mouse_input() -> None:
    _, authority, _, mouse, executor = _executor()
    current = _observation()
    proposal = _proposal()
    token = authority.authorize(current, proposal)
    stale = _observation("b" * 64)

    with pytest.raises(PermissionError, match="frame"):
        executor.execute_one(token, stale, _proposal("b" * 64))

    assert mouse.clicks == []


def test_executor_recaptures_and_rejects_a_stale_visible_action() -> None:
    controller, authority, _, mouse, executor = _executor(current=False)
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)

    with pytest.raises(PermissionError, match="visible action is stale"):
        executor.execute_one(token, state, proposal)

    assert mouse.clicks == []
    assert controller.snapshot().state is RunState.PAUSED


def test_executor_rejects_pixels_that_change_during_semantic_verification() -> None:
    controller, authority, _, mouse, executor = _executor(final_current=False)
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)

    with pytest.raises(PermissionError, match="changed during verification"):
        executor.execute_one(token, state, proposal)

    assert mouse.clicks == []
    assert controller.snapshot().state is RunState.PAUSED


def test_invalidated_run_lease_blocks_authorization_and_input() -> None:
    controller, authority, _, mouse, executor = _executor()
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)
    executor.lease.invalidate()

    with pytest.raises(PermissionError, match="run is no longer active"):
        executor.execute_one(token, state, proposal)

    with pytest.raises(PermissionError, match="run is no longer active"):
        authority.authorize(state, proposal)
    assert mouse.clicks == []


def test_old_blocked_verifier_cannot_pause_a_restarted_run() -> None:
    controller, authority, _, mouse, executor = _executor()
    blocker = _BlockingCurrentActionVerifier()
    executor.current_action = blocker
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            executor.execute_one(token, state, proposal)
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=execute)
    worker.start()
    assert blocker.entered.wait(2.0)
    executor.lease.invalidate()
    controller.stop(StopReason.USER_STOP)
    controller.start()
    blocker.release.set()
    worker.join(2.0)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RunInvalidatedError)
    assert controller.snapshot().state is RunState.RUNNING
    assert mouse.clicks == []


def test_executor_pauses_when_fresh_visible_action_verification_fails() -> None:
    controller, authority, _, mouse, executor = _executor()
    executor.current_action = _FailingCurrentActionVerifier()
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)

    with pytest.raises(PermissionError, match="verification failed"):
        executor.execute_one(token, state, proposal)

    assert mouse.clicks == []
    assert controller.snapshot().state is RunState.PAUSED


def test_authorization_token_is_one_shot() -> None:
    _, authority, _, mouse, executor = _executor()
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)
    executor.execute_one(token, state, proposal)

    with pytest.raises(PermissionError, match="token"):
        executor.execute_one(token, state, proposal)

    assert len(mouse.clicks) == 1


def test_pause_after_authorization_wins_before_mouse_input() -> None:
    controller, authority, _, mouse, executor = _executor()
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)
    controller.pause()

    with pytest.raises(PermissionError, match="controller"):
        executor.execute_one(token, state, proposal)

    assert mouse.clicks == []


def test_unsafe_window_pauses_and_never_clicks() -> None:
    controller, authority, guardian, mouse, executor = _executor()
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)
    guardian.reports = [GuardReport(False, ("overlap",), _snapshot())]

    with pytest.raises(PermissionError, match="overlap"):
        executor.execute_one(token, state, proposal)

    assert mouse.clicks == []
    assert controller.snapshot().state is RunState.PAUSED


def test_post_click_safety_failure_pauses_for_the_next_action() -> None:
    controller, authority, guardian, mouse, executor = _executor()
    state = _observation()
    proposal = _proposal()
    token = authority.authorize(state, proposal)
    guardian.reports = [
        GuardReport(True, (), _snapshot()),
        GuardReport(True, (), _snapshot()),
        GuardReport(False, ("focus_lost",), _snapshot()),
    ]

    with pytest.raises(PermissionError, match="focus_lost"):
        executor.execute_one(token, state, proposal)

    assert len(mouse.clicks) == 1
    assert controller.snapshot().state is RunState.PAUSED


def test_live_token_authority_rejects_premium_resource_before_issue() -> None:
    controller, authority, _, _, _ = _executor()
    state = _observation()
    premium = ActionProposal(
        observation_id=state.observation_id,
        kind=ActionKind.RESTORE_AP,
        target=Rect(500, 300, 800, 500),
        labels=("Saint Quartz",),
        resource=ResourceKind.SAINT_QUARTZ,
        resource_cost=1,
        mandatory=False,
    )

    with pytest.raises(PermissionError, match="saint_quartz"):
        authority.authorize(state, premium)
    assert controller.snapshot().state is RunState.RUNNING
