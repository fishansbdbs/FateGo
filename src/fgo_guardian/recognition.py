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

    @staticmethod
    def _loading_transition(
        gray: np.ndarray,
        mapping: ViewportMapping,
        frame_hash: str,
    ) -> Recognition | None:
        """Recognize FGO's black inter-wave transition without guessing an action."""
        viewport = mapping.viewport
        crop = gray[viewport.top : viewport.bottom, viewport.left : viewport.right]
        height, width = crop.shape
        white_ratio = float(np.mean(crop >= 245))
        top_left_dark = float(np.mean(crop[: round(height * 0.16), : round(width * 0.25)] <= 16))
        bottom_left_dark = float(np.mean(crop[round(height * 0.80) :, : round(width * 0.25)] <= 16))
        center_white = float(
            np.mean(
                crop[
                    round(height * 0.20) : round(height * 0.70),
                    round(width * 0.30) : round(width * 0.90),
                ]
                >= 245
            )
        )
        if (
            white_ratio >= 0.75
            and top_left_dark >= 0.90
            and bottom_left_dark >= 0.80
            and center_white >= 0.95
        ):
            margin = min(
                1.0,
                max(0.0, (white_ratio - 0.75) / 0.15),
                max(0.0, (top_left_dark - 0.90) / 0.10),
                max(0.0, (bottom_left_dark - 0.80) / 0.20),
                max(0.0, (center_white - 0.95) / 0.05),
            )
            confidence = 0.92 + 0.079 * margin
            center = Rect(
                viewport.left + round(width * 0.30),
                viewport.top + round(height * 0.20),
                viewport.left + round(width * 0.90),
                viewport.top + round(height * 0.70),
            )
            return Recognition(
                ScreenKind.LOADING,
                confidence,
                MappingProxyType({"loading_flash_center": center}),
                MappingProxyType({}),
                (
                    f"semantic:white-flash:{white_ratio:.4f}",
                    f"semantic:flash-center:{center_white:.4f}",
                ),
                frame_hash,
            )
        dark_ratio = float(np.mean(crop <= 16))
        if dark_ratio < 0.98:
            return None
        bottom_height = max(4, round(crop.shape[0] * 0.015))
        bottom = crop[-bottom_height:]
        bright = bottom >= 180
        row_support = np.mean(bright, axis=1)
        best_row = int(np.argmax(row_support))
        best_support = float(row_support[best_row])
        if best_support < 0.55:
            return None
        columns = np.flatnonzero(bright[best_row])
        if columns.size == 0:
            return None
        absolute_top = viewport.bottom - bottom_height + best_row
        bar = Rect(
            viewport.left + int(columns[0]),
            absolute_top,
            viewport.left + int(columns[-1]) + 1,
            absolute_top + 1,
        )
        margin = min(
            1.0,
            max(0.0, (dark_ratio - 0.98) / 0.02),
            max(0.0, (best_support - 0.55) / 0.30),
        )
        confidence = 0.92 + 0.079 * margin
        return Recognition(
            ScreenKind.LOADING,
            confidence,
            MappingProxyType({"loading_navigation_bar": bar}),
            MappingProxyType({}),
            (
                f"semantic:dark-transition:{dark_ratio:.4f}",
                f"semantic:navigation-bar:{best_support:.4f}",
            ),
            frame_hash,
        )

    def _skip_processing_transition(
        self,
        frame: np.ndarray,
        gray: np.ndarray,
        mapping: ViewportMapping,
        frame_hash: str,
    ) -> Recognition | None:
        """Recognize the deterministic blue spinner after confirming Story skip."""
        skip_match: tuple[float, Rect] | None = None
        for rule in self.catalog.rules:
            if rule.screen is not ScreenKind.STORY:
                continue
            for anchor in rule.anchors:
                if anchor.name == "skip":
                    skip_match = self._match_anchor(gray, mapping, anchor)
                    break
            break
        if skip_match is None:
            return None

        spinner = mapping.normalized_rect((0.60, 0.70, 0.69, 0.87))
        crop = frame[spinner.top : spinner.bottom, spinner.left : spinner.right]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        blue = (
            (hsv[:, :, 0] >= 85)
            & (hsv[:, :, 0] <= 135)
            & (hsv[:, :, 1] >= 100)
            & (hsv[:, :, 2] >= 120)
        ).astype(np.uint8)
        blue_ratio = float(np.mean(blue))
        component_count, _, stats, _ = cv2.connectedComponentsWithStats(blue, 8)
        visible_pieces = sum(
            int(area) >= 20
            for area in stats[1:component_count, cv2.CC_STAT_AREA]
        )
        if blue_ratio < 0.15 or visible_pieces < 8:
            return None

        margin = min(
            1.0,
            max(0.0, (blue_ratio - 0.15) / 0.10),
            max(0.0, (visible_pieces - 8) / 8),
        )
        skip_score, skip_rect = skip_match
        confidence = min(skip_score, 0.92 + 0.079 * margin)
        return Recognition(
            ScreenKind.LOADING,
            confidence,
            MappingProxyType(
                {
                    "skip": skip_rect,
                    "skip_processing_spinner": spinner,
                }
            ),
            MappingProxyType({}),
            (
                f"template:skip:{skip_score:.4f}",
                f"semantic:skip-processing-blue:{blue_ratio:.4f}",
                f"semantic:skip-processing-pieces:{visible_pieces}",
            ),
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
            skip_processing = self._skip_processing_transition(frame, gray, mapping, frame_hash)
            if skip_processing is not None:
                return skip_processing
            loading = self._loading_transition(gray, mapping, frame_hash)
            if loading is not None:
                return loading
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
