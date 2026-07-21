from __future__ import annotations

from pathlib import Path

import pytest

from fgo_guardian.simulation import StorySimulation


RECORDED_ROOT = Path(
    r"C:\Users\User\Documents\New project\fgo-supervised-assistant\data\recordings\tutorial-fuyuki-formation-run-9"
)


@pytest.mark.skipif(not RECORDED_ROOT.exists(), reason="local redacted Fuyuki recording is unavailable")
def test_fuyuki_replay_reaches_map_after_battle_without_unknown_actions() -> None:
    simulation = StorySimulation.from_recording(RECORDED_ROOT)

    report = simulation.run(stop_after_quests=1)

    assert report.completed_quests == 1
    assert report.prohibited_actions == ()
    assert report.unknown_actions == ()
    assert report.executed_actions > 0


def test_simulation_rejects_missing_or_incomplete_recording(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="completed quest"):
        StorySimulation.from_recording(tmp_path)
