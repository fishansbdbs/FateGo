from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import cv2
import numpy as np

from .agent_models import ScreenKind


NormalizedRect = tuple[float, float, float, float]


def _normalized_rect(value: object, field: str) -> NormalizedRect:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{field} must contain four normalized coordinates")
    result = tuple(float(item) for item in value)
    left, top, right, bottom = result
    if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
        raise ValueError(f"{field} must satisfy 0 <= left < right <= 1")
    return result


@dataclass(frozen=True, slots=True)
class TemplateAnchor:
    name: str
    template_path: Path
    search_region: NormalizedRect
    threshold: float
    scales: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class OCRRegion:
    name: str
    region: NormalizedRect
    whitelist: str | None


@dataclass(frozen=True, slots=True)
class ScreenRule:
    screen: ScreenKind
    minimum_matches: int
    anchors: tuple[TemplateAnchor, ...]
    ocr: tuple[OCRRegion, ...]
    supersedes: tuple[ScreenKind, ...]


@dataclass(frozen=True, slots=True)
class TemplateCatalog:
    version: str
    rules: tuple[ScreenRule, ...]
    templates: Mapping[Path, np.ndarray]

    @classmethod
    def load(cls, manifest_path: str | Path) -> "TemplateCatalog":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("version")
        screens = data.get("screens")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("template manifest requires a non-empty version")
        if not isinstance(screens, dict) or not screens:
            raise ValueError("template manifest requires screen rules")

        root = path.parent
        rules: list[ScreenRule] = []
        loaded_templates: dict[Path, np.ndarray] = {}
        for raw_screen, raw_rule in screens.items():
            try:
                screen = ScreenKind(raw_screen)
            except ValueError as error:
                raise ValueError(f"unknown screen kind in template manifest: {raw_screen}") from error
            if screen is ScreenKind.UNKNOWN:
                raise ValueError("UNKNOWN cannot have an actionable recognition rule")
            if not isinstance(raw_rule, dict):
                raise ValueError(f"screen rule {raw_screen} must be an object")
            raw_anchors = raw_rule.get("anchors")
            if not isinstance(raw_anchors, list) or len(raw_anchors) < 2:
                raise ValueError(f"screen rule {raw_screen} requires at least two anchors")
            minimum_matches = int(raw_rule.get("minimum_matches", 2))
            if not 2 <= minimum_matches <= len(raw_anchors):
                raise ValueError(f"screen rule {raw_screen} has an invalid minimum_matches")

            anchors: list[TemplateAnchor] = []
            anchor_names: set[str] = set()
            for raw_anchor in raw_anchors:
                if not isinstance(raw_anchor, dict):
                    raise ValueError(f"anchor for {raw_screen} must be an object")
                name = str(raw_anchor.get("name", "")).strip()
                if not name or name in anchor_names:
                    raise ValueError(f"anchor names for {raw_screen} must be non-empty and unique")
                anchor_names.add(name)
                relative = Path(str(raw_anchor.get("template", "")))
                template_path = (root / relative).resolve()
                if root != template_path and root not in template_path.parents:
                    raise ValueError("template path escapes the catalog directory")
                threshold = float(raw_anchor.get("threshold", 0.92))
                if not 0.0 < threshold <= 1.0:
                    raise ValueError(f"anchor {name} has an invalid threshold")
                raw_scales = raw_anchor.get("scales", [1.0])
                if not isinstance(raw_scales, list) or not raw_scales:
                    raise ValueError(f"anchor {name} requires at least one scale")
                scales = tuple(float(scale) for scale in raw_scales)
                if any(scale <= 0.0 for scale in scales):
                    raise ValueError(f"anchor {name} has a non-positive scale")
                anchor = TemplateAnchor(
                    name=name,
                    template_path=template_path,
                    search_region=_normalized_rect(raw_anchor.get("search_region"), f"{name}.search_region"),
                    threshold=threshold,
                    scales=scales,
                )
                anchors.append(anchor)
                if template_path not in loaded_templates:
                    image = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
                    if image is None or image.size == 0:
                        raise FileNotFoundError(f"template is missing or unreadable: {template_path}")
                    image.setflags(write=False)
                    loaded_templates[template_path] = image

            ocr_regions: list[OCRRegion] = []
            ocr_names: set[str] = set()
            for raw_ocr in raw_rule.get("ocr", []):
                if not isinstance(raw_ocr, dict):
                    raise ValueError(f"OCR region for {raw_screen} must be an object")
                name = str(raw_ocr.get("name", "")).strip()
                if not name or name in ocr_names:
                    raise ValueError(f"OCR region names for {raw_screen} must be non-empty and unique")
                ocr_names.add(name)
                whitelist = raw_ocr.get("whitelist")
                ocr_regions.append(
                    OCRRegion(
                        name,
                        _normalized_rect(raw_ocr.get("region"), f"{name}.region"),
                        str(whitelist) if whitelist else None,
                    )
                )

            supersedes: list[ScreenKind] = []
            for item in raw_rule.get("supersedes", []):
                superseded = ScreenKind(item)
                if superseded is screen or superseded is ScreenKind.UNKNOWN:
                    raise ValueError(f"screen rule {raw_screen} has an invalid supersedes entry")
                supersedes.append(superseded)
            rules.append(
                ScreenRule(
                    screen,
                    minimum_matches,
                    tuple(anchors),
                    tuple(ocr_regions),
                    tuple(supersedes),
                )
            )
        rules.sort(key=lambda item: item.screen.value)
        return cls(version.strip(), tuple(rules), MappingProxyType(loaded_templates))
