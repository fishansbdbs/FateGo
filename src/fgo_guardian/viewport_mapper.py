from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .models import Rect


@dataclass(frozen=True, slots=True)
class ViewportMapping:
    viewport: Rect
    titlebar_bottom: int
    toolbar_left: int

    @property
    def signature(self) -> tuple[Rect, int, int]:
        return self.viewport, self.titlebar_bottom, self.toolbar_left

    def crop(self, image: np.ndarray) -> np.ndarray:
        return image[self.viewport.top:self.viewport.bottom, self.viewport.left:self.viewport.right]

    def normalized_rect(self, values: tuple[float, float, float, float]) -> Rect:
        left, top, right, bottom = values
        if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
            raise ValueError("normalized rectangle must satisfy 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
        return Rect(
            self.viewport.left + round(left * self.viewport.width),
            self.viewport.top + round(top * self.viewport.height),
            self.viewport.left + round(right * self.viewport.width),
            self.viewport.top + round(bottom * self.viewport.height),
        )

    def normalized_target(self, rect: Rect) -> tuple[float, float, float, float]:
        if not (
            self.viewport.left <= rect.left < rect.right <= self.viewport.right
            and self.viewport.top <= rect.top < rect.bottom <= self.viewport.bottom
        ):
            raise ValueError("target rectangle must be inside the Android viewport")
        return (
            (rect.left - self.viewport.left) / self.viewport.width,
            (rect.top - self.viewport.top) / self.viewport.height,
            (rect.right - self.viewport.left) / self.viewport.width,
            (rect.bottom - self.viewport.top) / self.viewport.height,
        )


class ViewportMapper:
    TARGET_ASPECT = 16 / 9
    MIN_WIDTH = 640
    MIN_HEIGHT = 360
    MIN_EDGE_STRENGTH = 20.0
    MIN_SUSTAINED_CONTRAST = 5.0
    MIN_EDGE_SUPPORT = 0.75
    MIN_TITLEBAR_FULL_SUPPORT = 0.53
    MIN_TITLEBAR_BOUNDED_SUPPORT = 0.25
    MIN_TITLEBAR_STRONG_BAND_FULL_SUPPORT = 0.40
    MIN_TITLEBAR_STRONG_BAND_SUPPORT = 0.95
    MIN_TITLEBAR_ANIMATED_FULL_SUPPORT = 0.45
    MIN_TITLEBAR_ANIMATED_PAIRED_FULL_SUPPORT = 0.40
    MIN_TITLEBAR_ANIMATED_SUSTAINED_CONTRAST = 20.0
    MAX_TITLEBAR_ANIMATED_SEARCH_FRACTION = 0.043
    MIN_TITLEBAR_TOP_BAND_DOMINANCE_MARGIN = 0.15
    MIN_TITLEBAR_DENSE_DISTRACTOR_COUNT = 3
    MIN_TITLEBAR_DENSE_DISTRACTOR_SPAN_FRACTION = 0.02
    MIN_TOOLBAR_BOUNDED_SUPPORT = 0.70
    MIN_TOOLBAR_STRONG_BAND_FULL_SUPPORT = 0.70
    MIN_TOOLBAR_STRONG_BAND_SUPPORT = 0.75
    EDGE_EXCLUSION_RADIUS = 6
    TITLEBAR_ADJACENT_CANONICALIZATION_RADIUS = 1
    TOOLBAR_ADJACENT_CANONICALIZATION_RADIUS = 1
    TOOLBAR_NEAR_PLATEAU_FRACTION = 0.70
    TITLEBAR_NEAR_SUPPORT_MARGIN = 0.02
    TRAILING_EDGE_SUPPORT_FRACTION = 0.05
    TOOLBAR_SUPPORT_BAND = (0.85, 0.90)
    DOMINANT_PLATEAU_FRACTION = 0.75
    OUTER_BORDER_EXCLUSION_FRACTION = 0.02
    MAX_TITLEBAR_SEARCH_FRACTION = 0.12

    @staticmethod
    def _sustained_contrast(image: np.ndarray, index: int, axis: int) -> float:
        gap = 4
        width = 8
        if axis == 0:
            before = image[max(0, index - gap - width):max(0, index - gap)]
            after = image[min(image.shape[0], index + gap):min(image.shape[0], index + gap + width)]
        else:
            before = image[:, max(0, index - gap - width):max(0, index - gap)]
            after = image[:, min(image.shape[1], index + gap):min(image.shape[1], index + gap + width)]
        if before.size == 0 or after.size == 0:
            return 0.0
        return float(np.linalg.norm(before.mean(axis=(0, 1)) - after.mean(axis=(0, 1))))

    def _credible_edge(
        self,
        profile: np.ndarray,
        start: int,
        stop: int,
        label: str,
        image: np.ndarray,
        gradient: np.ndarray,
        axis: int,
        support_bounds: tuple[int, int] | None = None,
        bounded_support_threshold: float | None = None,
        full_support_threshold: float | None = None,
        prefer_trailing_candidate: bool = False,
    ) -> int:
        values = np.asarray(profile[start:stop], dtype=float).copy()
        if stop <= start or values.size == 0:
            raise ValueError("edge search region is empty")
        candidates: list[int] = []

        minimum_bounded_support = (
            self.MIN_EDGE_SUPPORT
            if bounded_support_threshold is None
            else bounded_support_threshold
        )
        minimum_full_support = (
            self.MIN_EDGE_SUPPORT
            if full_support_threshold is None
            else full_support_threshold
        )

        def support_values(absolute: int) -> tuple[float, float]:
            perpendicular = gradient[absolute] if axis == 0 else gradient[:, absolute]
            support = float(np.mean(perpendicular >= self.MIN_EDGE_STRENGTH))
            if support_bounds is not None:
                support_start, support_stop = support_bounds
                bounded = perpendicular[support_start:support_stop]
                bounded_support = float(np.mean(bounded >= self.MIN_EDGE_STRENGTH))
            else:
                bounded_support = support
            return support, bounded_support

        def titlebar_support_is_credible(
            absolute: int,
            full_support_margin: float = 0.0,
        ) -> bool:
            support, bounded_support = support_values(absolute)
            sustained_contrast = self._sustained_contrast(
                image, absolute, axis
            )
            animated_search_limit = round(
                image.shape[0] * self.MAX_TITLEBAR_ANIMATED_SEARCH_FRACTION
            )
            is_in_animated_titlebar_zone = absolute < animated_search_limit
            paired_animated_support = False
            if (
                is_in_animated_titlebar_zone
                and support
                >= self.MIN_TITLEBAR_ANIMATED_PAIRED_FULL_SUPPORT
                - full_support_margin
                and sustained_contrast
                >= self.MIN_TITLEBAR_ANIMATED_SUSTAINED_CONTRAST
            ):
                for neighbor in (absolute - 1, absolute + 1):
                    if not 0 <= neighbor < animated_search_limit:
                        continue
                    neighbor_support, _ = support_values(neighbor)
                    if (
                        neighbor_support
                        >= self.MIN_TITLEBAR_ANIMATED_PAIRED_FULL_SUPPORT
                        - full_support_margin
                        and self._sustained_contrast(image, neighbor, axis)
                        >= self.MIN_TITLEBAR_ANIMATED_SUSTAINED_CONTRAST
                    ):
                        paired_animated_support = True
                        break
            return (
                support
                >= self.MIN_TITLEBAR_FULL_SUPPORT - full_support_margin
                and bounded_support >= self.MIN_TITLEBAR_BOUNDED_SUPPORT
            ) or (
                support
                >= self.MIN_TITLEBAR_STRONG_BAND_FULL_SUPPORT
                - full_support_margin
                and bounded_support >= self.MIN_TITLEBAR_STRONG_BAND_SUPPORT
            ) or (
                is_in_animated_titlebar_zone
                and support
                >= self.MIN_TITLEBAR_ANIMATED_FULL_SUPPORT
                - full_support_margin
                and sustained_contrast
                >= self.MIN_TITLEBAR_ANIMATED_SUSTAINED_CONTRAST
            ) or paired_animated_support

        def invariantly_credible(absolute: int) -> bool:
            support, bounded_support = support_values(absolute)
            support_is_credible = (
                titlebar_support_is_credible(absolute)
                if label == "titlebar"
                else (
                    support >= minimum_full_support
                    or (
                        label == "toolbar"
                        and support
                        >= self.MIN_TOOLBAR_STRONG_BAND_FULL_SUPPORT
                        and bounded_support
                        >= self.MIN_TOOLBAR_STRONG_BAND_SUPPORT
                    )
                )
            )
            return (
                self._sustained_contrast(image, absolute, axis)
                >= self.MIN_SUSTAINED_CONTRAST
                and support_is_credible
            )

        def has_bounded_support(absolute: int) -> bool:
            _, bounded_support = support_values(absolute)
            return bounded_support >= minimum_bounded_support

        while values.size:
            winner = int(np.argmax(values))
            if float(values[winner]) < self.MIN_EDGE_STRENGTH:
                break
            absolute = start + winner
            left = max(0, winner - self.EDGE_EXCLUSION_RADIUS)
            right = min(values.size, winner + self.EDGE_EXCLUSION_RADIUS + 1)
            minimum_plateau_strength = max(
                self.MIN_EDGE_STRENGTH,
                float(np.max(values[left:right])) * self.DOMINANT_PLATEAU_FRACTION,
            )
            dominant_plateau = [
                start + relative
                for relative in range(left, right)
                if values[relative] >= minimum_plateau_strength
            ]
            credible_plateau = [
                candidate
                for candidate in dominant_plateau
                if invariantly_credible(candidate)
            ]
            accepted = (
                bool(credible_plateau)
                if label == "titlebar"
                else any(
                    has_bounded_support(candidate)
                    for candidate in credible_plateau
                )
            )
            if accepted:
                canonical = credible_plateau[0]
                adjacent_leading = (
                    canonical - self.TOOLBAR_ADJACENT_CANONICALIZATION_RADIUS
                )
                if (
                    label == "toolbar"
                    and adjacent_leading >= start
                    and float(profile[adjacent_leading]) >= self.MIN_EDGE_STRENGTH
                    and float(profile[adjacent_leading])
                    >= float(profile[canonical])
                    * self.TOOLBAR_NEAR_PLATEAU_FRACTION
                    and invariantly_credible(adjacent_leading)
                    and has_bounded_support(adjacent_leading)
                ):
                    canonical = adjacent_leading
                leading = dominant_plateau[0]
                if (
                    label == "titlebar"
                    and canonical - leading
                    <= self.TITLEBAR_ADJACENT_CANONICALIZATION_RADIUS
                    and titlebar_support_is_credible(
                        leading,
                        full_support_margin=self.TITLEBAR_NEAR_SUPPORT_MARGIN,
                    )
                    and self._sustained_contrast(image, leading, axis)
                    >= self.MIN_SUSTAINED_CONTRAST
                ):
                    canonical = leading
                candidates.append(canonical)
                values[left:right] = 0.0
            else:
                for candidate in dominant_plateau:
                    values[candidate - start] = 0.0
        if not candidates:
            raise ValueError(f"{label} edge is too weak")
        if label == "titlebar" and len(candidates) > 1:
            ordered_candidates = sorted(candidates)
            collapsed_candidates = [ordered_candidates[0]]
            previous_candidate = ordered_candidates[0]
            for candidate in ordered_candidates[1:]:
                if (
                    candidate - previous_candidate
                    > self.TITLEBAR_ADJACENT_CANONICALIZATION_RADIUS
                ):
                    collapsed_candidates.append(candidate)
                previous_candidate = candidate
            candidates = collapsed_candidates
        if len(candidates) != 1:
            if prefer_trailing_candidate:
                return max(candidates)
            if label == "titlebar":
                animated_search_limit = round(
                    image.shape[0]
                    * self.MAX_TITLEBAR_ANIMATED_SEARCH_FRACTION
                )
                top_candidates = [
                    candidate
                    for candidate in candidates
                    if candidate < animated_search_limit
                ]
                if len(top_candidates) == 1:
                    top_candidate = top_candidates[0]
                    lower_candidates = [
                        candidate
                        for candidate in candidates
                        if candidate != top_candidate
                    ]
                    _, top_bounded_support = support_values(top_candidate)
                    strongest_lower_bounded_support = max(
                        support_values(candidate)[1]
                        for candidate in lower_candidates
                    )
                    if (
                        top_bounded_support
                        >= strongest_lower_bounded_support
                        + self.MIN_TITLEBAR_TOP_BAND_DOMINANCE_MARGIN
                    ):
                        return top_candidate
                    if (
                        titlebar_support_is_credible(top_candidate)
                        and strongest_lower_bounded_support
                        < self.MIN_EDGE_SUPPORT
                    ):
                        return top_candidate
                    if (
                        titlebar_support_is_credible(top_candidate)
                        and len(lower_candidates)
                        >= self.MIN_TITLEBAR_DENSE_DISTRACTOR_COUNT
                        and max(lower_candidates) - min(lower_candidates)
                        >= round(
                            image.shape[0]
                            * self.MIN_TITLEBAR_DENSE_DISTRACTOR_SPAN_FRACTION
                        )
                    ):
                        return top_candidate
            raise ValueError(f"{label} edge is ambiguous")
        return candidates[0]

    def locate(self, image: np.ndarray) -> ViewportMapping:
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("expected an RGB frame")
        height, width = image.shape[:2]
        if width < self.MIN_WIDTH or height < self.MIN_HEIGHT:
            raise ValueError("LDPlayer frame is too small for FGO")
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        horizontal_gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
        vertical_gradient = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
        horizontal = np.mean(horizontal_gradient, axis=1)
        vertical = np.mean(vertical_gradient, axis=0)
        toolbar_support_bounds = tuple(
            round(height * fraction) for fraction in self.TOOLBAR_SUPPORT_BAND
        )
        toolbar_left = self._credible_edge(
            vertical,
            round(width * 0.65),
            min(
                width - 2,
                round(width * (1.0 - self.OUTER_BORDER_EXCLUSION_FRACTION)),
            ),
            "toolbar",
            image,
            vertical_gradient,
            1,
            support_bounds=toolbar_support_bounds,
            bounded_support_threshold=self.MIN_TOOLBAR_BOUNDED_SUPPORT,
            prefer_trailing_candidate=True,
        ) + 1
        trailing_width = max(1, round(toolbar_left * self.TRAILING_EDGE_SUPPORT_FRACTION))
        titlebar_bottom = self._credible_edge(
            horizontal,
            max(4, round(height * 0.01)),
            max(5, round(height * self.MAX_TITLEBAR_SEARCH_FRACTION)),
            "titlebar",
            image,
            horizontal_gradient,
            0,
            support_bounds=(toolbar_left - trailing_width, toolbar_left),
            bounded_support_threshold=self.MIN_TITLEBAR_BOUNDED_SUPPORT,
            full_support_threshold=self.MIN_TITLEBAR_FULL_SUPPORT,
        ) + 1
        available_width = toolbar_left
        available_height = height - titlebar_bottom
        if available_width / available_height >= self.TARGET_ASPECT:
            viewport_height = available_height
            viewport_width = round(viewport_height * self.TARGET_ASPECT)
            left = max(0, toolbar_left - viewport_width)
            top = titlebar_bottom
        else:
            viewport_width = available_width
            viewport_height = round(viewport_width / self.TARGET_ASPECT)
            left = 0
            top = titlebar_bottom + max(0, (available_height - viewport_height) // 2)
        viewport = Rect(left, top, left + viewport_width, top + viewport_height)
        if viewport.width < self.MIN_WIDTH or viewport.height < self.MIN_HEIGHT:
            raise ValueError("mapped Android viewport is too small")
        if abs(viewport.width / viewport.height - self.TARGET_ASPECT) >= 0.01:
            raise ValueError("mapped Android viewport is not landscape 16:9")
        return ViewportMapping(viewport, titlebar_bottom, toolbar_left)
