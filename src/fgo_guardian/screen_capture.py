from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Protocol

import mss
import numpy as np

from .models import Baseline, Rect


class CaptureBlocked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    timestamp: float
    rect: Rect
    image: np.ndarray


class GuardianLike(Protocol):
    def check(self, baseline: Baseline): ...


class DesktopLike(Protocol):
    def capture(self, rect: Rect) -> np.ndarray: ...


class DesktopCapture:
    def capture(self, rect: Rect) -> np.ndarray:
        monitor = {
            "left": rect.left,
            "top": rect.top,
            "width": rect.width,
            "height": rect.height,
        }
        with mss.mss() as grabber:
            bgra = np.asarray(grabber.grab(monitor), dtype=np.uint8)
        return np.ascontiguousarray(bgra[:, :, :3][:, :, ::-1])


class SafeCapture:
    def __init__(self, guardian: GuardianLike, desktop: DesktopLike) -> None:
        self.guardian = guardian
        self.desktop = desktop

    def capture(self, baseline: Baseline) -> CapturedFrame:
        pre = self.guardian.check(baseline)
        if not pre.safe or pre.snapshot is None:
            raise CaptureBlocked(",".join(pre.reasons) or "unsafe_precheck")

        rect = pre.snapshot.outer_rect
        image = self.desktop.capture(rect)

        post = self.guardian.check(baseline)
        if not post.safe:
            image.fill(0)
            raise CaptureBlocked(",".join(post.reasons) or "unsafe_postcheck")
        if post.snapshot is None or post.snapshot.outer_rect != rect:
            image.fill(0)
            raise CaptureBlocked("outer_rect_changed_during_capture")

        expected_shape = (rect.height, rect.width, 3)
        if image.shape != expected_shape:
            image.fill(0)
            raise CaptureBlocked("capture_dimensions_changed")
        return CapturedFrame(monotonic(), rect, image)
