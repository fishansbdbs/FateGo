from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Protocol

import numpy as np

from .agent_models import ActionKind, ActionProposal, Observation, ResourceKind, ScreenKind
from .battle import BattleDecisionEngine, BattleState
from .controller import AutomationController, RunState, StopReason
from .experience import ExperienceStore
from .models import Rect
from .policy import PolicyGate
from .quest_planner import NoEligibleQuestError, PlannerSafetyError, QuestPlanner, UnknownScreenError
from .recognition import Recognition
from .recovery import RecoveryDecision, RecoveryKind, RecoveryManager, RecoveryState
from .viewport_mapper import ViewportMapping


class LoopOutcome(str, Enum):
    ACTION_COMPLETED = "ACTION_COMPLETED"
    WAITING = "WAITING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    CONFIGURED_STOP = "CONFIGURED_STOP"


@dataclass(frozen=True, slots=True)
class FrameObservation:
    image: np.ndarray
    mapping: ViewportMapping


@dataclass(frozen=True, slots=True)
class StopCondition:
    maximum_quests: int | None = None
    deadline_monotonic: float | None = None

    def __post_init__(self) -> None:
        if self.maximum_quests is not None and self.maximum_quests <= 0:
            raise ValueError("maximum quest count must be positive")

    def reached(self, completed_quests: int) -> bool:
        return (
            self.maximum_quests is not None
            and completed_quests >= self.maximum_quests
        ) or (
            self.deadline_monotonic is not None
            and monotonic() >= self.deadline_monotonic
        )


@dataclass(frozen=True, slots=True)
class VerificationResult:
    valid: bool
    reason: str
    quest_completed: bool = False


@dataclass(frozen=True, slots=True)
class PendingTransition:
    before: Recognition
    proposal: ActionProposal


class Observer(Protocol):
    def capture(self) -> FrameObservation: ...


class Recognizer(Protocol):
    def recognize(self, frame: np.ndarray, mapping: ViewportMapping) -> Recognition: ...


class BattleProvider(Protocol):
    def build(
        self,
        frame: np.ndarray,
        mapping: ViewportMapping,
        recognition: Recognition,
    ) -> BattleState: ...


class RecoveryProvider(Protocol):
    def build(
        self,
        recognition: Recognition,
        frame: np.ndarray,
        mapping: ViewportMapping,
    ) -> RecoveryState: ...


class Authorizer(Protocol):
    def authorize(self, state: Observation, proposal: ActionProposal) -> str: ...


class Executor(Protocol):
    def execute_one(self, token: str, state: Observation, proposal: ActionProposal) -> None: ...


class TransitionVerifier(Protocol):
    def verify(
        self,
        before: Recognition,
        proposal: ActionProposal,
        after: Recognition,
    ) -> VerificationResult: ...


class DefaultTransitionVerifier:
    def verify(
        self,
        before: Recognition,
        proposal: ActionProposal,
        after: Recognition,
    ) -> VerificationResult:
        if before.frame_sha256 == after.frame_sha256:
            return VerificationResult(False, "fresh frame hash did not change")
        completed = (
            before.screen is ScreenKind.QUEST_RESULT
            and proposal.kind is ActionKind.COLLECT_RESULT
            and after.screen is not ScreenKind.QUEST_RESULT
        )
        return VerificationResult(True, "fresh transition observed", completed)


class DirectPolicyAuthorizer:
    """In-process authorizer for simulation and shadow mode; live uses one-shot tokens."""

    def __init__(self, policy: PolicyGate) -> None:
        self.policy = policy
        self._sequence = 0
        self._lock = Lock()

    def authorize(self, state: Observation, proposal: ActionProposal) -> str:
        decision = self.policy.evaluate(state, proposal)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        with self._lock:
            self._sequence += 1
            return f"direct-{self._sequence:08d}-{state.frame_sha256[:12]}"


class LoopJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def append(self, event: str, payload: dict[str, object]) -> None:
        record = {"event": event, **payload}
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())


class StoryLoop:
    RECOVERY_SCREENS = {
        ScreenKind.UNKNOWN,
        ScreenKind.DEFEAT,
        ScreenKind.AP_REFILL,
        ScreenKind.LOADING,
    }

    def __init__(
        self,
        *,
        controller: AutomationController,
        observer: Observer,
        recognizer: Recognizer,
        quest_planner: QuestPlanner,
        battle_provider: BattleProvider,
        battle_engine: BattleDecisionEngine,
        recovery_provider: RecoveryProvider,
        recovery_manager: RecoveryManager,
        authorizer: Authorizer,
        executor: Executor,
        verifier: TransitionVerifier,
        stop_condition: StopCondition,
        experience: ExperienceStore | None = None,
        journal: LoopJournal | None = None,
    ) -> None:
        self.controller = controller
        self.observer = observer
        self.recognizer = recognizer
        self.quest_planner = quest_planner
        self.battle_provider = battle_provider
        self.battle_engine = battle_engine
        self.recovery_provider = recovery_provider
        self.recovery_manager = recovery_manager
        self.authorizer = authorizer
        self.executor = executor
        self.verifier = verifier
        self.stop_condition = stop_condition
        self.experience = experience
        self.journal = journal
        self.pending_transition: PendingTransition | None = None
        self.completed_quests = 0
        self.verified_transitions = 0

    def _log(self, event: str, **payload: object) -> None:
        if self.journal is not None:
            self.journal.append(event, payload)

    @staticmethod
    def _observation(recognition: Recognition, mapping: ViewportMapping) -> Observation:
        labels = tuple(sorted(recognition.anchors)) + tuple(
            value for _, value in sorted(recognition.text.items()) if value
        ) + recognition.evidence
        return Observation(
            observation_id=recognition.frame_sha256,
            screen=recognition.screen,
            confidence=recognition.confidence,
            frame_sha256=recognition.frame_sha256,
            viewport=mapping.viewport,
            prohibited_regions=(),
            labels=labels,
        )

    def _verify_pending(self, after: Recognition) -> LoopOutcome | None:
        pending = self.pending_transition
        if pending is None:
            return None
        result = self.verifier.verify(pending.before, pending.proposal, after)
        self._log(
            "verification",
            before=pending.before.frame_sha256,
            after=after.frame_sha256,
            action=pending.proposal.kind.value,
            valid=result.valid,
            reason=result.reason,
            quest_completed=result.quest_completed,
        )
        if not result.valid:
            self.controller.pause()
            return LoopOutcome.PAUSED
        self.pending_transition = None
        self.verified_transitions += 1
        if self.experience is not None:
            self.experience.record_transition(
                before_frame_sha256=pending.before.frame_sha256,
                before_screen=pending.before.screen,
                action=pending.proposal.kind,
                after_frame_sha256=after.frame_sha256,
                after_screen=after.screen,
                verified=True,
            )
        if result.quest_completed:
            self.completed_quests += 1
            if self.stop_condition.reached(self.completed_quests):
                self.controller.stop(StopReason.CONFIGURED_STOP)
                return LoopOutcome.CONFIGURED_STOP
        return None

    @staticmethod
    def _recovery_proposal(recognition: Recognition, decision: RecoveryDecision) -> ActionProposal:
        if decision.kind is RecoveryKind.USE_APPLE:
            kind = ActionKind.RESTORE_AP
        elif decision.kind is RecoveryKind.RETRY:
            kind = ActionKind.RETRY
        else:
            raise ValueError("recovery decision is not actionable")
        return ActionProposal(
            observation_id=recognition.frame_sha256,
            kind=kind,
            target=decision.target,
            labels=(decision.message,),
            resource=decision.resource,
            resource_cost=decision.resource_cost,
            mandatory=False,
        )

    def _recovery(
        self,
        recognition: Recognition,
        observed: FrameObservation,
    ) -> tuple[LoopOutcome, ActionProposal | None]:
        state = self.recovery_provider.build(recognition, observed.image, observed.mapping)
        decision = self.recovery_manager.handle(state, observed.image, observed.mapping)
        self._log(
            "recovery",
            screen=recognition.screen.value,
            decision=decision.kind.value,
            reason=None if decision.reason is None else decision.reason.value,
            message=decision.message,
        )
        if decision.kind is RecoveryKind.WAIT:
            return LoopOutcome.WAITING, None
        if decision.kind is RecoveryKind.PAUSE:
            return LoopOutcome.PAUSED, None
        if decision.kind is RecoveryKind.STOP:
            return LoopOutcome.STOPPED, None
        return LoopOutcome.ACTION_COMPLETED, self._recovery_proposal(recognition, decision)

    def _route(self, recognition: Recognition, observed: FrameObservation) -> tuple[LoopOutcome, ActionProposal | None]:
        if recognition.screen in self.RECOVERY_SCREENS:
            return self._recovery(recognition, observed)
        if recognition.screen is ScreenKind.BATTLE:
            battle = self.battle_provider.build(observed.image, observed.mapping, recognition)
            decision = self.battle_engine.plan(battle)
            if decision.proposal.kind is ActionKind.WAIT:
                return LoopOutcome.WAITING, None
            return LoopOutcome.ACTION_COMPLETED, decision.proposal
        try:
            proposal = self.quest_planner.plan(recognition)
        except (UnknownScreenError, NoEligibleQuestError, PlannerSafetyError) as error:
            self._log("planner_paused", screen=recognition.screen.value, reason=str(error))
            self.controller.pause()
            return LoopOutcome.PAUSED, None
        if proposal.kind is ActionKind.WAIT:
            return LoopOutcome.WAITING, None
        return LoopOutcome.ACTION_COMPLETED, proposal

    def tick(self) -> LoopOutcome:
        snapshot = self.controller.snapshot()
        if snapshot.state is RunState.PAUSED or snapshot.state is RunState.DISARMED:
            return LoopOutcome.PAUSED
        if snapshot.state in {RunState.STOPPED, RunState.EMERGENCY_STOPPED}:
            return LoopOutcome.STOPPED
        if self.stop_condition.reached(self.completed_quests):
            self.controller.stop(StopReason.CONFIGURED_STOP)
            return LoopOutcome.CONFIGURED_STOP

        observed = self.observer.capture()
        recognition = self.recognizer.recognize(observed.image, observed.mapping)
        self._log(
            "observation",
            screen=recognition.screen.value,
            confidence=recognition.confidence,
            frame_sha256=recognition.frame_sha256,
        )
        verification_outcome = self._verify_pending(recognition)
        if verification_outcome is not None:
            return verification_outcome

        outcome, proposal = self._route(recognition, observed)
        if proposal is None:
            return outcome
        permit = self.controller.issue_permit()
        if permit is None:
            return LoopOutcome.PAUSED
        state = self._observation(recognition, observed.mapping)
        try:
            token = self.authorizer.authorize(state, proposal)
            self.controller.require_running(permit)
            self.executor.execute_one(token, state, proposal)
        except PermissionError as error:
            self._log("policy_stop", reason=str(error), action=proposal.kind.value)
            self.controller.stop(StopReason.POLICY_REJECTED)
            return LoopOutcome.STOPPED
        self.pending_transition = PendingTransition(recognition, proposal)
        self._log(
            "action",
            action=proposal.kind.value,
            frame_sha256=recognition.frame_sha256,
            target=None if proposal.target is None else proposal.target.as_tuple(),
        )
        return LoopOutcome.ACTION_COMPLETED
