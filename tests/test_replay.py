from pathlib import Path

import json
import numpy as np
import pytest

from fgo_guardian.agent_models import ActionKind, ActionProposal, Observation, ResourceKind, ScreenKind
from fgo_guardian.models import Rect
from fgo_guardian.policy import PolicyGate
from fgo_guardian.privacy import PrivacyPolicy
from fgo_guardian.recording import RecordingStore
from fgo_guardian.replay import ReplaySession
from fgo_guardian.viewport_mapper import ViewportMapping


def test_allowed_action_round_trips_through_replay(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path / "session", PrivacyPolicy({}))
    mapping = ViewportMapping(Rect(0, 0, 1600, 900), 0, 1600)
    first = store.record_observation(np.zeros((900, 1600, 3), dtype=np.uint8), mapping, ScreenKind.TUTORIAL_MAP, 0.99, ("NEXT",))
    state = Observation(first.observation_id, ScreenKind.TUTORIAL_MAP, 0.99, first.frame_sha256, mapping.viewport, (), ("NEXT",))
    action = ActionProposal(first.observation_id, ActionKind.SELECT_QUEST, Rect(700, 300, 900, 500), ("NEXT",), ResourceKind.NONE, 0, False)
    token = store.authorize(state, action, PolicyGate(0.92))
    with pytest.raises(ValueError, match="strictly later"):
        store.complete(token, first.observation_id)
    second = store.record_observation(np.ones((900, 1600, 3), dtype=np.uint8), mapping, ScreenKind.STORY, 0.99, ("Skip",))
    store.complete(token, second.observation_id)
    replay = ReplaySession(tmp_path / "session")
    replay.validate()
    transition = replay.transitions()[0]
    assert transition["before_id"] == first.observation_id
    assert transition["after_id"] == second.observation_id

    title_store = RecordingStore(tmp_path / "title", PrivacyPolicy.load(Path("config/privacy.json")))
    title = title_store.record_observation(
        np.zeros((100, 200, 3), dtype=np.uint8),
        ViewportMapping(Rect(0, 0, 200, 100), 0, 200),
        ScreenKind.TITLE,
        0.99,
        ("User 123-456-789",),
    )
    persisted = json.loads(title_store.observations_path.read_text(encoding="utf-8"))
    assert persisted["observation_id"] == title.observation_id
    assert persisted["labels"] == ["[TITLE_LABELS_REDACTED]"]
    title_state = Observation(
        title.observation_id,
        ScreenKind.TITLE,
        0.99,
        title.frame_sha256,
        Rect(0, 0, 200, 100),
        tuple(Rect(*region) for region in title.prohibited_regions),
        title.labels,
    )
    title_action = ActionProposal(title.observation_id, ActionKind.WAIT, None, ("account 12345678",), ResourceKind.NONE, 0, False)
    title_store.authorize(title_state, title_action, PolicyGate(0.92))
    assert ReplaySession(tmp_path / "title").actions()[0]["proposal"]["labels"] == ["[TITLE_LABELS_REDACTED]"]

    title_touch_store = RecordingStore(
        tmp_path / "title-touch",
        PrivacyPolicy.load(Path("config/privacy.json")),
    )
    title_touch = title_touch_store.record_observation(
        np.zeros((100, 200, 3), dtype=np.uint8),
        ViewportMapping(Rect(0, 0, 200, 100), 0, 200),
        ScreenKind.TITLE,
        0.99,
        ("User 123-456-789", "Touch Screen"),
    )
    title_touch_state = Observation(
        title_touch.observation_id,
        ScreenKind.TITLE,
        0.99,
        title_touch.frame_sha256,
        Rect(0, 0, 200, 100),
        tuple(Rect(*region) for region in title_touch.prohibited_regions),
        title_touch.labels,
    )
    assert list(title_touch.labels) == ["[TITLE_LABELS_REDACTED]", "Touch Screen"]
    title_touch_action = ActionProposal(
        title_touch.observation_id,
        ActionKind.ADVANCE_TUTORIAL,
        Rect(80, 68, 120, 76),
        ("Touch Screen",),
        ResourceKind.NONE,
        0,
        True,
    )
    title_touch_store.authorize(title_touch_state, title_touch_action, PolicyGate(0.92))
    assert ReplaySession(tmp_path / "title-touch").actions()[0]["proposal"]["labels"] == ["Touch Screen"]


def test_denied_action_never_receives_token(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path / "session", PrivacyPolicy({}))
    state = Observation("obs-1", ScreenKind.AP_REFILL, 0.99, "a" * 64, Rect(0, 0, 1600, 900), (), ())
    action = ActionProposal("obs-1", ActionKind.RESTORE_AP, Rect(700, 300, 900, 500), ("Saint Quartz",), ResourceKind.SAINT_QUARTZ, 1, False)
    try:
        store.authorize(state, action, PolicyGate(0.92))
    except PermissionError as error:
        assert "saint_quartz_forbidden" in str(error)
    else:
        raise AssertionError("denied action received an authorization token")
    logged = ReplaySession(tmp_path / "session").actions()[0]
    assert logged["token"] is None
    assert isinstance(logged["attempt_id"], str)
    missing = ActionProposal("missing", ActionKind.WAIT, None, ("account 12345678",), ResourceKind.NONE, 0, False)
    with pytest.raises(PermissionError, match="observation_not_recorded"):
        store.authorize(state, missing, PolicyGate(0.92))
    assert ReplaySession(tmp_path / "session").actions()[1]["proposal"]["labels"] == ["account xxxxxxxx"]


def test_allowed_action_requires_exactly_one_completion(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path / "session", PrivacyPolicy({}))
    mapping = ViewportMapping(Rect(0, 0, 1600, 900), 0, 1600)
    first = store.record_observation(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        mapping,
        ScreenKind.TUTORIAL_MAP,
        0.99,
        ("NEXT",),
    )
    state = Observation(first.observation_id, ScreenKind.TUTORIAL_MAP, 0.99, first.frame_sha256, mapping.viewport, (), ("NEXT",))
    action = ActionProposal(first.observation_id, ActionKind.SELECT_QUEST, Rect(700, 300, 900, 500), ("NEXT",), ResourceKind.NONE, 0, False)
    store.authorize(state, action, PolicyGate(0.92))
    with pytest.raises(ValueError, match="one-to-one"):
        ReplaySession(tmp_path / "session").validate()


def test_replay_rejects_image_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "session"
    root.mkdir()
    (root / "observations.jsonl").write_text(
        '{"observation_id":"obs-x","image_path":"../outside.png","frame_sha256":"' + "a" * 64 + '"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="escapes session root"):
        ReplaySession(root).validate()
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "actions.jsonl").write_text('{"partial":', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid actions.jsonl"):
        ReplaySession(corrupt).actions()
    denied_schema_corrupt = tmp_path / "denied-schema-corrupt"
    denied_schema_corrupt.mkdir()
    (denied_schema_corrupt / "actions.jsonl").write_text(
        '{"attempt_id":"attempt","token":null,"decision":{"allowed":false,"reason":"denied"},"proposal":[]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid actions.jsonl"):
        ReplaySession(denied_schema_corrupt).validate()
    schema_corrupt = tmp_path / "schema-corrupt"
    schema_corrupt.mkdir()
    (schema_corrupt / "observations.jsonl").write_text('{"observation_id":[]}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid observations.jsonl"):
        ReplaySession(schema_corrupt).validate()


def test_observation_cannot_authorize_two_allowed_actions(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path / "session", PrivacyPolicy({}))
    mapping = ViewportMapping(Rect(0, 0, 1600, 900), 0, 1600)
    first = store.record_observation(
        np.zeros((900, 1600, 3), dtype=np.uint8),
        mapping,
        ScreenKind.TUTORIAL_MAP,
        0.99,
        ("NEXT",),
    )
    state = Observation(first.observation_id, ScreenKind.TUTORIAL_MAP, 0.99, first.frame_sha256, mapping.viewport, (), ("NEXT",))
    action = ActionProposal(first.observation_id, ActionKind.SELECT_QUEST, Rect(700, 300, 900, 500), ("NEXT",), ResourceKind.NONE, 0, False)
    forged = Observation(first.observation_id, ScreenKind.TUTORIAL_MAP, 0.99, "b" * 64, mapping.viewport, (), ("NEXT",))
    with pytest.raises(PermissionError, match="observation_state_mismatch"):
        store.authorize(forged, action, PolicyGate(0.92))
    store.authorize(state, action, PolicyGate(0.92))
    with pytest.raises(PermissionError, match="observation_already_used"):
        store.authorize(state, action, PolicyGate(0.92))
