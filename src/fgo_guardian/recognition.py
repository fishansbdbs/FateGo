from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping

import cv2
import numpy as np

from .agent_models import ScreenKind
from .models import Rect
from .ocr import NullOCREngine, OCREngine
from .template_catalog import ScreenRule, TemplateAnchor, TemplateCatalog
from .viewport_mapper import ViewportMapping


@dataclass(frozen=True, slots=True)
class Recognition:
    screen: ScreenKind
    confidence: float
    anchors: Mapping[str, Rect]
    text: Mapping[str, str]
    evidence: tuple[str, ...]
    frame_sha256: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    rule: ScreenRule
    confidence: float
    anchors: Mapping[str, Rect]
    evidence: tuple[str, ...]


class ScreenRecognizer:
    """Pure screen-family recognition for a fixed immutable template catalog."""

    def __init__(self, catalog: TemplateCatalog, ocr: OCREngine | None = None) -> None:
        self.catalog = catalog
        self.ocr = ocr if ocr is not None else NullOCREngine()

    @staticmethod
    def _frame_hash(frame: np.ndarray) -> str:
        digest = sha256()
        digest.update(str(frame.shape).encode("ascii"))
        digest.update(str(frame.dtype).encode("ascii"))
        digest.update(np.ascontiguousarray(frame).tobytes())
        return digest.hexdigest()

    @staticmethod
    def _gray(frame: np.ndarray) -> np.ndarray:
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError("recognition expects an RGB uint8 frame")
        return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    @staticmethod
    def _validate_mapping(frame: np.ndarray, mapping: ViewportMapping) -> None:
        height, width = frame.shape[:2]
        viewport = mapping.viewport
        if not (
            0 <= viewport.left < viewport.right <= width
            and 0 <= viewport.top < viewport.bottom <= height
        ):
            raise ValueError("viewport mapping is outside the supplied frame")

    def _match_anchor(
        self,
        gray: np.ndarray,
        mapping: ViewportMapping,
        anchor: TemplateAnchor,
    ) -> tuple[float, Rect] | None:
        search_rect = mapping.normalized_rect(anchor.search_region)
        search = gray[search_rect.top : search_rect.bottom, search_rect.left : search_rect.right]
        source = self.catalog.templates[anchor.template_path]
        best: tuple[float, int, int, int, int] | None = None
        for scale in anchor.scales:
            width = max(1, round(source.shape[1] * scale))
            height = max(1, round(source.shape[0] * scale))
            if width > search.shape[1] or height > search.shape[0]:
                continue
            template = (
                source
                if width == source.shape[1] and height == source.shape[0]
                else cv2.resize(source, (width, height), interpolation=cv2.INTER_AREA)
            )
            scores = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
            _, maximum, _, location = cv2.minMaxLoc(scores)
            if not np.isfinite(maximum):
                continue
            left, top = location
            candidate = (float(maximum), -top, -left, width, height)
            if best is None or candidate > best:
                best = candidate
        if best is None or best[0] < anchor.threshold:
            return None
        score, negative_top, negative_left, width, height = best
        left = search_rect.left - negative_left
        top = search_rect.top - negative_top
        return score, Rect(left, top, left + width, top + height)

    def _candidate(
        self,
        gray: np.ndarray,
        mapping: ViewportMapping,
        rule: ScreenRule,
    ) -> _Candidate | None:
        matches: dict[str, Rect] = {}
        scores: list[float] = []
        evidence: list[str] = []
        for anchor in rule.anchors:
            match = self._match_anchor(gray, mapping, anchor)
            if match is None:
                continue
            score, rect = match
            matches[anchor.name] = rect
            scores.append(score)
            evidence.append(f"template:{anchor.name}:{score:.4f}")
        if len(matches) < rule.minimum_matches:
            return None
        selected_scores = sorted(scores, reverse=True)[: rule.minimum_matches]
        confidence = min(selected_scores)
        return _Candidate(
            rule,
            confidence,
            MappingProxyType(dict(sorted(matches.items()))),
            tuple(sorted(evidence)),
        )

    def _read_text(
        self,
        frame: np.ndarray,
        mapping: ViewportMapping,
        rule: ScreenRule,
    ) -> tuple[Mapping[str, str], tuple[str, ...]]:
        text: dict[str, str] = {}
        evidence: list[str] = []
        for spec in rule.ocr:
            rect = mapping.normalized_rect(spec.region)
            crop = frame[rect.top : rect.bottom, rect.left : rect.right]
            result = self.ocr.read(crop, whitelist=spec.whitelist)
            text[spec.name] = result.text
            evidence.append(f"ocr:{spec.name}:{result.confidence:.4f}")
        return MappingProxyType(text), tuple(evidence)

    @staticmethod
    def _unknown(frame_hash: str, *evidence: str) -> Recognition:
        return Recognition(
            ScreenKind.UNKNOWN,
            0.0,
            MappingProxyType({}),
            MappingProxyType({}),
            tuple(evidence),
            frame_hash,
        )

    def recognize(self, frame: np.ndarray, mapping: ViewportMapping) -> Recognition:
        frame_hash = self._frame_hash(frame)
        self._validate_mapping(frame, mapping)
        gray = self._gray(frame)
        accepted = [
            candidate
            for rule in self.catalog.rules
            if (candidate := self._candidate(gray, mapping, rule)) is not None
        ]
        if not accepted:
            return self._unknown(frame_hash, "no-screen-rule-passed")

        accepted_screens = {candidate.rule.screen for candidate in accepted}
        suppressed = {
            screen
            for candidate in accepted
            for screen in candidate.rule.supersedes
            if screen in accepted_screens
        }
        remaining = [candidate for candidate in accepted if candidate.rule.screen not in suppressed]
        if len(remaining) != 1:
            conflict = ",".join(sorted(candidate.rule.screen.value for candidate in remaining))
            return self._unknown(frame_hash, f"conflict:{conflict}")

        winner = remaining[0]
        text, ocr_evidence = self._read_text(frame, mapping, winner.rule)
        supersedes_evidence = tuple(f"supersedes:{screen.value}" for screen in sorted(suppressed, key=lambda item: item.value))
        return Recognition(
            winner.rule.screen,
            winner.confidence,
            winner.anchors,
            text,
            winner.evidence + ocr_evidence + supersedes_evidence,
            frame_hash,
        )
