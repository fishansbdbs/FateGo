from __future__ import annotations

from pathlib import Path
from threading import Event, Thread as NativeThread
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pytest
import fgo_guardian.live_runtime as live_runtime_module

from fgo_guardian.agent_models import ActionKind, ActionProposal, Observation, ResourceKind, ScreenKind
from fgo_guardian.controller import AutomationController, RunState, StopReason
from fgo_guardian.input_executor import RunLease
from fgo_guardian.live_runtime import LiveActionVerifier, LiveObserver, LiveRuntime
from fgo_guardian.models import Rect
from fgo_guardian.quest_planner import QuestMode
from fgo_guardian.recognition import Recognition
from fgo_guardian.story_loop import LoopOutcome
from fgo_guardian.viewport_mapper import ViewportMapping


def _capture_error(errors: list[BaseException], action) -> None:
    try:
        action()
    except BaseException as error:
        errors.append(error)


class _FailingLoop:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str]] = []

    def tick(self):
        raise RuntimeError("boom")

    def record_runtime_error(self, error: BaseException) -> None:
        self.errors.append((type(error).__name__, str(error)))


class _CountingLoop:
    def __init__(self) -> None:
        self.calls = 0

    def tick(self):
        self.calls += 1
        return "unused"


class _BlockingLoop:
    def __init__(self, controller: AutomationController, *, mutate_after_release: bool) -> None:
        self.controller = controller
        self.mutate_after_release = mutate_after_release
        self.entered = Event()
        self.release = Event()

    def tick(self):
        self.entered.set()
        assert self.release.wait(3.0)
        if self.mutate_after_release:
            self.controller.pause()
        return LoopOutcome.STOPPED

    def record_runtime_error(self, error: BaseException) -> None:
        raise AssertionError(f"unexpected worker error: {error}")


def test_worker_records_an_error_before_pausing() -> None:
    controller = AutomationController()
    runtime = LiveRuntime(
        controller,
        Path(__file__).parents[1],
        mode=QuestMode.STORY,
        maximum_quests=1,
    )
    loop = _FailingLoop()
    runtime._loop = loop
    controller.start()

    runtime._worker()

    assert controller.snapshot().state is RunState.STOPPED
    assert controller.snapshot().reason is StopReason.WINDOW_UNSAFE
    assert loop.errors == [("RuntimeError", "boom")]
    assert runtime.last_error == "RuntimeError: boom"


def test_worker_from_an_old_run_generation_exits_without_ticking() -> None:
    controller = AutomationController()
    runtime = LiveRuntime(
        controller,
        Path(__file__).parents[1],
        mode=QuestMode.STORY,
        maximum_quests=None,
    )
    loop = _CountingLoop()
    runtime._run_generation = 2
    controller.start()

    runtime._worker(1, loop)

    assert loop.calls == 0
    assert controller.snapshot().state is RunState.RUNNING


def test_stop_invalidates_the_active_run_lease_before_rearming() -> None:
    controller = AutomationController()
    runtime = LiveRuntime(
        controller,
        Path(__file__).parents[1],
        mode=QuestMode.STORY,
        maximum_quests=None,
    )
    lease = RunLease()
    runtime._active_lease = lease
    controller.start()

    runtime.stop()

    assert lease.is_active() is False
    assert controller.snapshot().state is RunState.STOPPED


def test_worker_start_failure_is_terminal_and_invalidates_the_run(monkeypatch) -> None:
    controller = AutomationController()
    runtime = LiveRuntime(
        controller,
        Path(__file__).parents[1],
        mode=QuestMode.STORY,
        maximum_quests=None,
    )
    runtime._prepare = lambda lease: _CountingLoop()

    class _FailingThread:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def start(self) -> None:
            raise RuntimeError("thread start failed")

    monkeypatch.setattr(live_runtime_module, "Thread", _FailingThread)

    with pytest.raises(RuntimeError, match="thread start failed"):
        runtime.start()

    assert controller.snapshot().state is RunState.STOPPED
    assert controller.snapshot().reason is StopReason.WINDOW_UNSAFE
    assert runtime._active_lease is not None
    assert runtime._active_lease.is_active() is False
    assert runtime._worker_thread is None


def test_restart_waits_for_an_inflight_old_tick_before_rearming() -> None:
    controller = AutomationController()
    runtime = LiveRuntime(
        controller,
        Path(__file__).parents[1],
        mode=QuestMode.STORY,
        maximum_quests=None,
    )
    old_lease = RunLease()
    old_loop = _BlockingLoop(controller, mutate_after_release=True)
    runtime._run_generation = 1
    runtime._active_lease = old_lease
    runtime._loop = old_loop
    controller.start()
    old_worker = NativeThread(
        target=runtime._worker,
        args=(1, old_loop, old_lease),
        daemon=True,
    )
    runtime._worker_thread = old_worker
    old_worker.start()
    assert old_loop.entered.wait(2.0)
    runtime.stop()

    new_loop = _BlockingLoop(controller, mutate_after_release=False)
    prepared = Event()

    def prepare(lease) -> _BlockingLoop:
        del lease
        prepared.set()
        return new_loop

    runtime._prepare = prepare
    errors: list[BaseException] = []

    def restart() -> None:
        try:
            runtime.start()
        except BaseException as error:
            errors.append(error)

    starter = NativeThread(target=restart, daemon=True)
    starter.start()
    overlapped = prepared.wait(0.2)
    old_loop.release.set()
    assert prepared.wait(2.0)
    assert new_loop.entered.wait(2.0)
    starter.join(2.0)

    assert overlapped is False
    assert errors == []
    assert controller.snapshot().state is RunState.RUNNING

    runtime.stop()
    new_loop.release.set()
    if runtime._worker_thread is not None:
        runtime._worker_thread.join(2.0)


def test_stop_cancels_background_startup_before_controller_rearm() -> None:
    controller = AutomationController()
    runtime = LiveRuntime(
        controller,
        Path(__file__).parents[1],
        mode=QuestMode.STORY,
        maximum_quests=None,
    )
    preparing = Event()
    release = Event()

    def prepare(lease):
        del lease
        preparing.set()
        assert release.wait(3.0)
        return _CountingLoop()

    runtime._prepare = prepare
    cancellation = Event()
    start_errors: list[BaseException] = []
    stop_errors: list[BaseException] = []
    starter = NativeThread(
        target=lambda: _capture_error(
            start_errors,
            lambda: runtime.start(cancellation),
        ),
        daemon=True,
    )
    starter.start()
    assert preparing.wait(2.0)
    stopper = NativeThread(
        target=lambda: _capture_error(stop_errors, runtime.stop),
        daemon=True,
    )
    stopper.start()
    assert cancellation.wait(2.0)
    assert controller.snapshot().state is RunState.STOPPED
    release.set()
    starter.join(2.0)
    stopper.join(2.0)

    assert start_errors == []
    assert stop_errors == []
    assert controller.snapshot().state is RunState.STOPPED
    assert runtime._worker_thread is None
    assert runtime._active_lease is not None
    assert runtime._active_lease.is_active() is False


class _Capture:
    def capture(self, baseline):
        del baseline
        return SimpleNamespace(image=np.zeros((360, 640, 3), dtype=np.uint8))


class _Mappings:
    def __init__(self, values) -> None:
        self.values = iter(values)

    def locate(self, image):
        del image
        value = next(self.values)
        if isinstance(value, BaseException):
            raise value
        return value


class _FreshObserver:
    def __init__(self, mapping) -> None:
        self.mapping = mapping
        self.calls = 0

    def capture(self):
        self.calls += 1
        return SimpleNamespace(
            image=np.zeros((360, 640, 3), dtype=np.uint8),
            mapping=self.mapping,
        )


class _SequenceObserver:
    def __init__(self, mapping, images) -> None:
        self.mapping = mapping
        self.images = iter(images)

    def capture(self):
        return SimpleNamespace(image=next(self.images), mapping=self.mapping)


class _FreshRecognizer:
    def __init__(self, recognition) -> None:
        self.recognition = recognition

    def recognize(self, frame, mapping):
        del frame, mapping
        return self.recognition


class _FreshPlanner:
    def __init__(self, proposal) -> None:
        self.proposal = proposal

    def plan(self, recognition):
        del recognition
        return self.proposal


def test_observer_reuses_fixed_mapping_only_while_edges_are_unobservable() -> None:
    expected = ViewportMapping(Rect(0, 0, 640, 360), 0, 640)
    changed = ViewportMapping(Rect(1, 0, 640, 360), 0, 640)
    observer = LiveObserver(
        _Capture(),
        object(),
        _Mappings((expected, ValueError("toolbar edge is too weak"), changed)),
    )

    assert observer.capture().mapping == expected
    assert observer.capture().mapping == expected
    with pytest.raises(ValueError, match="viewport mapping changed"):
        observer.capture()


def test_live_action_verifier_recaptures_and_requires_the_same_intent() -> None:
    mapping = ViewportMapping(Rect(0, 0, 640, 360), 0, 640)
    target = Rect(500, 10, 630, 80)
    proposal = ActionProposal(
        "old-frame",
        ActionKind.SKIP_STORY,
        target,
        ("Skip", "anchor:skip"),
        ResourceKind.NONE,
        0,
        False,
    )
    recognition = Recognition(
        ScreenKind.STORY,
        0.99,
        MappingProxyType({"skip": target}),
        MappingProxyType({}),
        ("fresh",),
        "b" * 64,
    )
    observer = _FreshObserver(mapping)
    recognizer = _FreshRecognizer(recognition)
    verifier = LiveActionVerifier(
        observer,
        recognizer,
        _FreshPlanner(proposal),
        object(),
        object(),
    )
    state = Observation(
        "old-frame",
        ScreenKind.STORY,
        0.99,
        "a" * 64,
        mapping.viewport,
        (),
        ("skip",),
    )

    assert verifier.verify(state, proposal) is True
    assert observer.calls == 1

    recognizer.recognition = Recognition(
        ScreenKind.LOADING,
        0.99,
        MappingProxyType({}),
        MappingProxyType({}),
        ("fresh",),
        "c" * 64,
    )
    assert verifier.verify(state, proposal) is False


def test_live_action_verifier_rejects_target_pixels_changed_after_replan() -> None:
    mapping = ViewportMapping(Rect(0, 0, 640, 360), 0, 640)
    target = Rect(500, 10, 630, 80)
    proposal = ActionProposal(
        "old-frame",
        ActionKind.SKIP_STORY,
        target,
        ("Skip", "anchor:skip"),
        ResourceKind.NONE,
        0,
        False,
    )
    recognition = Recognition(
        ScreenKind.STORY,
        0.99,
        MappingProxyType({"skip": target}),
        MappingProxyType({}),
        ("fresh",),
        "b" * 64,
    )
    before = np.zeros((360, 640, 3), dtype=np.uint8)
    after = before.copy()
    after[target.top:target.bottom, target.left:target.right] = 255
    verifier = LiveActionVerifier(
        _SequenceObserver(mapping, (before, after)),
        _FreshRecognizer(recognition),
        _FreshPlanner(proposal),
        object(),
        object(),
    )
    state = Observation(
        "old-frame",
        ScreenKind.STORY,
        0.99,
        "a" * 64,
        mapping.viewport,
        (),
        ("skip",),
    )

    assert verifier.verify(state, proposal) is True
    assert verifier.still_current(state, proposal) is False
