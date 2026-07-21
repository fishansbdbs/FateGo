# FGO Milestone 1 Autonomous Story Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, locally runnable Fuyuki Story loop that recognizes supported screens, navigates quests, uses supports and combat skills, clears ordinary battles, collects results, and remains immediately pausable or stoppable.

**Architecture:** A single state-machine controller consumes fresh guarded screenshots, obtains a typed recognition result, asks a screen-specific planner for one semantic action, passes it through the existing policy gate, executes one visible click, and verifies the next state. Unknown screens and defeats enter fail-closed recovery paths; new observations remain quarantined until replay regression tests promote them.

**Tech Stack:** Python 3.14, NumPy, OpenCV, local Tesseract OCR, pywin32 visible input, immutable dataclasses, JSON/JSONL datasets, pytest, Tkinter control panel.

## Global Constraints

- Control exactly one verified `C:\LDPlayer\LDPlayer14\dnplayer.exe` window titled `LDPlayer`.
- Use visible screenshots and standard Windows mouse input only; no ADB, root, memory inspection, packet interception, APK changes, injection, emulator tampering, or evasion.
- Never spend Saint Quartz, Command Spells, or Summon Tickets.
- Apples are the only limited consumable authorized for automatic use.
- Unknown screens pause; they never receive a guessed action.
- Defeat saves a redacted screenshot and structured state, logs the likely cause, stops input, and returns control.
- Every action consumes a fresh observation and must be followed by outcome verification.
- Start, Pause, Stop, and Emergency Stop remain available while the application is open.
- Each subsystem is test-first, committed independently, and leaves the project runnable.

---

### Task 1: Runtime State Machine and Immediate Controls

**Files:**
- Create: `src/fgo_guardian/controller.py`
- Create: `src/fgo_guardian/app.py`
- Test: `tests/test_controller.py`

**Interfaces:**
- Produces: `RunState`, `StopReason`, `ControllerSnapshot`, and `AutomationController`.
- `AutomationController.start()`, `.pause()`, `.resume()`, `.stop()`, and `.emergency_stop()` are thread-safe.
- `AutomationController.step(stepper)` invokes at most one gameplay action and never invokes `stepper` unless state is `RUNNING`.

- [x] **Step 1: Write failing lifecycle tests**

```python
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
```

- [x] **Step 2: Run the tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_controller.py -q`

Expected: import failure because `fgo_guardian.controller` does not exist.

- [x] **Step 3: Implement the lifecycle and control panel**

```python
class RunState(StrEnum):
    DISARMED = "DISARMED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"

class AutomationController:
    def step(self, stepper: Callable[[], None]) -> bool:
        with self._lock:
            if self._state is not RunState.RUNNING:
                return False
            stepper()
            return True
```

`app.py` creates a Tkinter window outside the LDPlayer rectangle with Start, Pause/Resume, Stop, and Emergency Stop buttons bound only to these controller methods.

- [x] **Step 4: Run controller tests and the complete suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_controller.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass and `python -m fgo_guardian.app --simulation` opens without arming input.

- [x] **Step 5: Commit**

```powershell
git add src/fgo_guardian/controller.py src/fgo_guardian/app.py tests/test_controller.py
git commit -m "feat: add deterministic runtime controls"
```

### Task 2: Deterministic Screen Recognition

**Files:**
- Create: `src/fgo_guardian/recognition.py`
- Create: `src/fgo_guardian/ocr.py`
- Create: `src/fgo_guardian/template_catalog.py`
- Create: `config/recognition.json`
- Create: `templates/manifest.json`
- Test: `tests/test_recognition.py`

**Interfaces:**
- Consumes: guarded RGB viewport frames and the existing `ScreenKind` enum.
- Produces: `Recognition(screen, confidence, anchors, text, evidence, frame_sha256)`.
- Produces: `ScreenRecognizer.recognize(frame, mapping) -> Recognition`; it is pure and deterministic for a fixed catalog version.

- [x] **Step 1: Write failing recorded-frame and ambiguity tests**

```python
@pytest.mark.parametrize("label", ["STORY", "SKIP_CONFIRM", "SUPPORT_SELECT", "PARTY_CONFIRM", "BATTLE", "QUEST_RESULT", "TUTORIAL_MAP"])
def test_recorded_fuyuki_screen_family_is_recognized(recorded_frame, label):
    result = recognizer.recognize(recorded_frame.image, recorded_frame.mapping)
    assert result.screen.value == label
    assert result.confidence >= 0.92

def test_conflicting_anchors_return_unknown(conflicting_frame):
    assert recognizer.recognize(conflicting_frame.image, conflicting_frame.mapping).screen is ScreenKind.UNKNOWN
```

- [x] **Step 2: Run recognition tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_recognition.py -q`

Expected: import failure because the recognition modules do not exist.

- [x] **Step 3: Implement bounded OCR, templates, and validators**

```python
@dataclass(frozen=True, slots=True)
class Recognition:
    screen: ScreenKind
    confidence: float
    anchors: Mapping[str, Rect]
    text: Mapping[str, str]
    evidence: tuple[str, ...]
    frame_sha256: str

class ScreenRecognizer:
    def recognize(self, frame: np.ndarray, mapping: ViewportMapping) -> Recognition:
        candidates = tuple(validator.evaluate(frame, mapping) for validator in self.validators)
        accepted = tuple(item for item in candidates if item.confidence >= self.threshold)
        return accepted[0] if len(accepted) == 1 else self.unknown(frame)
```

Use grayscale/multiscale `cv2.matchTemplate`, geometric anchor agreement, and OCR limited to configured regions. Story requires the top-right Skip anchor plus story-panel geometry; every other family requires at least two independent anchors. Do not classify from OCR text alone.

- [x] **Step 4: Run recognition tests, replay tests, and the complete suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_recognition.py tests\test_replay.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

- [x] **Step 5: Commit**

```powershell
git add src/fgo_guardian/recognition.py src/fgo_guardian/ocr.py src/fgo_guardian/template_catalog.py config/recognition.json templates/manifest.json tests/test_recognition.py
git commit -m "feat: recognize deterministic FGO screen families"
```

### Task 3: Quarantined Experience Dataset

**Files:**
- Create: `src/fgo_guardian/experience.py`
- Create: `config/dataset.json`
- Test: `tests/test_experience.py`

**Interfaces:**
- Consumes: `Recognition`, redacted frame bytes, and verified transitions.
- Produces: `ExperienceStore.quarantine_unknown(...)`, `.record_transition(...)`, and `.promote(candidate_id, regression_report)`.
- Active and quarantined datasets use immutable version IDs and append-only JSONL manifests.

- [ ] **Step 1: Write failing quarantine and promotion tests**

```python
def test_unknown_is_quarantined_and_cannot_become_actionable(tmp_path):
    store = ExperienceStore(tmp_path)
    candidate = store.quarantine_unknown(redacted_png, proposal)
    assert candidate.dataset == "quarantine"
    assert store.active_examples() == ()

def test_promotion_requires_zero_regressions(tmp_path):
    store = seeded_store(tmp_path)
    with pytest.raises(PermissionError, match="regression"):
        store.promote("candidate-1", RegressionReport(failures=("story->battle",)))
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_experience.py -q`

- [ ] **Step 3: Implement append-only versioned storage**

```python
def promote(self, candidate_id: str, report: RegressionReport) -> DatasetVersion:
    if report.failures:
        raise PermissionError("regression suite did not pass")
    candidate = self._load_quarantined(candidate_id)
    return self._write_new_active_version(candidate)
```

Unknown screenshots are privacy-redacted before persistence. Promotion never changes thresholds, policy rules, or existing labels; it adds a new catalog version selected only on the next run.

- [ ] **Step 4: Run dataset, privacy, replay, and complete tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_experience.py tests\test_privacy_recording.py tests\test_replay.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

- [ ] **Step 5: Commit**

```powershell
git add src/fgo_guardian/experience.py config/dataset.json tests/test_experience.py
git commit -m "feat: quarantine and promote recognition experience"
```

### Task 4: Quest Navigation Planner

**Files:**
- Create: `src/fgo_guardian/quest_planner.py`
- Test: `tests/test_quest_planner.py`

**Interfaces:**
- Consumes: `Recognition`, operating mode, and persisted `QuestGraph`.
- Produces: one `ActionProposal` for Skip, Skip confirmation, dialogue choice, quest card, support row, party start, result collection, or safe wait.

- [ ] **Step 1: Write failing Story-loop navigation tests**

```python
def test_story_skip_has_priority_over_every_other_control():
    action = planner.plan(story_recognition(skip=SKIP_RECT))
    assert action.kind is ActionKind.SKIP_STORY

def test_map_selects_verified_next_main_quest():
    action = planner.plan(map_recognition(main_quest=QUEST_RECT, next_marker=True))
    assert action.kind is ActionKind.SELECT_QUEST

def test_support_selects_guest_or_highest_compatible_visible_row():
    assert planner.plan(support_recognition()).kind is ActionKind.SELECT_SUPPORT
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_quest_planner.py -q`

- [ ] **Step 3: Implement deterministic screen-specific planning**

```python
class QuestPlanner:
    def plan(self, state: Recognition) -> ActionProposal:
        handler = self._handlers.get(state.screen)
        if handler is None:
            raise UnknownScreenError(state.frame_sha256)
        return handler(state)
```

The planner preserves prepared party/CE state, verifies Auto Teapot is OFF, selects Guest support when required, otherwise scores visible compatible supports deterministically, and never invents a target outside recognized anchors.

- [ ] **Step 4: Run planner, policy, replay, and complete tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_quest_planner.py tests\test_agent_models_policy.py tests\test_replay.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

- [ ] **Step 5: Commit**

```powershell
git add src/fgo_guardian/quest_planner.py tests/test_quest_planner.py
git commit -m "feat: plan FGO story quest navigation"
```

### Task 5: Battle Decision Engine With Skills

**Files:**
- Create: `src/fgo_guardian/battle.py`
- Create: `config/battle_policy.json`
- Test: `tests/test_battle.py`

**Interfaces:**
- Consumes: visible `BattleState` containing wave, enemies, allies, HP, NP, available Servant/Master skills, target state, command cards, and tutorial constraints.
- Produces: exactly one legal semantic action per decision phase.

- [ ] **Step 1: Write failing skill, NP, card, and resource tests**

```python
def test_available_damage_skill_is_used_on_final_wave_before_attack():
    assert agent.plan(final_wave_with_safe_damage_skill()).kind is ActionKind.USE_SKILL

def test_ready_np_is_selected_before_ordinary_cards():
    assert agent.plan(card_phase_with_ready_np()).kind is ActionKind.SELECT_NOBLE_PHANTASM

def test_three_cards_are_ranked_deterministically():
    first = agent.rank_cards(sample_cards())
    assert first == agent.rank_cards(sample_cards())

@pytest.mark.parametrize("resource", [ResourceKind.SAINT_QUARTZ, ResourceKind.COMMAND_SPELL, ResourceKind.SUMMON_TICKET])
def test_forbidden_resources_have_no_battle_candidate(resource):
    assert agent.candidates(defeat_state(resource)) == ()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_battle.py -q`

- [ ] **Step 3: Implement explainable candidate scoring**

```python
@dataclass(frozen=True, slots=True)
class ScoredAction:
    proposal: ActionProposal
    score: int
    reasons: tuple[str, ...]

def choose(candidates: Sequence[ScoredAction]) -> ScoredAction:
    return max(candidates, key=lambda item: (item.score, item.proposal.stable_key()))
```

The first policy uses recognized safe Servant and Master skills, prioritizes survival when an ally is low, NP charge when it enables an NP, damage buffs on the final/high-HP wave, ready NPs before ordinary cards, class-effective cards, brave chains, and deterministic stable-key tie breaks. Skill target modals are handled as separate fresh observations.

- [ ] **Step 4: Run battle, policy, replay, and complete tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_battle.py tests\test_agent_models_policy.py tests\test_replay.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

- [ ] **Step 5: Commit**

```powershell
git add src/fgo_guardian/battle.py config/battle_policy.json tests/test_battle.py
git commit -m "feat: add explainable FGO battle decisions"
```

### Task 6: Recovery and Failure Manager

**Files:**
- Create: `src/fgo_guardian/recovery.py`
- Test: `tests/test_recovery.py`

**Interfaces:**
- Consumes: unknown, loading, network, AP, inventory, prohibited, and defeat states.
- Produces: `RecoveryDecision` with `WAIT`, `RETRY`, `USE_APPLE`, `PAUSE`, or `STOP`; only `USE_APPLE` may consume a limited resource.

- [ ] **Step 1: Write failing defeat, unknown, and Apple tests**

```python
def test_defeat_persists_diagnostic_and_stops(tmp_path):
    decision = manager.handle(defeat, frame, tmp_path)
    assert decision.kind is RecoveryKind.STOP
    assert decision.reason is StopReason.BATTLE_DEFEAT
    assert (tmp_path / "defeats" / decision.incident_id / "state.json").exists()

def test_unknown_is_quarantined_and_pauses():
    assert manager.handle(unknown, frame, root).kind is RecoveryKind.PAUSE

def test_ap_shortage_selects_apple_but_never_quartz():
    assert manager.handle(ap_with_apple, frame, root).kind is RecoveryKind.USE_APPLE
    assert manager.handle(ap_with_only_quartz, frame, root).kind is RecoveryKind.STOP
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_recovery.py -q`

- [ ] **Step 3: Implement recovery decisions and redacted incidents**

```python
if state.screen is ScreenKind.DEFEAT:
    incident = self.incidents.save_redacted(frame, state, diagnose_failure(state))
    return RecoveryDecision.stop(StopReason.BATTLE_DEFEAT, incident.id)
if state.screen is ScreenKind.UNKNOWN:
    self.experience.quarantine_unknown(frame, state)
    return RecoveryDecision.pause(StopReason.UNKNOWN_SCREEN)
```

- [ ] **Step 4: Run recovery, privacy, policy, and complete tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_recovery.py tests\test_privacy_recording.py tests\test_agent_models_policy.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

- [ ] **Step 5: Commit**

```powershell
git add src/fgo_guardian/recovery.py tests/test_recovery.py
git commit -m "feat: recover safely and stop with defeat diagnostics"
```

### Task 7: Simulation and Autonomous Story Orchestrator

**Files:**
- Create: `src/fgo_guardian/story_loop.py`
- Create: `src/fgo_guardian/simulation.py`
- Modify: `src/fgo_guardian/app.py`
- Test: `tests/test_story_loop.py`
- Test: `tests/test_simulation.py`

**Interfaces:**
- Consumes all earlier subsystems through constructor-injected interfaces.
- Produces: `StoryLoop.tick() -> LoopOutcome` and a `--simulation <recording>` CLI mode with no input capability.

- [ ] **Step 1: Write failing end-to-end recorded transition tests**

```python
def test_fuyuki_replay_reaches_map_after_battle_without_unknown_actions(recording):
    simulation = StorySimulation.from_recording(recording)
    report = simulation.run(stop_after_quests=1)
    assert report.completed_quests == 1
    assert report.prohibited_actions == ()
    assert report.unknown_actions == ()

def test_manual_pause_wins_before_executor_call(loop):
    loop.controller.pause()
    assert loop.tick() is LoopOutcome.PAUSED
    assert loop.executor.calls == 0
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_story_loop.py tests\test_simulation.py -q`

- [ ] **Step 3: Implement the one-action loop**

```python
def tick(self) -> LoopOutcome:
    if not self.controller.may_act():
        return LoopOutcome.PAUSED
    frame, mapping = self.observer.capture()
    state = self.recognizer.recognize(frame, mapping)
    proposal = self.router.plan(state)
    token = self.policy.authorize(state, proposal)
    self.executor.execute_one(token, state, proposal)
    self.verifier.require_fresh_result(state)
    return LoopOutcome.ACTION_COMPLETED
```

The configured stop condition supports manual stop, quest count, wall-clock deadline, defeat, unknown state, prohibited prompt, or no eligible quest.

- [ ] **Step 4: Run simulation and complete tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_story_loop.py tests\test_simulation.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

- [ ] **Step 5: Commit**

```powershell
git add src/fgo_guardian/story_loop.py src/fgo_guardian/simulation.py src/fgo_guardian/app.py tests/test_story_loop.py tests/test_simulation.py
git commit -m "feat: orchestrate autonomous Story mode and simulation"
```

### Task 8: Guarded Visible Input and Fuyuki Acceptance Gate

**Files:**
- Create: `src/fgo_guardian/input_executor.py`
- Modify: `src/fgo_guardian/app.py`
- Modify: `docs/execution-log.md`
- Test: `tests/test_input_executor.py`
- Test: `tests/test_fuyuki_acceptance.py`

**Interfaces:**
- Consumes: a current policy token, exact baseline, fresh observation hash, and anchored normalized target.
- Produces: exactly one standard mouse click followed by mandatory fresh capture verification.

- [ ] **Step 1: Write failing stale/focus/one-click acceptance tests**

```python
def test_executor_rejects_stale_observation_without_mouse_input():
    with pytest.raises(PermissionError, match="stale"):
        executor.execute_one(token, stale_state, proposal)
    assert mouse.clicks == []

def test_executor_emits_exactly_one_click_for_current_safe_state():
    executor.execute_one(token, current_state, proposal)
    assert mouse.clicks == [proposal.target.center]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_input_executor.py tests\test_fuyuki_acceptance.py -q`

- [ ] **Step 3: Implement visible input and live arming gate**

```python
def execute_one(self, token: str, state: Observation, proposal: ActionProposal) -> None:
    self.guard.require_safe(self.baseline)
    self.tokens.consume_current(token, state.frame_sha256)
    point = self.mapping.denormalize(proposal.target).center
    self.mouse.click(point)
    self.guard.require_safe(self.baseline)
```

The application defaults to simulation/disarmed mode. Live Start requires a stable exact baseline, active emergency hotkey, recognition catalog version, and explicit Story-mode selection. Pause and Stop are checked again immediately before `mouse.click`.

- [ ] **Step 4: Run offline acceptance and full tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_input_executor.py tests\test_fuyuki_acceptance.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass, no Saint Quartz/Command Spell/Ticket candidate exists, and the Fuyuki recording reaches its configured stop condition in simulation.

- [ ] **Step 5: Run supervised shadow mode, then the first live autonomous Fuyuki loop**

Run: `.\.venv\Scripts\python.exe -m fgo_guardian.app --mode story --shadow`

Only after shadow predictions match the visible supported states, run the desktop app and press Start. The automator—not the development operator—must choose every gameplay action. Stop on the first unknown screen or defeat and retain its diagnostic package.

- [ ] **Step 6: Document and commit Milestone 1**

```powershell
git add src/fgo_guardian/input_executor.py src/fgo_guardian/app.py docs/execution-log.md tests/test_input_executor.py tests/test_fuyuki_acceptance.py
git commit -m "feat: complete guarded Fuyuki Story loop milestone"
```

At handoff, report the remote Git commit hash, implemented behavior, exact tests and live gates run, remaining blockers, and recommended Milestone 2.
