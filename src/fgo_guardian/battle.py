from __future__ import annotations

"""Battle turn execution.

Design note on the single-enemy bug: the previous approach assumed a fixed
three-enemy layout and tried to *select an enemy slot* before attacking, which
breaks on single-enemy boss waves where only one target exists. This version
never selects an enemy slot. FGO already has a target focused by default, so we
simply open the card screen and play three cards -- correct for one enemy or
many. An optional focus tap on the left-most enemy is available but off by
default because it is unnecessary and is what caused the boss-wave failures.

All coordinates are normalised (0..1) fractions of the 16:9 game viewport and
are grouped here so they are easy to re-calibrate.
"""

import time
from dataclasses import dataclass

from .input_controller import InputController
from .models import Rect
from .viewport_mapper import ViewportMapping


# Normalised layout for FGO NA landscape.
ATTACK_BUTTON = (0.905, 0.855)
# Five command cards spread along the lower third once the card screen opens.
COMMAND_CARDS = [
    (0.15, 0.70),
    (0.325, 0.70),
    (0.50, 0.70),
    (0.675, 0.70),
    (0.85, 0.70),
]
# "Attack" again / next-wave has no separate button; the loop re-detects.


@dataclass(slots=True)
class BattleTuning:
    cards_to_play: int = 3
    open_cards_wait: float = 1.4      # after pressing Attack, wait for cards to slide in
    between_cards: float = 0.28
    after_turn_wait: float = 1.0      # let the attack animation start before re-observing


class BattleAgent:
    def __init__(self, tap: InputController, tuning: BattleTuning | None = None) -> None:
        self.tap = tap
        self.tuning = tuning or BattleTuning()

    def play_turn(self, frame_rect: Rect, mapping: ViewportMapping) -> bool:
        """Execute one attack turn: open cards and play the first N cards.

        Returns True if the Attack press was issued. Skills and NPs are left for
        a later tuning pass; plain card attacks clear early Story/Free content
        reliably, which is the stated priority.
        """

        if not self.tap.tap_normalized(frame_rect, mapping, *ATTACK_BUTTON, settle=0.0):
            return False
        time.sleep(self.tuning.open_cards_wait)
        for i in range(min(self.tuning.cards_to_play, len(COMMAND_CARDS))):
            self.tap.tap_normalized(frame_rect, mapping, *COMMAND_CARDS[i], settle=0.0)
            time.sleep(self.tuning.between_cards)
        time.sleep(self.tuning.after_turn_wait)
        return True
