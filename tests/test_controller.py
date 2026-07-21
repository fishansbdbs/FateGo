from __future__ import annotations

import threading

import pytest

from fgo_guardian.controller import (
    AutomationController,
    RunState,
    StopReason,
)


def test_controller_starts_disarmed_and_start_arms_a_new_run() -> None:
    controller = AutomationController()

    initial = controller.snapshot()
    assert initial.state is RunState.DISARMED
    assert initial.reason is None
    assert initial.revision == 0

    started = controller.start()
    assert started.state is RunState.RUNNING
    assert started.reason is None
    assert started.revision == 1


def test_pause_and_stop_prevent_the_next_action() -> None:
    controller = AutomationController()
    calls: list[str] = []

    controller.start()
    controller.pause()
    assert controller.step(lambda: calls.append("click")) is False

    controller.resume()
    assert controller.step(lambda: calls.append("click")) is True

    controller.stop(StopReason.USER_STOP)
    assert controller.step(lambda: calls.append("click")) is False
    assert calls == ["click"]


def test_stop_requires_a_new_start_and_emergency_stop_is_terminal() -> None:
    controller = AutomationController()
    controller.start()
    controller.stop(StopReason.USER_STOP)

    with pytest.raises(RuntimeError, match="paused"):
        controller.resume()

    restarted = controller.start()
    assert restarted.state is RunState.RUNNING

    emergency = controller.emergency_stop()
    assert emergency.state is RunState.EMERGENCY_STOPPED
    assert emergency.reason is StopReason.EMERGENCY_STOP

    with pytest.raises(RuntimeError, match="emergency"):
        controller.start()


def test_state_changes_are_thread_safe_and_revisioned() -> None:
    controller = AutomationController()
    controller.start()
    barrier = threading.Barrier(3)
    outcomes: list[RunState] = []

    def pause() -> None:
        barrier.wait()
        outcomes.append(controller.pause().state)

    def stop() -> None:
        barrier.wait()
        outcomes.append(controller.stop(StopReason.USER_STOP).state)

    pause_thread = threading.Thread(target=pause)
    stop_thread = threading.Thread(target=stop)
    pause_thread.start()
    stop_thread.start()
    barrier.wait()
    pause_thread.join(timeout=2)
    stop_thread.join(timeout=2)

    snapshot = controller.snapshot()
    assert snapshot.state in {RunState.PAUSED, RunState.STOPPED}
    assert snapshot.revision >= 2
    assert len(outcomes) == 2


def test_observers_receive_immutable_snapshots_after_transitions() -> None:
    controller = AutomationController()
    received = []
    controller.subscribe(received.append)

    controller.start()
    controller.pause()
    controller.resume()
    controller.stop(StopReason.CONFIGURED_STOP)

    assert [item.state for item in received] == [
        RunState.RUNNING,
        RunState.PAUSED,
        RunState.RUNNING,
        RunState.STOPPED,
    ]
    assert received[-1].reason is StopReason.CONFIGURED_STOP
