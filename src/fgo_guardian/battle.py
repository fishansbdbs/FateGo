from __future__ import annotations

"""Battle turn execution: skills, Noble Phantasms, and command cards.

Design note on the single-enemy bug: the previous approach assumed a fixed
three-enemy layout and tried to *select an enemy slot* before attacking, which
breaks on single-enemy boss waves. This version never selects an enemy slot.
FGO already has a target focused by default, so we open the card screen and play
cards -- correct for one enemy or many.

Per user preference the play style is aggressive: fire ready servant skills every
turn and use any charged NP, then fill with command cards for the fastest clear.
Skills that are on cooldown are greyed out and simply ignore the tap, so firing
them every turn is safe. Skill targeting uses a sensible default (the main
damage servant); enemy-target skills that need a different target are cancelled
harmlessly rather than mis-fired.

All coordinates are normalised (0..1) fractions of the 16:9 game viewport and
were verified against the live game where possible. Skill/NP/target points are
the first thing to fine-tune in a live pass.
"""

import time
from dataclasses import dataclass, field

from .input_controller import InputController
from .models import Rect
from .viewport_mapper import ViewportMapping


# Verified live:
ATTACK_BUTTON = (0.865, 0.73)
COMMAND_CARDS = [
    (0.125, 0.70),
    (0.312, 0.70),
    (0.502, 0.70),
    (0.690, 0.70),
    (0.875, 0.70),
]
# Servant skills: 3 servants x 3 skills, along the lower-left/centre (verified).
SKILL_BUTTONS = [
    (0.055, 0.79), (0.110, 0.79), (0.165, 0.79),      # servant 1
    (0.295, 0.79), (0.350, 0.79), (0.405, 0.79),      # servant 2
    (0.551, 0.79), (0.611, 0.79), (0.676, 0.79),      # servant 3
]
# This account has skill-use confirmation ON: tapping a skill opens a
# "Confirm Skill Use" dialog first. Its OK button is here (verified live).
# Tapping this spot is harmless when no dialog is present.
CONFIRM_OK = (0.653, 0.549)
# Default target when a skill opens an ally-target selector: the centre servant
# (verified: the three targets sit at ~0.19 / 0.50 / 0.81, y ~ 0.50).
SKILL_TARGET = (0.50, 0.50)
# NP cards appear as a row above the command cards once a gauge is full
# (verified: servant 3's NP card sits at ~0.67, 0.32).
NP_CARDS = [(0.33, 0.31), (0.50, 0.31), (0.67, 0.31)]


@dataclass(slots=True)
class BattleTuning:
    use_skills: bool = True
    use_nps: bool = True
    cards_to_play: int = 3
    skill_settle: float = 0.35
    open_cards_wait: float = 1.4
    between_cards: float = 0.28
    after_turn_wait: float = 1.0


class BattleAgent:
    def __init__(self, tap: InputController, tuning: BattleTuning | None = None) -> None:
        self.tap = tap
        self.tuning = tuning or BattleTuning()

    def _fire_skills(self, frame_rect: Rect, mapping: ViewportMapping) -> None:
        for sx, sy in SKILL_BUTTONS:
            # Ready skills respond; cooldowned ones ignore the tap.
            self.tap.tap_normalized(frame_rect, mapping, sx, sy, settle=0.25)
            # Confirm the "Confirm Skill Use" dialog (harmless if absent).
            self.tap.tap_normalized(frame_rect, mapping, *CONFIRM_OK, settle=0.25)
            # If an ally-target selector opened, pick the centre servant; if not,
            # this taps a harmless spot.
            self.tap.tap_normalized(frame_rect, mapping, *SKILL_TARGET, settle=0.0)
            time.sleep(self.tuning.skill_settle)

    def play_turn(self, frame_rect: Rect, mapping: ViewportMapping) -> bool:
        """Execute one turn: skills -> Attack -> NP(s) -> command cards.

        Returns True if the Attack press was issued.
        """

        if self.tuning.use_skills:
            self._fire_skills(frame_rect, mapping)

        if not self.tap.tap_normalized(frame_rect, mapping, *ATTACK_BUTTON, settle=0.0):
            return False
        time.sleep(self.tuning.open_cards_wait)

        if self.tuning.use_nps:
            # Tap each NP slot. If a gauge is full its card is there and gets
            # picked; otherwise the tap lands on empty battlefield (harmless).
            for nx, ny in NP_CARDS:
                self.tap.tap_normalized(frame_rect, mapping, nx, ny, settle=0.05)

        for i in range(min(self.tuning.cards_to_play, len(COMMAND_CARDS))):
            self.tap.tap_normalized(frame_rect, mapping, *COMMAND_CARDS[i], settle=0.0)
            time.sleep(self.tuning.between_cards)
        time.sleep(self.tuning.after_turn_wait)
        return True
