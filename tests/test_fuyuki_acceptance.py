from __future__ import annotations

from pathlib import Path

import pytest

from fgo_guardian.agent_models import ActionKind, ActionProposal, Observation, ResourceKind, ScreenKind
from fgo_guardian.models import Rect
from fgo_guardian.policy import PolicyGate
from fgo_guardian.simulation import StorySimulation


RECORDED_ROOT = Path(
    r"C:\Users\User\Documents\New project\fgo-supervised-assistant\data\recordings\tutorial-fuyuki-formation-run-9"
)


@pytest.mark.skipif(not RECORDED_ROOT.exists(), reason="local redacted Fuyuki recording is unavailable")
def test_recorded_fuyuki_quest_passes_offline_acceptance() -> None:
    report = StorySimulation.from_recording(RECORDED_ROOT).run(stop_after_quests=1)

    assert report.completed_quests == 1
    assert report.executed_actions == 21
    assert report.verified_transitions == 21
    assert report.prohibited_actions == ()
    assert report.unknown_actions == ()


@pytest.mark.parametrize(
    ("kind", "resource"),
    [
        (ActionKind.RESTORE_AP, ResourceKind.SAINT_QUARTZ),
        (ActionKind.USE_COMMAND_SPELL, ResourceKind.COMMAND_SPELL),
        (ActionKind.OPTIONAL_SUMMON, ResourceKind.SUMMON_TICKET),
    ],
)
def test_acceptance_policy_has_no_premium_or_command_spell_path(kind, resource) -> None:
    state = Observation(
        "frame",
        ScreenKind.DEFEAT if kind is ActionKind.USE_COMMAND_SPELL else ScreenKind.AP_REFILL,
        0.99,
        "a" * 64,
        Rect(0, 0, 1600, 900),
        (),
        (),
    )
    proposal = ActionProposal(
        "frame",
        kind,
        Rect(500, 300, 900, 500),
        (),
        resource,
        1,
        False,
    )

    assert not PolicyGate(0.92).evaluate(state, proposal).allowed
