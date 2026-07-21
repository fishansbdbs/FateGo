from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from fgo_guardian.agent_models import ResourceKind, ScreenKind
from fgo_guardian.battle import AllyState, BattlePhase, BattleState, EnemyState
from fgo_guardian.controller import AutomationController, RunState, StopReason
from fgo_guardian.experience import ExperienceStore
from fgo_guardian.models import Rect
from fgo_guardian.recovery import (
    IncidentRedactor,
    RecoveryKind,
    RecoveryManager,
    RecoveryState,
)
from fgo_guardian.viewport_mapper import ViewportMapping


MAPPING = ViewportMapping(Rect(0, 0, 320, 180), 0, 320)


def _frame() -> np.ndarray:
    rows = np.arange(180, dtype=np.uint8)[:, None]
    frame = np.repeat(rows, 320, axis=1)
    return np.repeat(frame[:, :, None], 3, axis=2)


def _battle_defeat() -> BattleState:
    return BattleState(
        frame_sha256="d" * 64,
        phase=BattlePhase.DEFEAT,
        wave=2,
        total_waves=3,
        turn=9,
        allies=(
            AllyState("mash", 0, 5000, 20, Rect(20, 120, 80, 175), False),
            AllyState("cu", 0, 4200, 80, Rect(100, 120, 160, 175), False),
        ),
        enemies=(EnemyState("boss", 22000, 30000, True, 3, Rect(180, 20, 300, 110)),),
        servant_skills=(),
        master_skills=(),
        noble_phantasms=(),
        cards=(),
        attack_target=None,
        pending_target_strategy=None,
    )


def _state(screen: ScreenKind, **overrides) -> RecoveryState:
    values = {
        "screen": screen,
        "frame_sha256": screen.value.lower().ljust(64, "0")[:64],
        "confidence": 0.99,
        "labels": (),
        "evidence": ("test",),
        "battle": None,
        "proposed_screen": None,
        "current_ap": None,
        "quest_ap_cost": None,
        "available_apples": {},
        "resource_targets": {},
        "loading_seconds": 0.0,
        "network_retry_count": 0,
        "retry_target": None,
    }
    values.update(overrides)
    return RecoveryState(**values)


def _manager(tmp_path: Path) -> tuple[RecoveryManager, AutomationController, ExperienceStore]:
    controller = AutomationController()
    controller.start()
    experience = ExperienceStore(tmp_path / "experience")
    manager = RecoveryManager(
        tmp_path,
        controller=controller,
        experience=experience,
        redactor=IncidentRedactor(),
    )
    return manager, controller, experience


def test_defeat_persists_redacted_diagnostic_and_stops(tmp_path: Path) -> None:
    manager, controller, _ = _manager(tmp_path)
    state = _state(ScreenKind.DEFEAT, battle=_battle_defeat(), labels=("Party Defeated",))

    decision = manager.handle(state, _frame(), MAPPING)

    assert decision.kind is RecoveryKind.STOP
    assert decision.reason is StopReason.BATTLE_DEFEAT
    assert controller.snapshot().state is RunState.STOPPED
    incident = tmp_path / "incidents" / "defeats" / decision.incident_id
    assert (incident / "screenshot.png").is_file()
    saved = cv2.cvtColor(cv2.imread(str(incident / "screenshot.png")), cv2.COLOR_BGR2RGB)
    assert np.all(saved[0:29, 0:80] == 0)
    assert np.all(saved[137:180, 0:96] == 0)
    state_payload = json.loads((incident / "state.json").read_text(encoding="utf-8"))
    diagnosis = json.loads((incident / "diagnosis.json").read_text(encoding="utf-8"))
    assert state_payload["screen"] == "DEFEAT"
    assert diagnosis["primary_cause"] == "party_wiped"
    assert diagnosis["enemy_hp_remaining"] == 22000


def test_unknown_is_quarantined_and_pauses_without_promotion(tmp_path: Path) -> None:
    manager, controller, experience = _manager(tmp_path)
    state = _state(
        ScreenKind.UNKNOWN,
        confidence=0.0,
        proposed_screen=ScreenKind.TUTORIAL_PROMPT,
        evidence=("below-threshold:tutorial-prompt",),
    )

    decision = manager.handle(state, _frame(), MAPPING)

    assert decision.kind is RecoveryKind.PAUSE
    assert decision.reason is StopReason.UNKNOWN_SCREEN
    assert controller.snapshot().state is RunState.PAUSED
    assert experience.active_examples() == ()
    assert list((tmp_path / "experience" / "quarantine" / "frames").glob("*.png"))


def test_unclassified_unknown_is_still_quarantined_but_cannot_be_promoted(tmp_path: Path) -> None:
    manager, _, experience = _manager(tmp_path)

    decision = manager.handle(_state(ScreenKind.UNKNOWN, confidence=0.0), _frame(), MAPPING)

    assert decision.kind is RecoveryKind.PAUSE
    candidate_id = decision.candidate_id
    assert candidate_id is not None
    from fgo_guardian.experience import RegressionReport
    with pytest.raises(PermissionError, match="classified"):
        experience.promote(candidate_id, RegressionReport(passed_cases=140))


def test_ap_shortage_selects_smallest_available_apple_but_never_quartz(tmp_path: Path) -> None:
    manager, _, _ = _manager(tmp_path)
    bronze = Rect(50, 40, 280, 75)
    golden = Rect(50, 80, 280, 115)
    apple_state = _state(
        ScreenKind.AP_REFILL,
        current_ap=1,
        quest_ap_cost=20,
        available_apples={ResourceKind.GOLDEN_APPLE: 3, ResourceKind.BRONZE_APPLE: 4},
        resource_targets={ResourceKind.GOLDEN_APPLE: golden, ResourceKind.BRONZE_APPLE: bronze},
    )

    use = manager.handle(apple_state, _frame(), MAPPING)

    assert use.kind is RecoveryKind.USE_APPLE
    assert use.resource is ResourceKind.BRONZE_APPLE
    assert use.target == bronze

    manager2, controller2, _ = _manager(tmp_path / "quartz-only")
    quartz = manager2.handle(
        _state(
            ScreenKind.AP_REFILL,
            current_ap=1,
            quest_ap_cost=20,
            labels=("Use Saint Quartz",),
            available_apples={ResourceKind.SAINT_QUARTZ: 99},
            resource_targets={ResourceKind.SAINT_QUARTZ: Rect(50, 40, 280, 75)},
        ),
        _frame(),
        MAPPING,
    )
    assert quartz.kind is RecoveryKind.STOP
    assert quartz.resource is ResourceKind.NONE
    assert controller2.snapshot().reason is StopReason.POLICY_REJECTED


@pytest.mark.parametrize("label", ["Use Command Spell", "Spend Summon Ticket", "Use Saint Quartz"])
def test_limited_or_premium_prompt_stops_without_a_click(tmp_path: Path, label: str) -> None:
    manager, controller, _ = _manager(tmp_path / label.replace(" ", "-"))

    decision = manager.handle(_state(ScreenKind.TUTORIAL_PROMPT, labels=(label,)), _frame(), MAPPING)

    assert decision.kind is RecoveryKind.STOP
    assert decision.resource is ResourceKind.NONE
    assert controller.snapshot().reason is StopReason.POLICY_REJECTED


def test_loading_waits_then_uses_bounded_retry_then_pauses(tmp_path: Path) -> None:
    retry = Rect(100, 90, 220, 130)
    manager, _, _ = _manager(tmp_path / "wait")
    assert manager.handle(
        _state(ScreenKind.LOADING, loading_seconds=4), _frame(), MAPPING
    ).kind is RecoveryKind.WAIT

    manager2, _, _ = _manager(tmp_path / "retry")
    retry_decision = manager2.handle(
        _state(
            ScreenKind.LOADING,
            loading_seconds=35,
            labels=("Network error",),
            retry_target=retry,
            network_retry_count=0,
        ),
        _frame(),
        MAPPING,
    )
    assert retry_decision.kind is RecoveryKind.RETRY
    assert retry_decision.target == retry

    manager3, controller3, _ = _manager(tmp_path / "timeout")
    timeout = manager3.handle(
        _state(ScreenKind.LOADING, loading_seconds=35, network_retry_count=2),
        _frame(),
        MAPPING,
    )
    assert timeout.kind is RecoveryKind.PAUSE
    assert controller3.snapshot().state is RunState.PAUSED
