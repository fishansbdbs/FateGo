from __future__ import annotations

"""Fast, template-free screen perception for FGO in LDPlayer.

Instead of the heavy local vision-language model the design doc imagines, this
uses cheap colour/geometry probes over the mapped 16:9 game viewport. Every
probe runs in well under a millisecond, which is what makes the agent's
decisions fast. All positions are normalised (0..1) fractions of the viewport,
so they hold regardless of the LDPlayer window size.

The numbers here are tuned for FGO NA in landscape. They are intentionally kept
together and named so they are easy to re-calibrate against a live screen.
"""

from dataclasses import dataclass, field
from enum import Enum

import cv2
import numpy as np

from .viewport_mapper import ViewportMapping


class Screen(str, Enum):
    BATTLE_COMMAND = "BATTLE_COMMAND"      # Attack button visible; pick/skills phase
    COMMAND_CARDS = "COMMAND_CARDS"        # 5 command cards shown
    MAP = "MAP"                            # singularity / free-quest map with nodes
    SUPPORT_SELECT = "SUPPORT_SELECT"      # choose a support servant
    CONFIRM_DIALOG = "CONFIRM_DIALOG"      # yellow/blue confirm button (start, skip-yes, apple...)
    RESULT_TAP = "RESULT_TAP"              # results / "tap to continue" / drops / bond / friend
    STORY = "STORY"                        # cutscene / dialogue -> skippable
    LOADING = "LOADING"                    # mostly black/near-static loading frame
    UNKNOWN = "UNKNOWN"


# --- colour ranges (OpenCV HSV: H 0-179, S 0-255, V 0-255) -----------------

HSV_ORANGE_BADGE = ((7, 150, 150), (22, 255, 255))     # the red/orange "1" quest badge
HSV_BLUE_CHEVRON = ((92, 110, 170), (120, 255, 255))   # blue ">>" quest markers
HSV_ATTACK_RED = ((0, 140, 110), (9, 255, 255))        # Attack button body (low red)
HSV_ATTACK_RED2 = ((168, 140, 110), (179, 255, 255))   # Attack button body (high red)
HSV_GOLD_BUTTON = ((20, 120, 170), (34, 255, 255))     # gold/yellow confirm buttons


@dataclass(frozen=True, slots=True)
class Marker:
    nx: float
    ny: float
    area: float


@dataclass(slots=True)
class Reading:
    screen: Screen
    confidence: float
    markers: list[Marker] = field(default_factory=list)
    confirm: tuple[float, float] | None = None
    mean_value: float = 0.0
    note: str = ""


def _hsv(img_rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(np.ascontiguousarray(img_rgb), cv2.COLOR_RGB2HSV)


def _mask_fraction(hsv: np.ndarray, region, lo, hi) -> float:
    x0, y0, x1, y1 = region
    h, w = hsv.shape[:2]
    sub = hsv[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if sub.size == 0:
        return 0.0
    mask = cv2.inRange(sub, np.array(lo, np.uint8), np.array(hi, np.uint8))
    return float(np.count_nonzero(mask)) / mask.size


def _largest_blob_frac(hsv: np.ndarray, region, lo, hi) -> float:
    """Area (as a fraction of the whole frame) of the largest colour blob in a region."""
    x0, y0, x1, y1 = region
    h, w = hsv.shape[:2]
    sub = hsv[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if sub.size == 0:
        return 0.0
    mask = cv2.inRange(sub, np.array(lo, np.uint8), np.array(hi, np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    return float(max(cv2.contourArea(c) for c in contours)) / float(h * w)


def _find_blobs(hsv: np.ndarray, lo, hi, min_area_frac: float) -> list[Marker]:
    h, w = hsv.shape[:2]
    mask = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[Marker] = []
    frame_area = float(h * w)
    for c in contours:
        area = cv2.contourArea(c)
        if area / frame_area < min_area_frac:
            continue
        m = cv2.moments(c)
        if m["m00"] == 0:
            continue
        cx = (m["m10"] / m["m00"]) / w
        cy = (m["m01"] / m["m00"]) / h
        out.append(Marker(cx, cy, area / frame_area))
    return out


class Perception:
    """Classify the current game screen from one RGB frame."""

    def crop(self, image_rgb: np.ndarray, mapping: ViewportMapping) -> np.ndarray:
        return mapping.crop(image_rgb)

    def read(self, image_rgb: np.ndarray, mapping: ViewportMapping) -> Reading:
        view = self.crop(image_rgb, mapping)
        if view.size == 0:
            return Reading(Screen.UNKNOWN, 0.0)
        hsv = _hsv(view)
        mean_v = float(hsv[:, :, 2].mean())

        # Attack button: a large, vivid disc in the lower-right. Live testing
        # showed its hue is BLUE here (not the red assumed earlier) and can vary
        # by state/version, so detect it by size + saturation/brightness rather
        # than a specific colour. The area threshold keeps the smaller blue map
        # "MENU" button from being mistaken for it.
        attack = _largest_blob_frac(hsv, (0.78, 0.58, 1.0, 0.93), (0, 90, 160), (179, 255, 255))
        if attack >= 0.015:
            return Reading(Screen.BATTLE_COMMAND, min(1.0, 0.55 + attack * 5), mean_value=mean_v,
                           note=f"attack_blob={attack:.4f}")

        # Quest markers: orange "1" badges and blue chevrons across the map.
        badges = _find_blobs(hsv, *HSV_ORANGE_BADGE, min_area_frac=0.00035)
        chevrons = _find_blobs(hsv, *HSV_BLUE_CHEVRON, min_area_frac=0.00045)
        markers = _dedupe(badges + chevrons)
        if len(markers) >= 1 and mean_v > 25:
            # Prefer nodes that carry an orange badge (uncleared / available).
            conf = 0.55 + 0.1 * min(3, len(markers))
            return Reading(Screen.MAP, min(0.95, conf), markers=markers, mean_value=mean_v,
                           note=f"badges={len(badges)} chevrons={len(chevrons)}")

        # Gold confirm button (Start Quest / Yes / Attention / apple confirm).
        gold = _find_blobs(hsv, *HSV_GOLD_BUTTON, min_area_frac=0.004)
        gold_lower = [m for m in gold if m.ny > 0.55]
        if gold_lower:
            target = max(gold_lower, key=lambda m: m.area)
            return Reading(Screen.CONFIRM_DIALOG, 0.7, confirm=(target.nx, target.ny),
                           mean_value=mean_v, note="gold_button")

        # Near-black frame -> loading; wait rather than tap.
        if mean_v < 18:
            return Reading(Screen.LOADING, 0.6, mean_value=mean_v)

        # Anything else that is bright and busy: treat as story/dialogue/result
        # that we advance by tapping. The caller uses frame-diff to avoid
        # hammering a genuinely static screen.
        return Reading(Screen.STORY, 0.3, mean_value=mean_v)


def _dedupe(markers: list[Marker], min_dist: float = 0.06) -> list[Marker]:
    kept: list[Marker] = []
    for m in sorted(markers, key=lambda k: -k.area):
        if all((m.nx - k.nx) ** 2 + (m.ny - k.ny) ** 2 > min_dist ** 2 for k in kept):
            kept.append(m)
    return kept


def frame_signature(image_rgb: np.ndarray, mapping: ViewportMapping) -> np.ndarray:
    """A tiny downscaled grayscale thumbnail used for change detection."""
    view = mapping.crop(image_rgb)
    if view.size == 0:
        return np.zeros((8, 8), np.float32)
    gray = cv2.cvtColor(np.ascontiguousarray(view), cv2.COLOR_RGB2GRAY)
    return cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32)


def frames_differ(a: np.ndarray, b: np.ndarray, threshold: float = 6.0) -> bool:
    if a.shape != b.shape:
        return True
    return float(np.abs(a - b).mean()) > threshold
