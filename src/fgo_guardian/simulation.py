from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import numpy as np
from PIL import Image

from .agent_models import ActionKind, ActionProposal, ResourceKind, ScreenKind
from .battle import (
    AllyState,
    BattleDecisionEngine,
    BattlePhase,
    BattleState,
    CardColor,
    CommandCard,
    EnemyState,
    NoblePhantasm,
    SkillPurpose,
    SkillState,
    TargetStrategy,
)
from .controller import AutomationController, RunState
from .models import Rect
from .policy import PolicyGate
from .quest_planner import QuestMode, QuestPlanner
from .recognition import Recognition
from .replay import ReplaySession
from .story_loop import (
    DefaultTransitionVerifier,
    DirectPolicyAuthorizer,
    FrameObservation,
    LoopOutcome,
    StopCondition,
    StoryLoop,
)
from .viewport_mapper import ViewportMapping


SUPPORTED_ACTIONS = {
    ActionKind.SELECT_QUEST,
    ActionKind.SKIP_STORY,
    ActionKind.CONFIRM_SKIP,
    ActionKind.SELECT_DIALOGUE,
    ActionKind.SELECT_SUPPORT,
    ActionKind.START_QUEST,
    ActionKind.USE_SKILL,
    ActionKind.SELECT_TARGET,
    ActionKind.ATTACK,
    ActionKind.SELECT_COMMAND_CARD,
    ActionKind.SELECT_NOBLE_PHANTASM,
    ActionKind.COLLECT_RESULT,
}


@dataclass(frozen=True, slots=True)
class _FrameSpec:
    path: Path
    expected_sha256: str
    mapping: ViewportMapping


@dataclass(frozen=True, slots=True)
class SimulationReport:
    completed_quests: int
    executed_actions: int
    verified_transitions: int
    prohibited_actions: tuple[str, ...]
    unknown_actions: tuple[str, ...]


class _RecordedObserver:
    def __init__(self, frames: tuple[_FrameSpec, ...], root: Path) -> None:
        self.frames = frames
        self.root = root.resolve()
        self.index = 0

    def capture(self) -> FrameObservation:
        if self.index >= len(self.frames):
            raise RuntimeError("recording simulation exhausted its frames")
        spec = self.frames[self.index]
        self.index += 1
        path = spec.path.resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("recorded frame escapes the recording root")
        try:
            image = np.asarray(Image.open(path).convert("RGB"))
        except (FileNotFoundError, OSError) as error:
            raise ValueError(f"recorded frame is unavailable: {path.name}") from error
        if sha256(image.tobytes()).hexdigest() != spec.expected_sha256:
            raise ValueError(f"recorded frame hash mismatch: {path.name}")
        return FrameObservation(image, spec.mapping)


class _DeclaredRecognizer:
    """Replays immutable recorded labels; template accuracy has its own frame suite."""

    def __init__(self, states: tuple[Recognition, ...]) -> None:
        self.states = states
        self.index = 0

    def recognize(self, frame: np.ndarray, mapping: ViewportMapping) -> Recognition:
        del frame, mapping
        if self.index >= len(self.states):
            raise RuntimeError("recording simulation exhausted its recognized states")
        result = self.states[self.index]
        self.index += 1
        return result


class _RecordedBattleProvider:
    def __init__(self, states: Mapping[str, BattleState]) -> None:
        self.states = states

    def build(self, frame, mapping, recognition) -> BattleState:
        del frame, mapping
        try:
            return self.states[recognition.frame_sha256]
        except KeyError as error:
            raise RuntimeError("recording has no structured battle state for this action") from error


class _UnexpectedRecoveryProvider:
    def build(self, recognition, frame, mapping):
        del frame, mapping
        raise RuntimeError(f"unexpected recovery screen in completed replay: {recognition.screen.value}")


class _UnexpectedRecoveryManager:
    def handle(self, state, frame, mapping):
        del state, frame, mapping
        raise RuntimeError("recovery manager should not receive a completed replay segment")


class _SimulationExecutor:
    PROHIBITED_KINDS = {
        ActionKind.USE_COMMAND_SPELL,
        ActionKind.OPTIONAL_SUMMON,
        ActionKind.PURCHASE,
        ActionKind.ACCOUNT_ACTION,
        ActionKind.DELETE_DATA,
        ActionKind.CLEAR_CACHE,
    }
    PROHIBITED_RESOURCES = {
        ResourceKind.SAINT_QUARTZ,
        ResourceKind.COMMAND_SPELL,
        ResourceKind.SUMMON_TICKET,
        ResourceKind.PAID_CURRENCY,
    }

    def __init__(self, expected: tuple[ActionProposal, ...]) -> None:
        self.expected = expected
        self.calls: list[ActionProposal] = []
        self.mismatches: list[str] = []
        self.prohibited: list[str] = []

    def execute_one(self, token, state, proposal) -> None:
        del token, state
        index = len(self.calls)
        self.calls.append(proposal)
        if proposal.kind in self.PROHIBITED_KINDS or proposal.resource in self.PROHIBITED_RESOURCES:
            self.prohibited.append(f"{index}:{proposal.kind.value}:{proposal.resource.value}")
        if index >= len(self.expected):
            self.mismatches.append(f"{index}:unexpected:{proposal.kind.value}")
            return
        expected = self.expected[index]
        if proposal.kind is not expected.kind:
            self.mismatches.append(f"{index}:expected-{expected.kind.value}:got-{proposal.kind.value}")
        if proposal.target != expected.target:
            self.mismatches.append(f"{index}:{proposal.kind.value}:target-mismatch")


@dataclass(frozen=True, slots=True)
class _Scenario:
    frames: tuple[_FrameSpec, ...]
    recognitions: tuple[Recognition, ...]
    battle_states: Mapping[str, BattleState]
    expected_actions: tuple[ActionProposal, ...]


def _rect(values: object) -> Rect:
    if not isinstance(values, list) or len(values) != 4:
        raise ValueError("recorded action target is invalid")
    return Rect(*(int(value) for value in values))


def _mapping(record: dict[str, object]) -> ViewportMapping:
    viewport = _rect(record.get("viewport"))
    return ViewportMapping(viewport, viewport.top, viewport.right)


def _anchors(screen: ScreenKind, action: ActionProposal | None, viewport: Rect) -> Mapping[str, Rect]:
    target = action.target if action is not None else None
    anchors: dict[str, Rect] = {}
    if target is not None:
        name = {
            ScreenKind.STORY: "skip",
            ScreenKind.SKIP_CONFIRM: "yes",
            ScreenKind.DIALOGUE_CHOICE: "choice_1",
            ScreenKind.TUTORIAL_MAP: "main_quest",
            ScreenKind.SUPPORT_SELECT: "guest",
            ScreenKind.PARTY_CONFIRM: "start",
            ScreenKind.QUEST_RESULT: "next",
        }.get(screen)
        if name is not None:
            anchors[name] = target
    if screen is ScreenKind.STORY:
        anchors["dialogue_controls"] = Rect(viewport.right - 80, viewport.bottom - 180, viewport.right - 10, viewport.bottom - 10)
    elif screen is ScreenKind.SKIP_CONFIRM:
        anchors["prompt"] = Rect(viewport.left + 200, viewport.top + 100, viewport.right - 200, viewport.top + 260)
    elif screen is ScreenKind.TUTORIAL_MAP:
        anchors.setdefault("close", Rect(viewport.left + 10, viewport.top + 10, viewport.left + 120, viewport.top + 70))
        anchors.setdefault("menu", Rect(viewport.right - 140, viewport.bottom - 90, viewport.right - 10, viewport.bottom - 10))
    elif screen is ScreenKind.PARTY_CONFIRM:
        anchors["teapot_off"] = Rect(viewport.right - 570, viewport.bottom - 90, viewport.right - 490, viewport.bottom - 20)
    return MappingProxyType(anchors)


def _battle_state(action: ActionProposal) -> BattleState:
    ally_target = action.target or Rect(100, 100, 200, 200)
    ally = AllyState("recorded-ally", 5000, 5000, 100, ally_target, True)
    enemy = EnemyState("recorded-enemy", 10000, 10000, True, 1, Rect(600, 100, 900, 350))
    values = {
        "frame_sha256": action.observation_id,
        "phase": BattlePhase.ANIMATION,
        "wave": 1,
        "total_waves": 1,
        "turn": 1,
        "allies": (ally,),
        "enemies": (enemy,),
        "servant_skills": (),
        "master_skills": (),
        "noble_phantasms": (),
        "cards": (),
        "attack_target": None,
        "pending_target_strategy": None,
    }
    if action.kind is ActionKind.ATTACK:
        values.update(phase=BattlePhase.ACTION, attack_target=action.target)
    elif action.kind is ActionKind.SELECT_COMMAND_CARD:
        values.update(
            phase=BattlePhase.COMMAND_CARDS,
            cards=(CommandCard("recorded-card", "recorded-ally", action.target, CardColor.BUSTER, 0, 0, 1, False),),
        )
    elif action.kind is ActionKind.SELECT_NOBLE_PHANTASM:
        values.update(
            phase=BattlePhase.COMMAND_CARDS,
            noble_phantasms=(NoblePhantasm("recorded-np", "recorded-ally", action.target, True, False, 0),),
        )
    elif action.kind is ActionKind.SELECT_TARGET:
        values.update(phase=BattlePhase.TARGET_SELECTION, pending_target_strategy=TargetStrategy.LOWEST_HP_ALLY)
    elif action.kind is ActionKind.USE_SKILL:
        values.update(
            phase=BattlePhase.ACTION,
            servant_skills=(SkillState("recorded-skill", "recorded-ally", action.target, SkillPurpose.GENERIC_SAFE, 100, True, False, False),),
        )
    else:
        raise ValueError(f"unsupported recorded battle action: {action.kind.value}")
    return BattleState(**values)


class StorySimulation:
    def __init__(self, root: Path, scenario: _Scenario) -> None:
        self.root = root
        self.scenario = scenario

    @classmethod
    def from_recording(cls, root: str | Path) -> "StorySimulation":
        path = Path(root)
        replay = ReplaySession(path)
        observations = replay.observations()
        actions = [item for item in replay.actions() if item.get("decision", {}).get("allowed") is True]
        transitions = replay.transitions()
        observation_by_id = {str(item.get("observation_id")): item for item in observations}
        transition_by_token = {str(item.get("token")): item for item in transitions}

        candidates: list[tuple[int, int, dict[str, object]]] = []
        for end, action in enumerate(actions):
            token = action.get("token")
            transition = transition_by_token.get(str(token))
            if transition is None:
                continue
            before = observation_by_id.get(str(transition.get("before_id")))
            after = observation_by_id.get(str(transition.get("after_id")))
            if before is None or after is None:
                continue
            if before.get("screen") != ScreenKind.QUEST_RESULT.value or after.get("screen") != ScreenKind.TUTORIAL_MAP.value:
                continue
            for start in range(end, -1, -1):
                proposal = actions[start].get("proposal", {})
                before_start = observation_by_id.get(str(proposal.get("observation_id")))
                if (
                    before_start is not None
                    and before_start.get("screen") == ScreenKind.TUTORIAL_MAP.value
                    and proposal.get("kind") == ActionKind.SELECT_QUEST.value
                ):
                    kinds = {ActionKind(str(item["proposal"]["kind"])) for item in actions[start : end + 1]}
                    if kinds <= SUPPORTED_ACTIONS:
                        candidates.append((start, end, after))
                    break
        if not candidates:
            raise ValueError("recording does not contain a completed quest segment")
        start, end, final_record = candidates[-1]
        selected = actions[start : end + 1]

        frame_specs: list[_FrameSpec] = []
        recognitions: list[Recognition] = []
        expected_actions: list[ActionProposal] = []
        battle_states: dict[str, BattleState] = {}
        for item in selected:
            raw = item["proposal"]
            record = observation_by_id.get(str(raw["observation_id"]))
            if record is None:
                raise ValueError("recorded action references a missing observation")
            screen = ScreenKind(str(record["screen"]))
            mapping = _mapping(record)
            target = None if raw["target"] is None else _rect(raw["target"])
            proposal = ActionProposal(
                observation_id=str(record["frame_sha256"]),
                kind=ActionKind(str(raw["kind"])),
                target=target,
                labels=tuple(str(label) for label in raw["labels"]),
                resource=ResourceKind(str(raw["resource"])),
                resource_cost=int(raw["resource_cost"]),
                mandatory=bool(raw["mandatory"]),
            )
            image_path = path / str(record["image_path"])
            frame_specs.append(_FrameSpec(image_path, str(record["frame_sha256"]), mapping))
            recognition = Recognition(
                screen,
                float(record["confidence"]),
                _anchors(screen, proposal, mapping.viewport),
                MappingProxyType({}),
                ("recorded-label",),
                str(record["frame_sha256"]),
            )
            recognitions.append(recognition)
            expected_actions.append(proposal)
            if screen is ScreenKind.BATTLE:
                battle_states[recognition.frame_sha256] = _battle_state(proposal)

        final_mapping = _mapping(final_record)
        frame_specs.append(
            _FrameSpec(path / str(final_record["image_path"]), str(final_record["frame_sha256"]), final_mapping)
        )
        final_screen = ScreenKind(str(final_record["screen"]))
        recognitions.append(
            Recognition(
                final_screen,
                float(final_record["confidence"]),
                _anchors(final_screen, None, final_mapping.viewport),
                MappingProxyType({}),
                ("recorded-final-state",),
                str(final_record["frame_sha256"]),
            )
        )
        scenario = _Scenario(
            tuple(frame_specs),
            tuple(recognitions),
            MappingProxyType(battle_states),
            tuple(expected_actions),
        )
        return cls(path, scenario)

    def run(self, *, stop_after_quests: int = 1) -> SimulationReport:
        controller = AutomationController()
        controller.start()
        executor = _SimulationExecutor(self.scenario.expected_actions)
        loop = StoryLoop(
            controller=controller,
            observer=_RecordedObserver(self.scenario.frames, self.root),
            recognizer=_DeclaredRecognizer(self.scenario.recognitions),
            quest_planner=QuestPlanner(QuestMode.STORY),
            battle_provider=_RecordedBattleProvider(self.scenario.battle_states),
            battle_engine=BattleDecisionEngine(),
            recovery_provider=_UnexpectedRecoveryProvider(),
            recovery_manager=_UnexpectedRecoveryManager(),
            authorizer=DirectPolicyAuthorizer(PolicyGate(0.92)),
            executor=executor,
            verifier=DefaultTransitionVerifier(),
            stop_condition=StopCondition(maximum_quests=stop_after_quests),
        )
        unknown: list[str] = []
        maximum_ticks = len(self.scenario.recognitions) + 2
        for _ in range(maximum_ticks):
            try:
                outcome = loop.tick()
            except (RuntimeError, ValueError, KeyError) as error:
                unknown.append(str(error))
                break
            if outcome in {LoopOutcome.CONFIGURED_STOP, LoopOutcome.STOPPED}:
                break
            if outcome is LoopOutcome.PAUSED and controller.snapshot().state is not RunState.RUNNING:
                unknown.append("loop paused before the configured stop condition")
                break
        unknown.extend(executor.mismatches)
        if len(executor.calls) != len(self.scenario.expected_actions):
            unknown.append(
                f"expected {len(self.scenario.expected_actions)} actions but executed {len(executor.calls)}"
            )
        return SimulationReport(
            completed_quests=loop.completed_quests,
            executed_actions=len(executor.calls),
            verified_transitions=loop.verified_transitions,
            prohibited_actions=tuple(executor.prohibited),
            unknown_actions=tuple(unknown),
        )
