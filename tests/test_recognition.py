from __future__ import annotations

import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from fgo_guardian.agent_models import ScreenKind
from fgo_guardian.models import Rect
from fgo_guardian.ocr import NullOCREngine, OCRResult, TesseractOCREngine
from fgo_guardian.recognition import Recognition, ScreenRecognizer
from fgo_guardian.template_catalog import TemplateCatalog
from fgo_guardian.viewport_mapper import ViewportMapping


SCREEN_FAMILIES = (
    ScreenKind.STORY,
    ScreenKind.SKIP_CONFIRM,
    ScreenKind.SUPPORT_SELECT,
    ScreenKind.PARTY_CONFIRM,
    ScreenKind.BATTLE,
    ScreenKind.QUEST_RESULT,
    ScreenKind.TUTORIAL_MAP,
)


def _pattern(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    pattern = rng.integers(0, 256, (22, 28), dtype=np.uint8)
    pattern[3:6, 4:24] = 255
    pattern[15:19, 8:20] = 0
    return pattern


def _catalog(tmp_path: Path) -> tuple[TemplateCatalog, dict[ScreenKind, tuple[np.ndarray, np.ndarray]]]:
    templates: dict[ScreenKind, tuple[np.ndarray, np.ndarray]] = {}
    manifest: dict[str, object] = {"version": "test-v1", "screens": {}}
    screens = manifest["screens"]
    assert isinstance(screens, dict)
    for index, screen in enumerate(SCREEN_FAMILIES):
        first = _pattern(index * 2 + 1)
        second = _pattern(index * 2 + 2)
        templates[screen] = (first, second)
        first_name = f"{screen.value.lower()}-primary.png"
        second_name = f"{screen.value.lower()}-secondary.png"
        assert cv2.imwrite(str(tmp_path / first_name), first)
        assert cv2.imwrite(str(tmp_path / second_name), second)
        screens[screen.value] = {
            "minimum_matches": 2,
            "anchors": [
                {
                    "name": "primary",
                    "template": first_name,
                    "search_region": [0.04, 0.04, 0.48, 0.48],
                    "threshold": 0.98,
                    "scales": [1.0],
                },
                {
                    "name": "secondary",
                    "template": second_name,
                    "search_region": [0.52, 0.52, 0.96, 0.96],
                    "threshold": 0.98,
                    "scales": [1.0],
                },
            ],
            "ocr": [],
            "supersedes": ["STORY"] if screen is ScreenKind.SKIP_CONFIRM else [],
        }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return TemplateCatalog.load(path), templates


def _frame(
    screen: ScreenKind,
    templates: dict[ScreenKind, tuple[np.ndarray, np.ndarray]],
) -> np.ndarray:
    frame = np.full((360, 640, 3), 61, dtype=np.uint8)
    first, second = templates[screen]
    index = SCREEN_FAMILIES.index(screen)
    positions = ((80 + index * 30, 50 + index * 12), (550 - index * 30, 300 - index * 15))
    for pattern, (left, top) in zip((first, second), positions, strict=True):
        height, width = pattern.shape
        frame[top : top + height, left : left + width] = cv2.cvtColor(pattern, cv2.COLOR_GRAY2RGB)
    return frame


@pytest.mark.parametrize("screen", SCREEN_FAMILIES)
def test_synthetic_fuyuki_screen_family_is_recognized(tmp_path: Path, screen: ScreenKind) -> None:
    catalog, templates = _catalog(tmp_path)
    recognizer = ScreenRecognizer(catalog, NullOCREngine())
    frame = _frame(screen, templates)
    mapping = ViewportMapping(Rect(0, 0, 640, 360), 0, 640)

    result = recognizer.recognize(frame, mapping)

    assert isinstance(result, Recognition)
    assert result.screen is screen
    assert result.confidence >= 0.98
    assert set(result.anchors) == {"primary", "secondary"}
    assert result.frame_sha256 == recognizer.recognize(frame.copy(), mapping).frame_sha256


def test_unrelated_conflicting_anchors_return_unknown(tmp_path: Path) -> None:
    catalog, templates = _catalog(tmp_path)
    recognizer = ScreenRecognizer(catalog, NullOCREngine())
    frame = _frame(ScreenKind.STORY, templates)
    battle = _frame(ScreenKind.BATTLE, templates)
    frame[battle != 61] = battle[battle != 61]
    mapping = ViewportMapping(Rect(0, 0, 640, 360), 0, 640)

    result = recognizer.recognize(frame, mapping)

    assert result.screen is ScreenKind.UNKNOWN
    assert "conflict:BATTLE,STORY" in result.evidence


def test_specific_overlay_supersedes_its_parent_screen(tmp_path: Path) -> None:
    catalog, templates = _catalog(tmp_path)
    recognizer = ScreenRecognizer(catalog, NullOCREngine())
    frame = _frame(ScreenKind.STORY, templates)
    overlay = _frame(ScreenKind.SKIP_CONFIRM, templates)
    frame[overlay != 61] = overlay[overlay != 61]
    mapping = ViewportMapping(Rect(0, 0, 640, 360), 0, 640)

    result = recognizer.recognize(frame, mapping)

    assert result.screen is ScreenKind.SKIP_CONFIRM
    assert "supersedes:STORY" in result.evidence


class _FakeOCR:
    def read(self, image: np.ndarray, *, whitelist: str | None = None) -> OCRResult:
        assert image.shape[:2] == (72, 128)
        assert whitelist == "NEXT"
        return OCRResult("NEXT", 0.93)


def test_ocr_is_bounded_to_configured_region_and_is_only_supporting_evidence(tmp_path: Path) -> None:
    catalog, templates = _catalog(tmp_path)
    data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    data["screens"]["TUTORIAL_MAP"]["ocr"] = [
        {
            "name": "next_text",
            "region": [0.40, 0.40, 0.60, 0.60],
            "whitelist": "NEXT",
        }
    ]
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    catalog = TemplateCatalog.load(tmp_path / "manifest.json")
    recognizer = ScreenRecognizer(catalog, _FakeOCR())
    frame = _frame(ScreenKind.TUTORIAL_MAP, templates)
    mapping = ViewportMapping(Rect(0, 0, 640, 360), 0, 640)

    result = recognizer.recognize(frame, mapping)

    assert result.screen is ScreenKind.TUTORIAL_MAP
    assert result.text == {"next_text": "NEXT"}

    blank = np.zeros_like(frame)
    assert recognizer.recognize(blank, mapping).screen is ScreenKind.UNKNOWN


def test_tesseract_tsv_parser_ignores_non_word_rows_and_averages_confidence() -> None:
    tsv = "level\tconf\ttext\n1\t-1\t\n5\t90\tFlame\n5\t80\tCity\n"

    result = TesseractOCREngine._parse_tsv(tsv)

    assert result.text == "Flame City"
    assert result.confidence == pytest.approx(0.85)


RECORDED_ROOT = Path(
    os.environ.get(
        "FGO_RECORDED_FRAMES",
        r"C:\Users\User\Documents\New project\fgo-supervised-assistant\data\recordings\tutorial-fuyuki-formation-run-9",
    )
)
RECORDED_EXAMPLES = {
    ScreenKind.STORY: "obs-95f1fc897a5e433ea0866775e210a2f8",
    ScreenKind.SKIP_CONFIRM: "obs-8ab23df1a0e447ff80400aa3c3a22f59",
    ScreenKind.SUPPORT_SELECT: "obs-5ecbab3ce18048eebbfe22c127ec955a",
    ScreenKind.PARTY_CONFIRM: "obs-3a92caba44fb433db8c8985e5b39f758",
    ScreenKind.BATTLE: "obs-facd279e01304e74ac7ef390a8730f77",
    ScreenKind.QUEST_RESULT: "obs-83f713559d1847b3bdad314ade0ab4fa",
    ScreenKind.TUTORIAL_MAP: "obs-927c231e2c8a4afabf135816d427a394",
}


@pytest.mark.skipif(not RECORDED_ROOT.exists(), reason="local redacted Fuyuki recording is unavailable")
@pytest.mark.parametrize("screen,observation_id", RECORDED_EXAMPLES.items())
def test_recorded_fuyuki_screen_family_is_recognized(
    screen: ScreenKind,
    observation_id: str,
) -> None:
    project_root = Path(__file__).parents[1]
    catalog = TemplateCatalog.load(project_root / "templates" / "manifest.json")
    recognizer = ScreenRecognizer(catalog, NullOCREngine())
    bgr = cv2.imread(str(RECORDED_ROOT / "frames" / f"{observation_id}.png"))
    assert bgr is not None
    frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mapping = ViewportMapping(Rect(55, 40, 1819, 1032), 40, 1819)

    result = recognizer.recognize(frame, mapping)

    assert result.screen is screen
    assert result.confidence >= 0.92
