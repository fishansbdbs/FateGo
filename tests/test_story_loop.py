from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import numpy as np

from fgo_guardian.agent_models import ScreenKind
from fgo_guardian.battle import BattleDecisionEngine
from fgo_guardian.controller import AutomationController, RunState, StopReason
from fgo_guardian.models import Rect
from fgo_guardian.policy import PolicyGate
from fgo_guardian.quest_planner import QuestMode, QuestPlanner
from fgo_guardian.recognition import Recognition
from fgo_guardian.story_loop import (
    DefaultTransitionVerifier,
    DirectPolicyAuthorizer,
    FrameObservation,
    LoopOutcome,
    LoopJournal,
    StopCondition,
    StoryLoop,
)
from fgo_guardian.viewport_mapper import ViewportMapping


MAPPING = ViewportMapping(Rect(0, 0, 640, 360), 0, 640)


def _recognition(screen: ScreenKind, digest: str, **anchors: Rect) -> Recognition:
    return Recognition(
        screen,
        0.99,
        MappingProxyType(anchors),
        MappingProxyType({}),
        ("test",),
        digest * 64,
    )


class _Observer:
    def __init__(self, count: int) -> None:
        self.frames = [FrameObservation(np.full((360, 640, 3), index, dtype=np.uint8), MAPPING) for index in range(count)]
        self.calls = 0

    def capture(self) -> FrameObservation:
        frame = self.frames[self.calls]
        self.calls += 1
        return frame


class _Recognizer:
    def __init__(self, states: list[Recognition]) -> None:
        self.states = states
        self.calls = 0

    def recognize(self, frame, mapping) -> Recognition:
        del frame, mapping
        state = self.states[self.calls]
        self.calls += 1
        return state


class _Executor:
    def __init__(self) -> None:
        self.calls = []

    def execute_one(self, token, state, proposal) -> None:
        self.calls.append((token, state, proposal))


class _NoBattleProvider:
    def build(self, frame, mapping, recognition):
        raise AssertionError("battle provider should not be used")


class _NoRecoveryProvider:
    def build(self, recognition, frame, mapping):
        raise AssertionError("recovery provider should not be used")


class _NoRecoveryManager:
    def handle(self, state, frame, mapping):
        raise AssertionError("recovery manager should not be used")


def _loop(
    controller,
    observer,
    recognizer,
    executor,
    *,
    stop_after: int = 99,
    journal: LoopJournal | None = None,
) -> StoryLoop:
    return StoryLoop(
        controller=controller,
        observer=observer,
        recognizer=recognizer,
        quest_planner=QuestPlanner(QuestMode.STORY),
        battle_provider=_NoBattleProvider(),
        battle_engine=BattleDecisionEngine(),
        recovery_provider=_NoRecoveryProvider(),
        recovery_manager=_NoRecoveryManager(),
        authorizer=DirectPolicyAuthorizer(PolicyGate(0.92)),
        executor=executor,
        verifier=DefaultTransitionVerifier(),
        stop_condition=StopCondition(maximum_quests=stop_after),
        journal=journal,
    )


def test_manual_pause_wins_before_capture_or_executor_call() -> None:
    controller = AutomationController()
    controller.start()
    controller.pause()
    observer = _Observer(1)
    executor = _Executor()
    loop = _loop(
        controller,
        observer,
        _Recognizer([_recognition(ScreenKind.STORY, "a", skip=Rect(500, 10, 630, 80))]),
        executor,
    )

    assert loop.tick() is LoopOutcome.PAUSED
    assert observer.calls == 0
    assert executor.calls == []


def test_one_action_is_executed_then_verified_from_a_fresh_frame() -> None:
    controller = AutomationController()
    controller.start()
    observer = _Observer(2)
    executor = _Executor()
    states = [
        _recognition(ScreenKind.STORY, "a", skip=Rect(500, 10, 630, 80)),
        _recognition(
            ScreenKind.SKIP_CONFIRM,
            "b",
            prompt=Rect(150, 100, 500, 220),
            yes=Rect(350, 240, 520, 320),
        ),
    ]
    loop = _loop(controller, observer, _Recognizer(states), executor)

    assert loop.tick() is LoopOutcome.ACTION_COMPLETED
    assert len(executor.calls) == 1
    assert loop.pending_transition is not None
    assert loop.tick() is LoopOutcome.ACTION_COMPLETED
    assert len(executor.calls) == 2
    assert loop.verified_transitions == 1


def test_result_to_map_increments_quest_count_and_applies_stop_condition() -> None:
    controller = AutomationController()
    controller.start()
    observer = _Observer(2)
    executor = _Executor()
    states = [
        _recognition(ScreenKind.QUEST_RESULT, "c", next=Rect(450, 270, 630, 350)),
        _recognition(
            ScreenKind.TUTORIAL_MAP,
            "d",
            close=Rect(10, 10, 120, 70),
            menu=Rect(500, 280, 630, 350),
        ),
    ]
    loop = _loop(controller, observer, _Recognizer(states), executor, stop_after=1)

    assert loop.tick() is LoopOutcome.ACTION_COMPLETED
    assert loop.tick() is LoopOutcome.CONFIGURED_STOP
    assert loop.completed_quests == 1
    assert len(executor.calls) == 1
    assert controller.snapshot().state is RunState.STOPPED
    assert controller.snapshot().reason is StopReason.CONFIGURED_STOP


def test_stale_same_frame_verification_pauses_before_another_action() -> None:
    controller = AutomationController()
    controller.start()
    observer = _Observer(2)
    executor = _Executor()
    state = _recognition(ScreenKind.STORY, "a", skip=Rect(500, 10, 630, 80))
    loop = _loop(controller, observer, _Recognizer([state, state]), executor)

    assert loop.tick() is LoopOutcome.ACTION_COMPLETED
    assert loop.tick() is LoopOutcome.PAUSED
    assert len(executor.calls) == 1
    assert controller.snapshot().state is RunState.PAUSED


def test_loop_journal_records_observation_action_and_verification(tmp_path: Path) -> None:
    controller = AutomationController()
    controller.start()
    executor = _Executor()
    states = [
        _recognition(ScreenKind.STORY, "a", skip=Rect(500, 10, 630, 80)),
        _recognition(
            ScreenKind.SKIP_CONFIRM,
            "b",
            prompt=Rect(150, 100, 500, 220),
            yes=Rect(350, 240, 520, 320),
        ),
    ]
    journal_path = tmp_path / "run.jsonl"
    loop = _loop(
        controller,
        _Observer(2),
        _Recognizer(states),
        executor,
        journal=LoopJournal(journal_path),
    )

    loop.tick()
    loop.tick()

    events = [line.split('"event":"', 1)[1].split('"', 1)[0] for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert events == ["observation", "action", "observation", "verification", "action"]
