from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic, sleep

import numpy as np
import win32gui

from .agent_models import ActionProposal, Observation, ScreenKind
from .battle import BattleDecisionEngine, BattlePhase, BattlePlanningError, BattlePolicy
from .battle_vision import BattleVisionProvider
from .config import AppConfig
from .controller import AutomationController, RunState, StopReason
from .experience import ExperienceStore
from .hotkey import EmergencyHotkey
from .input_executor import GuardedInputExecutor, LiveTokenAuthority, RunLease, StandardMouse
from .ocr import TesseractOCREngine
from .policy import PolicyGate
from .quest_planner import (
    NoEligibleQuestError,
    PlannerSafetyError,
    QuestMode,
    QuestPlanner,
    UnknownScreenError,
)
from .recognition import Recognition, ScreenRecognizer
from .recovery import IncidentRedactor, RecoveryManager, RecoveryState
from .screen_capture import SafeCapture
from .story_loop import (
    DefaultTransitionVerifier,
    DirectPolicyAuthorizer,
    FrameObservation,
    LoopJournal,
    LoopOutcome,
    StopCondition,
    StoryLoop,
)
from .template_catalog import TemplateCatalog
from .viewport_mapper import ViewportMapper, ViewportMapping
from .win32_api import PyWin32WindowApi
from .window_guardian import WindowGuardian
from .screen_capture import DesktopCapture


class LiveObserver:
    def __init__(self, capture: SafeCapture, baseline, mapper: ViewportMapper) -> None:
        self.capture_source = capture
        self.baseline = baseline
        self.mapper = mapper
        self.expected_mapping: ViewportMapping | None = None

    def capture(self) -> FrameObservation:
        captured = self.capture_source.capture(self.baseline)
        try:
            mapping = self.mapper.locate(captured.image)
        except ValueError:
            if self.expected_mapping is None:
                raise
            mapping = self.expected_mapping
        else:
            if self.expected_mapping is None:
                self.expected_mapping = mapping
            elif mapping.signature != self.expected_mapping.signature:
                raise ValueError("viewport mapping changed from the fixed live baseline")
        return FrameObservation(captured.image, mapping)


class VisionRecoveryProvider:
    def __init__(self, battle: BattleVisionProvider) -> None:
        self.battle = battle
        self._loading_started: float | None = None
        self._network_retries = 0

    def build(
        self,
        recognition: Recognition,
        frame,
        mapping: ViewportMapping,
    ) -> RecoveryState:
        del frame
        if recognition.screen.value == "LOADING":
            if self._loading_started is None:
                self._loading_started = monotonic()
            loading_seconds = monotonic() - self._loading_started
        else:
            self._loading_started = None
            loading_seconds = 0.0
        battle = self.battle.last_state
        if recognition.screen.value == "DEFEAT" and battle is not None:
            battle = replace(battle, phase=BattlePhase.DEFEAT)
        labels = tuple(sorted(recognition.anchors)) + tuple(recognition.text.values()) + recognition.evidence
        return RecoveryState(
            screen=recognition.screen,
            frame_sha256=recognition.frame_sha256,
            confidence=recognition.confidence,
            labels=labels,
            evidence=recognition.evidence,
            battle=battle,
            proposed_screen=None,
            current_ap=None,
            quest_ap_cost=None,
            available_apples={},
            resource_targets={},
            loading_seconds=loading_seconds,
            network_retry_count=self._network_retries,
            retry_target=recognition.anchors.get("retry"),
        )


class _ShadowExecutor:
    def execute_one(self, token, state, proposal) -> None:
        del token, state, proposal
        raise AssertionError("shadow mode must never call an input executor")


class LiveActionVerifier:
    """Recaptures and deterministically replans the exact action immediately before input."""

    def __init__(
        self,
        observer: LiveObserver,
        recognizer: ScreenRecognizer,
        planner: QuestPlanner,
        battle_vision: BattleVisionProvider,
        battle_engine: BattleDecisionEngine,
    ) -> None:
        self.observer = observer
        self.recognizer = recognizer
        self.planner = planner
        self.battle_vision = battle_vision
        self.battle_engine = battle_engine
        self._receipt: tuple[tuple[object, ...], object, str] | None = None

    @staticmethod
    def _target_digest(image: np.ndarray, target) -> str:
        crop = image[target.top:target.bottom, target.left:target.right]
        if crop.size == 0:
            raise ValueError("visible action target has an empty pixel region")
        digest = sha256()
        digest.update(str(crop.shape).encode("ascii"))
        digest.update(str(crop.dtype).encode("ascii"))
        digest.update(np.ascontiguousarray(crop).tobytes())
        return digest.hexdigest()

    @staticmethod
    def _same_intent(left: ActionProposal, right: ActionProposal) -> bool:
        return (
            left.kind is right.kind
            and left.target == right.target
            and left.labels == right.labels
            and left.resource is right.resource
            and left.resource_cost == right.resource_cost
            and left.mandatory == right.mandatory
        )

    def verify(self, state: Observation, proposal: ActionProposal) -> bool:
        self._receipt = None
        if proposal.target is None:
            return False
        observed = self.observer.capture()
        recognition = self.recognizer.recognize(observed.image, observed.mapping)
        if recognition.screen is not state.screen:
            return False
        try:
            if recognition.screen is ScreenKind.BATTLE:
                battle = self.battle_vision.build(
                    observed.image,
                    observed.mapping,
                    recognition,
                )
                fresh = self.battle_engine.plan(battle).proposal
            else:
                fresh = self.planner.plan(recognition)
        except (BattlePlanningError, NoEligibleQuestError, PlannerSafetyError, UnknownScreenError):
            return False
        if not self._same_intent(proposal, fresh):
            return False
        self._receipt = (
            observed.mapping.signature,
            proposal.target,
            self._target_digest(observed.image, proposal.target),
        )
        return True

    def still_current(self, state: Observation, proposal: ActionProposal) -> bool:
        del state
        receipt = self._receipt
        self._receipt = None
        if receipt is None or proposal.target is None:
            return False
        signature, target, expected_digest = receipt
        if proposal.target != target:
            return False
        observed = self.observer.capture()
        return (
            observed.mapping.signature == signature
            and self._target_digest(observed.image, proposal.target) == expected_digest
        )


class LiveRuntime:
    """Owns the exact LDPlayer baseline and the background autonomous loop."""

    def __init__(
        self,
        controller: AutomationController,
        project_root: str | Path,
        *,
        mode: QuestMode,
        maximum_quests: int | None,
        farming_anchor: str | None = None,
        shadow: bool = False,
    ) -> None:
        self.controller = controller
        self.project_root = Path(project_root)
        self.mode = mode
        self.maximum_quests = maximum_quests
        self.farming_anchor = farming_anchor
        self.shadow = shadow
        self.config = AppConfig.load(self.project_root / "config" / "default.json")
        self._lock = RLock()
        self._worker_thread: Thread | None = None
        self._hotkey: EmergencyHotkey | None = None
        self._guardian: WindowGuardian | None = None
        self._baseline = None
        self._loop: StoryLoop | None = None
        self._run_generation = 0
        self._active_lease: RunLease | None = None
        self._startup_cancellation: Event | None = None
        self.last_error: str | None = None

    @staticmethod
    def _focus(hwnd: int) -> None:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, 9)
        win32gui.SetForegroundWindow(hwnd)

    def _build_loop(
        self,
        guardian: WindowGuardian,
        baseline,
        lease: RunLease,
    ) -> StoryLoop:
        catalog = TemplateCatalog.load(self.project_root / "templates" / "manifest.json")
        ocr = TesseractOCREngine()
        recognizer = ScreenRecognizer(catalog, ocr)
        battle_vision = BattleVisionProvider(self.project_root / "templates", ocr)
        experience = ExperienceStore(self.project_root / "data" / "experience")
        recovery = RecoveryManager(
            self.project_root / "data",
            controller=self.controller,
            experience=experience,
            redactor=IncidentRedactor(),
            catalog_version=catalog.version,
        )
        observer = LiveObserver(
            SafeCapture(guardian, DesktopCapture()),
            baseline,
            ViewportMapper(),
        )
        planner = QuestPlanner(
            self.mode,
            farming_anchor=self.farming_anchor,
        )
        battle_engine = BattleDecisionEngine(
            BattlePolicy.load(self.project_root / "config" / "battle_policy.json")
        )
        policy = PolicyGate(self.config.confidence_threshold)
        if self.shadow:
            authorizer = DirectPolicyAuthorizer(policy)
            executor = _ShadowExecutor()
        else:
            authority = LiveTokenAuthority(
                policy,
                self.controller,
                ttl_seconds=self.config.stale_timeout_seconds,
                lease=lease,
            )
            authorizer = authority
            executor = GuardedInputExecutor(
                self.controller,
                authority,
                guardian,
                baseline,
                StandardMouse(),
                LiveActionVerifier(
                    observer,
                    recognizer,
                    planner,
                    battle_vision,
                    battle_engine,
                ),
                lease,
            )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        journal = LoopJournal(self.project_root / "data" / "runs" / f"story-{stamp}.jsonl")
        return StoryLoop(
            controller=self.controller,
            observer=observer,
            recognizer=recognizer,
            quest_planner=planner,
            battle_provider=battle_vision,
            battle_engine=battle_engine,
            recovery_provider=VisionRecoveryProvider(battle_vision),
            recovery_manager=recovery,
            authorizer=authorizer,
            executor=executor,
            verifier=DefaultTransitionVerifier(),
            stop_condition=StopCondition(maximum_quests=self.maximum_quests),
            experience=experience,
            journal=journal,
            shadow=self.shadow,
        )

    def _prepare(self, lease: RunLease) -> StoryLoop:
        api = PyWin32WindowApi()
        guardian = WindowGuardian(api, self.config)
        hwnd = guardian.select_unique()
        self._focus(hwnd)
        sleep(0.25)
        baseline = guardian.establish_baseline(hwnd, sample_count=3, delay_seconds=0.2)
        if self._hotkey is None:
            hotkey = EmergencyHotkey(self.config.emergency_hotkey, self.controller.emergency_stop)
            hotkey.start()
            hotkey.ensure_running()
            self._hotkey = hotkey
        self._guardian = guardian
        self._baseline = baseline
        return self._build_loop(guardian, baseline, lease)

    def start(self, cancellation: Event | None = None) -> None:
        request = cancellation or Event()
        self._startup_cancellation = request
        if request.is_set():
            return
        with self._lock:
            if request.is_set():
                return
            if self.controller.snapshot().state is RunState.EMERGENCY_STOPPED:
                raise RuntimeError("emergency stop is terminal until the application restarts")
            if self.controller.snapshot().state is RunState.RUNNING:
                return
            previous_worker = self._worker_thread
            if previous_worker is not None and previous_worker.is_alive():
                previous_worker.join(timeout=self.config.stale_timeout_seconds)
                if previous_worker.is_alive():
                    raise RuntimeError(
                        "previous automation run is still stopping; Start was not rearmed"
                    )
            self._worker_thread = None
            if request.is_set():
                return
            if self._active_lease is not None:
                self._active_lease.invalidate()
            self._run_generation += 1
            generation = self._run_generation
            lease = RunLease()
            self._active_lease = lease
            try:
                loop = self._prepare(lease)
                self._loop = loop
                if request.is_set():
                    lease.invalidate()
                    self._run_generation += 1
                    self._loop = None
                    self.controller.stop(StopReason.USER_STOP)
                    return
                self.controller.start()
                if request.is_set():
                    lease.invalidate()
                    self._run_generation += 1
                    self._loop = None
                    self.controller.stop(StopReason.USER_STOP)
                    return
                worker = Thread(
                    target=self._worker,
                    args=(generation, loop, lease),
                    name="fgo-story-loop",
                    daemon=True,
                )
                self._worker_thread = worker
                worker.start()
            except BaseException:
                lease.invalidate()
                self._run_generation += 1
                self._worker_thread = None
                self.controller.stop(StopReason.WINDOW_UNSAFE)
                raise

    def _worker(
        self,
        generation: int | None = None,
        loop: StoryLoop | None = None,
        lease: RunLease | None = None,
    ) -> None:
        if generation is None:
            generation = self._run_generation
        if loop is None:
            loop = self._loop
        interval = self.config.capture_interval_ms / 1000.0
        try:
            while True:
                if generation != self._run_generation:
                    return
                state = self.controller.snapshot().state
                if state in {RunState.STOPPED, RunState.EMERGENCY_STOPPED}:
                    return
                if state is RunState.PAUSED:
                    sleep(min(interval, 0.25))
                    continue
                if loop is None:
                    self.controller.stop(StopReason.WINDOW_UNSAFE)
                    return
                try:
                    outcome = loop.tick()
                except BaseException as error:
                    if generation == self._run_generation:
                        self.last_error = f"{type(error).__name__}: {error}"
                    try:
                        loop.record_runtime_error(error)
                    finally:
                        if generation == self._run_generation:
                            self.controller.stop(StopReason.WINDOW_UNSAFE)
                    return
                if outcome in {LoopOutcome.STOPPED, LoopOutcome.CONFIGURED_STOP}:
                    return
                sleep(interval)
        finally:
            if lease is not None:
                lease.invalidate()

    def pause(self) -> None:
        self.controller.pause()

    def resume(self) -> None:
        with self._lock:
            if self._baseline is None or self._guardian is None:
                raise RuntimeError("live runtime has no established LDPlayer baseline")
            self._focus(self._baseline.hwnd)
            sleep(0.2)
            report = self._guardian.check(self._baseline)
            if not report.safe:
                raise RuntimeError(",".join(report.reasons) or "LDPlayer is unsafe")
            self.controller.resume()

    def stop(self) -> None:
        cancellation = self._startup_cancellation
        if cancellation is not None:
            cancellation.set()
        self.controller.stop(StopReason.USER_STOP)
        with self._lock:
            self._run_generation += 1
            if self._active_lease is not None:
                self._active_lease.invalidate()

    def close(self) -> None:
        self.stop()
        hotkey = self._hotkey
        if hotkey is not None:
            hotkey.stop()
            self._hotkey = None
