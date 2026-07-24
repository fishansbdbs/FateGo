from __future__ import annotations

"""Map navigation and quest selection.

The user's key requirement: a node showing a red/orange "1" badge has an
available quest that must be done -- even on the Story map. So this scans the
map for orange badges (availability) and blue ">>" chevrons (selectable quest
banners), then prioritises banners that sit next to a badge. That makes the
agent treat every Red-1 as a quest to clear instead of walking past it.

Selection taps the quest banner; the resulting quest-detail / support / party
screens are advanced by the main loop (Start Quest is a gold confirm button).
"""

from dataclasses import dataclass

import cv2
import numpy as np

from .input_controller import InputController
from .models import Rect
from .perception import (
    HSV_BLUE_CHEVRON,
    HSV_ORANGE_BADGE,
    Marker,
    _find_blobs,
    _hsv,
)
from .viewport_mapper import ViewportMapping


# Post-selection flow tap targets (normalised). These are the standard FGO NA
# landscape positions and are the first thing to re-calibrate live if a step
# stalls.
START_QUEST_BUTTON = (0.885, 0.875)    # quest-detail "Start" (y verified: 0.92 hit the taskbar)
SUPPORT_FIRST_ROW = (0.42, 0.36)       # first support entry in the list
PARTY_START_BUTTON = (0.888, 0.874)    # party screen "Start Quest"
QUEST_BANNER = (0.70, 0.28)            # highlighted quest banner shown after tapping a map node


@dataclass(slots=True)
class QuestTarget:
    nx: float
    ny: float
    has_badge: bool
    reason: str


def find_markers(view_rgb: np.ndarray) -> tuple[list[Marker], list[Marker]]:
    hsv = _hsv(view_rgb)
    badges = _find_blobs(hsv, *HSV_ORANGE_BADGE, min_area_frac=0.00035)
    chevrons = _find_blobs(hsv, *HSV_BLUE_CHEVRON, min_area_frac=0.00045)
    return badges, chevrons


def pick_quest_target(badges: list[Marker], chevrons: list[Marker]) -> QuestTarget | None:
    """Choose which quest banner to open.

    Priority: a selectable banner (chevron) that has an orange badge near it
    (a Red-1 available quest). Fall back to any selectable banner, then to any
    badge on its own.
    """

    def near_badge(c: Marker) -> bool:
        # Verified live: a node's badge sits ~0.13-0.19 (normalised) from its
        # banner, so the association radius must be generous.
        return any((c.nx - b.nx) ** 2 + (c.ny - b.ny) ** 2 < 0.22 ** 2 for b in badges)

    if chevrons:
        badged = [c for c in chevrons if near_badge(c)]
        pool = badged or chevrons
        # Prefer the upper-most banner so Story progresses in order.
        chosen = min(pool, key=lambda c: c.ny)
        return QuestTarget(chosen.nx, chosen.ny, chosen in badged,
                           "red1_quest" if chosen in badged else "available_quest")
    if badges:
        b = max(badges, key=lambda m: m.area)
        # Badges sit at the top-right of a node; nudge toward the node centre.
        return QuestTarget(max(0.05, b.nx - 0.02), min(0.95, b.ny + 0.05), True, "badge_only")
    return None


class Navigator:
    def __init__(self, tap: InputController) -> None:
        self.tap = tap

    def select_quest(self, frame_rect: Rect, mapping: ViewportMapping, view_rgb: np.ndarray) -> QuestTarget | None:
        badges, chevrons = find_markers(view_rgb)
        target = pick_quest_target(badges, chevrons)
        if target is None:
            return None
        self.tap.tap_normalized(frame_rect, mapping, target.nx, target.ny, settle=0.6)
        return target
