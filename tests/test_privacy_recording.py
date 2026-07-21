from pathlib import Path

import hashlib
import json

import numpy as np
import pytest
from PIL import Image

from fgo_guardian.agent_models import ScreenKind
from fgo_guardian.models import Rect
from fgo_guardian.privacy import PersistenceBlocked, PrivacyPolicy
from fgo_guardian.recording import RecordingStore
from fgo_guardian.viewport_mapper import ViewportMapping


def mapping() -> ViewportMapping:
    return ViewportMapping(Rect(0, 0, 200, 100), 0, 200)


def test_title_frame_is_blacked_out_before_disk_write(tmp_path: Path) -> None:
    policy = PrivacyPolicy.load(Path("config/privacy.json"))
    store = RecordingStore(tmp_path / "session", policy)
    frame = np.full((100, 200, 3), 255, dtype=np.uint8)
    record = store.record_observation(frame, mapping(), ScreenKind.TITLE, 0.99, ("FGO title",))
    saved = np.asarray(Image.open(tmp_path / "session" / record.image_path).convert("RGB"))
    assert np.all(saved[78:100, 0:80] == 0)
    assert np.all(saved[80:100, 70:144] == 0)
    assert record.masks_applied == 2
    assert record.prohibited_regions == ((0, 78, 80, 100), (70, 80, 144, 100))
    assert hashlib.sha256(saved.tobytes()).hexdigest() == record.frame_sha256


def test_unknown_screen_is_never_persisted(tmp_path: Path) -> None:
    store = RecordingStore(tmp_path / "session", PrivacyPolicy({}))
    with pytest.raises(PersistenceBlocked, match="TITLE"):
        store.record_observation(
            np.zeros((100, 200, 3), dtype=np.uint8),
            mapping(),
            ScreenKind.TITLE,
            0.99,
            (),
        )
    with pytest.raises(PersistenceBlocked, match="unknown"):
        store.record_observation(
            np.zeros((100, 200, 3), dtype=np.uint8),
            mapping(),
            ScreenKind.UNKNOWN,
            0.0,
            (),
        )
    assert not list((tmp_path / "session").glob("**/*.png"))
    assert not (tmp_path / "session" / "observations.jsonl").exists()


def test_invalid_manifest_and_mismatched_frame_fail_closed(tmp_path: Path) -> None:
    manifest = tmp_path / "privacy.json"
    invalid_payloads = (
        [],
        {"version": 2, "screen_masks": {"TITLE": [[0.0, 0.8, 0.7, 1.0]]}},
        {"version": 1, "screen_masks": {"TITLE": []}},
        {"version": 1, "screen_masks": {"TITLE": [[0.0, 0.8, 0.7]]}},
        {"version": 1, "screen_masks": {"TITLE": [[0.0, 0.8, float("nan"), 1.0]]}},
    )
    for payload in invalid_payloads:
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError):
            PrivacyPolicy.load(manifest)

    store = RecordingStore(tmp_path / "session", PrivacyPolicy.load(Path("config/privacy.json")))
    with pytest.raises(PersistenceBlocked, match="viewport"):
        store.record_observation(
            np.zeros((100, 200, 3), dtype=np.uint8),
            ViewportMapping(Rect(0, 0, 300, 100), 0, 300),
            ScreenKind.STORY,
            0.99,
            (),
        )
    with pytest.raises(PersistenceBlocked, match="uint8 RGB"):
        store.record_observation(
            np.zeros((100, 200, 3), dtype=float),
            mapping(),
            ScreenKind.STORY,
            0.99,
            (),
        )
    tiny_mask = PrivacyPolicy({ScreenKind.TITLE: ((0.0, 0.0, 0.001, 0.001),)})
    with pytest.raises(PersistenceBlocked, match="nonzero area"):
        RecordingStore(tmp_path / "tiny", tiny_mask).record_observation(
            np.zeros((100, 200, 3), dtype=np.uint8),
            mapping(),
            ScreenKind.TITLE,
            0.99,
            (),
        )


def test_metadata_failure_removes_staged_and_published_images(tmp_path: Path, monkeypatch) -> None:
    store = RecordingStore(tmp_path / "session", PrivacyPolicy.load(Path("config/privacy.json")))
    store.record_observation(
        np.zeros((100, 200, 3), dtype=np.uint8),
        mapping(),
        ScreenKind.STORY,
        0.99,
        ("first",),
    )
    original_log = store.observations_path.read_bytes()
    original_frames = {path.name for path in store.frames.iterdir()}

    def fail_after_partial_write(handle, line) -> None:
        handle.write('{"partial":')
        raise OSError("simulated metadata failure")

    monkeypatch.setattr(store, "_write_line", fail_after_partial_write)
    with pytest.raises(OSError, match="metadata failure"):
        store.record_observation(
            np.zeros((100, 200, 3), dtype=np.uint8),
            mapping(),
            ScreenKind.STORY,
            0.99,
            (),
        )
    assert store.observations_path.read_bytes() == original_log
    assert {path.name for path in store.frames.iterdir()} == original_frames
