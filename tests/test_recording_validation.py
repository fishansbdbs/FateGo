from pathlib import Path

import json
import numpy as np
import pytest

from fgo_guardian.agent_models import (
    ActionKind,
    ActionProposal,
    Observation,
    ResourceKind,
    ScreenKind,
)
from fgo_guardian.models import Rect
from fgo_guardian.policy import PolicyGate
from fgo_guardian.privacy import PrivacyPolicy
from fgo_guardian.recording import RecordingStore
from fgo_guardian.tools import validate_recording as validation_module
from fgo_guardian.tools.validate_recording import validate_recording
from fgo_guardian.viewport_mapper import ViewportMapping


def empty_recording(root: Path) -> None:
    (root / "observations.jsonl").write_text("", encoding="utf-8")
    (root / "actions.jsonl").write_text("", encoding="utf-8")
    (root / "transitions.jsonl").write_text("", encoding="utf-8")


def test_validation_rejects_missing_required_screen(tmp_path: Path) -> None:
    empty_recording(tmp_path)
    with pytest.raises(ValueError, match="missing required screens"):
        validate_recording(tmp_path, {ScreenKind.TUTORIAL_MAP})


def test_validation_rejects_quartz_label_even_without_quartz_resource(tmp_path: Path) -> None:
    (tmp_path / "observations.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "transitions.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "actions.jsonl").write_text(
        '{"token":"x","proposal":{"labels":["Saint Quartz"],"resource":"NONE"},'
        '"decision":{"allowed":true,"reason":"allowed"}}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Quartz"):
        validate_recording(tmp_path, set())


def test_validation_rejects_unmasked_title_observation(tmp_path: Path) -> None:
    (tmp_path / "actions.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "transitions.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "observations.jsonl").write_text(
        '{"observation_id":"obs-title","screen":"TITLE","masks_applied":0}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="privacy mask"):
        validate_recording(tmp_path, set())


def test_safe_stop_mode_accepts_only_one_trailing_incomplete_action(
    tmp_path: Path,
) -> None:
    root = tmp_path / "session"
    mapping = ViewportMapping(Rect(0, 0, 200, 100), 0, 200)
    store = RecordingStore(root, PrivacyPolicy({}))
    record = store.record_observation(
        np.zeros((100, 200, 3), dtype=np.uint8),
        mapping,
        ScreenKind.TUTORIAL_PROMPT,
        0.99,
        ("Summon", "forced tutorial prompt"),
    )
    state = Observation(
        record.observation_id,
        ScreenKind.TUTORIAL_PROMPT,
        0.99,
        record.frame_sha256,
        mapping.viewport,
        (),
        ("Summon", "forced tutorial prompt"),
    )
    proposal = ActionProposal(
        record.observation_id,
        ActionKind.ADVANCE_TUTORIAL,
        Rect(80, 40, 120, 80),
        ("Summon", "forced tutorial prompt"),
        ResourceKind.NONE,
        0,
        True,
    )
    store.authorize(state, proposal, PolicyGate(0.92))
    (root / "STOPPED").write_text("emergency_stop", encoding="utf-8")
    valid_pause = "viewport_unobservable:ValueError:" + "a" * 32
    (root / "VIEWPORT_PAUSED").write_text(
        valid_pause,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="one-to-one"):
        validate_recording(root, set())
    counts = validate_recording(root, set(), allow_incomplete_safe_stop=True)
    assert counts == {
        "observations": 1,
        "actions": 1,
        "transitions": 0,
        "pending_actions": 1,
    }
    for invalid_pause in (
        valid_pause + "\n",
        "viewport_unobservable:ValueError:short-token",
        "viewport_unobservable:Value-Error:" + "a" * 32,
        valid_pause + ":extra",
    ):
        (root / "VIEWPORT_PAUSED").write_text(invalid_pause, encoding="utf-8")
        with pytest.raises(ValueError, match="owned unobservable viewport"):
            validate_recording(root, set(), allow_incomplete_safe_stop=True)


def test_safe_stop_mode_rejects_a_quartz_spend_tail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = {
        "token": "pending-token",
        "proposal": {
            "observation_id": "obs-final",
            "kind": "TUTORIAL_FREE_SUMMON",
            "labels": ["Saint Quartz Cost 30"],
            "resource": "SAINT_QUARTZ",
            "resource_cost": 30,
            "mandatory": True,
        },
        "decision": {"allowed": True, "reason": "allowed"},
        "required_after_sequence": 1,
    }

    class FakeReplay:
        def observations(self) -> list[dict[str, object]]:
            return [{"observation_id": "obs-final", "screen": "TUTORIAL_PROMPT"}]

        def actions(self) -> list[dict[str, object]]:
            return [action]

        def transitions(self) -> list[dict[str, object]]:
            return []

        def validate(self) -> None:
            raise ValueError("allowed actions and transitions are not one-to-one")

    monkeypatch.setattr(validation_module, "ReplaySession", lambda root: FakeReplay())
    (tmp_path / "STOPPED").write_text("emergency_stop\n", encoding="utf-8")
    (tmp_path / "VIEWPORT_PAUSED").write_text(
        "viewport_unobservable:ValueError:owned-token\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Quartz"):
        validate_recording(tmp_path, set(), allow_incomplete_safe_stop=True)


def test_validation_rejects_unknown_forbidden_and_semantically_invalid_actions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "complete"
    mapping = ViewportMapping(Rect(0, 0, 200, 100), 0, 200)
    store = RecordingStore(root, PrivacyPolicy({}))
    first = store.record_observation(
        np.zeros((100, 200, 3), dtype=np.uint8),
        mapping,
        ScreenKind.TUTORIAL_PROMPT,
        0.99,
        ("Continue",),
    )
    state = Observation(
        first.observation_id,
        ScreenKind.TUTORIAL_PROMPT,
        0.99,
        first.frame_sha256,
        mapping.viewport,
        (),
        ("Continue",),
    )
    proposal = ActionProposal(
        first.observation_id,
        ActionKind.ADVANCE_TUTORIAL,
        Rect(80, 40, 120, 80),
        ("Continue",),
        ResourceKind.NONE,
        0,
        True,
    )
    token = store.authorize(state, proposal, PolicyGate(0.92))
    second = store.record_observation(
        np.ones((100, 200, 3), dtype=np.uint8),
        mapping,
        ScreenKind.STORY,
        0.99,
        ("Skip",),
    )
    store.complete(token, second.observation_id)
    original = json.loads(store.actions_path.read_text(encoding="utf-8"))

    invalid_cases = (
        ("kind", "NOT_AN_ACTION", "unknown action kind"),
        ("resource", "NOT_A_RESOURCE", "unknown resource"),
        ("resource", "SUMMON_TICKET", "Summon Ticket"),
        ("resource", "PAID_CURRENCY", "paid currency"),
        ("kind", "TUTORIAL_FREE_SUMMON", "recorded policy"),
    )
    for field, value, message in invalid_cases:
        changed = json.loads(json.dumps(original))
        changed["proposal"][field] = value
        store.actions_path.write_text(json.dumps(changed) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            validate_recording(root, set())
