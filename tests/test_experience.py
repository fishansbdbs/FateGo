from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from fgo_guardian.agent_models import ActionKind, ScreenKind
from fgo_guardian.experience import (
    CandidateProposal,
    ExperienceStore,
    RegressionReport,
)


def _redacted_png(value: int = 20) -> bytes:
    frame = np.full((48, 96, 3), value, dtype=np.uint8)
    frame[:, :12] = 0
    encoded, output = cv2.imencode(".png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    assert encoded
    return output.tobytes()


def _proposal(screen: ScreenKind = ScreenKind.STORY) -> CandidateProposal:
    return CandidateProposal(
        proposed_screen=screen,
        confidence=0.97,
        evidence=("human-verified", "skip-anchor"),
        source_catalog_version="fuyuki-m1-v1",
    )


def test_unknown_is_quarantined_and_cannot_become_actionable(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path)

    candidate = store.quarantine_unknown(_redacted_png(), _proposal())

    assert candidate.dataset == "quarantine"
    assert store.active_examples() == ()
    assert (tmp_path / candidate.image_path).is_file()
    assert candidate.proposed_screen is ScreenKind.STORY


def test_quarantine_is_content_addressed_and_append_only(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path)

    first = store.quarantine_unknown(_redacted_png(), _proposal())
    second = store.quarantine_unknown(_redacted_png(), _proposal())

    assert second == first
    lines = (tmp_path / "quarantine" / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_promotion_requires_zero_regressions(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path)
    candidate = store.quarantine_unknown(_redacted_png(), _proposal())

    with pytest.raises(PermissionError, match="regression"):
        store.promote(
            candidate.candidate_id,
            RegressionReport(passed_cases=104, failures=("story->battle",)),
        )

    assert store.active_examples() == ()


def test_promotion_creates_a_new_immutable_version_selected_on_next_load(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path)
    candidate = store.quarantine_unknown(_redacted_png(), _proposal())

    version = store.promote(candidate.candidate_id, RegressionReport(passed_cases=105))

    assert version.parent_version_id is None
    assert version.added_candidate_id == candidate.candidate_id
    assert store.active_examples() == (candidate,)
    reloaded = ExperienceStore(tmp_path)
    assert reloaded.active_version() == version
    assert reloaded.active_examples() == (candidate,)
    with pytest.raises(PermissionError, match="already active"):
        reloaded.promote(candidate.candidate_id, RegressionReport(passed_cases=105))


def test_promotion_requires_a_nonempty_regression_run(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path)
    candidate = store.quarantine_unknown(_redacted_png(), _proposal())

    with pytest.raises(PermissionError, match="no passing cases"):
        store.promote(candidate.candidate_id, RegressionReport())


def test_active_examples_fail_closed_if_a_quarantined_image_is_tampered(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path)
    candidate = store.quarantine_unknown(_redacted_png(), _proposal())
    store.promote(candidate.candidate_id, RegressionReport(passed_cases=105))
    (tmp_path / candidate.image_path).write_bytes(_redacted_png(90))

    with pytest.raises(ValueError, match="hash mismatch"):
        ExperienceStore(tmp_path).active_examples()


def test_verified_transitions_are_append_only_and_unverified_ones_are_rejected(tmp_path: Path) -> None:
    store = ExperienceStore(tmp_path)

    transition = store.record_transition(
        before_frame_sha256="a" * 64,
        before_screen=ScreenKind.STORY,
        action=ActionKind.SKIP_STORY,
        after_frame_sha256="b" * 64,
        after_screen=ScreenKind.SKIP_CONFIRM,
        verified=True,
    )

    assert transition.verified is True
    with pytest.raises(PermissionError, match="verified"):
        store.record_transition(
            before_frame_sha256="b" * 64,
            before_screen=ScreenKind.SKIP_CONFIRM,
            action=ActionKind.CONFIRM_SKIP,
            after_frame_sha256="c" * 64,
            after_screen=ScreenKind.TUTORIAL_MAP,
            verified=False,
        )
    items = [json.loads(line) for line in (tmp_path / "transitions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(items) == 1
    assert items[0]["transition_id"] == transition.transition_id


@pytest.mark.parametrize("payload", [b"", b"not-png", b"\x89PNG\r\n\x1a\n"])
def test_quarantine_rejects_invalid_png_without_partial_files(tmp_path: Path, payload: bytes) -> None:
    store = ExperienceStore(tmp_path)

    with pytest.raises(ValueError, match="PNG"):
        store.quarantine_unknown(payload, _proposal())

    assert not list(tmp_path.glob("**/*.png"))
    assert not (tmp_path / "quarantine" / "candidates.jsonl").exists()
