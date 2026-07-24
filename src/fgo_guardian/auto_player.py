from __future__ import annotations

"""Autonomous play loop.

This replaces the old ``recon_sentinel``, whose only behaviour was to *pause*
whenever the viewport signature changed -- i.e. on essentially every screen,
which is exactly the "pauses way too much" complaint. Here we observe, decide,
and act on every frame in a tight loop.

Decision priority each cycle:

1. If the window is unsafe (moved/minimised/covered/lost focus) -> pause, keep
   re-checking, resume automatically when safe again. We do NOT pause merely
   because the screen changed.
2. Loading (near-black) -> brief wait.
3. Battle command screen -> play a card turn (works for 1 or many enemies).
4. Map -> pick a quest, prioritising Red-1 (badged) nodes.
5. Gold confirm dialog -> press it (Start / Yes / Close / Attention / apple).
6. Everything else (story, dialogue, level-up, mission-clear, drops, friend
   request, achievements) -> skip and tap through instead of stalling.
"""

import time
from dataclasses import dataclass
from threading import Event
from typing import Callable

import numpy as np

from .battle import BattleAgent
from .input_controller import InputController, SafetyGate
from .navigator import Navigator, PARTY_START_BUTTON, QUEST_BANNER, SUPPORT_FIRST_ROW
from .perception import Perception, Screen, frame_signature, frames_differ
from .screen_capture import CaptureBlocked, SafeCapture
from .viewport_mapper import ViewportMapper


# Generic tap targets used when tapping through non-battle screens.
SKIP_BUTTON = (0.932, 0.055)          # story/cutscene Skip pill, top-right
ADVANCE_BOTTOM_RIGHT = (0.90, 0.875)  # Next / Close on result-style screens (y verified)
ADVANCE_CENTER = (0.50, 0.62)         # "tap to continue" dialogue advance


@dataclass(slots=True)
class LoopTuning:
    decision_interval: float = 0.18      # base loop period -> fast decisions
    loading_wait: float = 0.45
    story_settle: float = 0.35
    unsafe_grace: int = 3                # unsafe checks before we call it a pause
    max_map_misses: int = 6              # empty-map cycles before pausing
    stuck_after: int = 40                # unchanged frames before nudging harder


class AutoPlayer:
    def __init__(
        self,
        guardian,
        capture: SafeCapture,
        mapper: ViewportMapper,
        baseline,
        tuning: LoopTuning | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.guardian = guardian
        self.capture = capture
        self.mapper = mapper
        self.baseline = baseline
        self.tuning = tuning or LoopTuning()
        self.log = log or (lambda msg: None)
        self.gate = SafetyGate(lambda: self.guardian.check(self.baseline).safe)
        self.tap = InputController(self.gate)
        self.battle = BattleAgent(self.tap)
        self.navigator = Navigator(self.tap)
        self.perception = Perception()
        self._last_sig: np.ndarray | None = None
        self._unchanged = 0
        self._map_misses = 0
        self._post_start_flow = 0     # counts advances since a quest was started

    # -- helpers ------------------------------------------------------------

    def _changed(self, sig: np.ndarray) -> bool:
        changed = self._last_sig is None or frames_differ(self._last_sig, sig)
        self._last_sig = sig
        if changed:
            self._unchanged = 0
        else:
            self._unchanged += 1
        return changed

    # -- main loop ----------------------------------------------------------

    def run(self, stop: Event, paused: Event | None = None) -> None:
        paused = paused or Event()
        unsafe_streak = 0
        was_paused = False
        while not stop.is_set():
            if paused.is_set():
                time.sleep(0.2)
                continue

            report = self.guardian.check(self.baseline)
            if not report.safe:
                unsafe_streak += 1
                if unsafe_streak >= self.tuning.unsafe_grace and not was_paused:
                    self.log(f"paused: window unsafe ({','.join(report.reasons)})")
                    was_paused = True
                time.sleep(0.3)
                continue
            if was_paused:
                self.log("resumed: window safe again")
                was_paused = False
            unsafe_streak = 0

            try:
                frame = self.capture.capture(self.baseline)
            except CaptureBlocked:
                time.sleep(0.2)
                continue

            try:
                mapping = self.mapper.locate(frame.image)
            except Exception:
                # Cannot map the viewport (black/loading/animation) -> wait.
                time.sleep(self.tuning.loading_wait)
                continue

            reading = self.perception.read(frame.image, mapping)
            sig = frame_signature(frame.image, mapping)
            self._changed(sig)

            self._act(frame.rect, mapping, frame.image, reading)
            time.sleep(self.tuning.decision_interval)

    def _act(self, frame_rect, mapping, image_rgb, reading) -> None:
        screen = reading.screen

        if screen is Screen.LOADING:
            time.sleep(self.tuning.loading_wait)
            return

        if screen is Screen.BATTLE_COMMAND:
            self._post_start_flow = 0
            self.log("battle: playing a card turn")
            self.battle.play_turn(frame_rect, mapping)
            return

        if screen is Screen.MAP:
            if self._post_start_flow:
                # A node was just selected and its quest banner is up. Tap the
                # banner to go to support selection instead of re-selecting a
                # different node (verified flow: node -> banner -> support).
                self.tap.tap_normalized(frame_rect, mapping, *QUEST_BANNER, settle=0.5)
                self._post_start_flow += 1
                if self._post_start_flow > 4:
                    self._post_start_flow = 0
                return
            target = self.navigator.select_quest(frame_rect, mapping, mapping.crop(image_rgb))
            if target is None:
                self._map_misses += 1
                if self._map_misses >= self.tuning.max_map_misses:
                    self.log("paused: on a map but found no available quest markers")
                    time.sleep(0.6)
                return
            self._map_misses = 0
            self._post_start_flow = 1
            self.log(f"map: selecting quest ({target.reason})")
            return

        if screen is Screen.CONFIRM_DIALOG and reading.confirm is not None:
            self.log("confirm: pressing dialog button")
            self.tap.tap_normalized(frame_rect, mapping, *reading.confirm, settle=0.4)
            if self._post_start_flow:
                self._post_start_flow += 1
            return

        # Catch-all: story / dialogue / level-up / mission / drops / friend req.
        self._advance(frame_rect, mapping)

    def _advance(self, frame_rect, mapping) -> None:
        """Skip and tap through anything that is not a decision screen."""
        # Try to skip cutscenes first (harmless if the button is absent).
        self.tap.tap_normalized(frame_rect, mapping, *SKIP_BUTTON, settle=0.15)
        # Then advance result/level-up/mission style screens.
        self.tap.tap_normalized(frame_rect, mapping, *ADVANCE_BOTTOM_RIGHT, settle=0.1)

        # If we started a quest recently, the support list appears; nudge the
        # first support row so the flow does not stall there.
        if self._post_start_flow:
            self.tap.tap_normalized(frame_rect, mapping, *SUPPORT_FIRST_ROW, settle=0.1)
            self.tap.tap_normalized(frame_rect, mapping, *PARTY_START_BUTTON, settle=0.1)

        if self._unchanged >= self.tuning.stuck_after:
            # Genuinely stuck: try a neutral dialogue advance tap.
            self.tap.tap_normalized(frame_rect, mapping, *ADVANCE_CENTER, settle=0.1)
        time.sleep(self.tuning.story_settle)
