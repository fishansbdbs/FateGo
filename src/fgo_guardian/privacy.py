from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .agent_models import ScreenKind
from .models import Rect
from .viewport_mapper import ViewportMapping


class PersistenceBlocked(RuntimeError):
    pass


class PrivacyPolicy:
    def __init__(self, masks: dict[ScreenKind, tuple[tuple[float, float, float, float], ...]]) -> None:
        self._masks = masks

    @classmethod
    def load(cls, path: Path) -> "PrivacyPolicy":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("screen_masks"), dict):
            raise ValueError("privacy manifest must use version 1 and contain screen_masks")
        masks = {}
        for name, entries in raw["screen_masks"].items():
            if not isinstance(entries, list):
                raise ValueError("screen mask entries must be a list")
            parsed = []
            for item in entries:
                if not isinstance(item, list) or len(item) != 4:
                    raise ValueError("each privacy mask must contain four values")
                values = tuple(float(value) for value in item)
                left, top, right, bottom = values
                if not all(math.isfinite(value) for value in values) or not (
                    0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0
                ):
                    raise ValueError("privacy masks must be finite normalized rectangles")
                parsed.append(values)
            masks[ScreenKind(name)] = tuple(parsed)
        if not masks.get(ScreenKind.TITLE):
            raise ValueError("privacy manifest requires at least one TITLE mask")
        return cls(masks)

    def masks_for(self, screen: ScreenKind, mapping: ViewportMapping) -> tuple[Rect, ...]:
        if screen is ScreenKind.UNKNOWN:
            raise PersistenceBlocked("unknown screen cannot be persisted")
        entries = self._masks.get(screen, ())
        if screen is ScreenKind.TITLE and not entries:
            raise PersistenceBlocked("TITLE cannot be persisted without privacy masks")
        try:
            return tuple(mapping.normalized_rect(values) for values in entries)
        except ValueError as error:
            raise PersistenceBlocked("privacy mask geometry is invalid") from error

    def redact(self, frame: np.ndarray, screen: ScreenKind, mapping: ViewportMapping) -> tuple[np.ndarray, tuple[Rect, ...]]:
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise PersistenceBlocked("frame must be a uint8 RGB array")
        height, width = frame.shape[:2]
        viewport = mapping.viewport
        if not (0 <= viewport.left < viewport.right <= width and 0 <= viewport.top < viewport.bottom <= height):
            raise PersistenceBlocked("viewport must be wholly inside the frame")
        masks = self.masks_for(screen, mapping)
        if any(
            mask.width <= 0
            or mask.height <= 0
            or not (0 <= mask.left < mask.right <= width and 0 <= mask.top < mask.bottom <= height)
            for mask in masks
        ):
            raise PersistenceBlocked("privacy mask must be wholly inside the frame with nonzero area")
        safe = np.array(frame, copy=True)
        for mask in masks:
            safe[mask.top:mask.bottom, mask.left:mask.right] = 0
        return safe, masks
