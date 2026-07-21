from __future__ import annotations

from pathlib import Path
import re

import cv2
import numpy as np

from .agent_models import ActionKind, ActionProposal
from .battle import (
    AllyState,
    BattlePhase,
    BattleState,
    CardColor,
    CommandCard,
    EnemyState,
    NoblePhantasm,
    SkillPurpose,
    SkillState,
)
from .models import Rect
from .ocr import OCREngine
from .recognition import Recognition
from .viewport_mapper import ViewportMapping


class BattleVisionProvider:
    """Conservative fixed-layout parser for FGO's landscape battle controls."""

    CARD_REGIONS = (
        (0.02, 0.54, 0.22, 0.94),
        (0.24, 0.54, 0.40, 0.94),
        (0.43, 0.54, 0.59, 0.94),
        (0.63, 0.54, 0.79, 0.94),
        (0.83, 0.54, 0.99, 0.94),
    )
    ALLY_REGIONS = (
        (0.02, 0.72, 0.25, 0.99),
        (0.27, 0.72, 0.50, 0.99),
        (0.52, 0.72, 0.75, 0.99),
    )
    NP_BAR_REGIONS = (
        (0.12, 0.91, 0.25, 0.97),
        (0.36, 0.91, 0.50, 0.97),
        (0.61, 0.91, 0.75, 0.97),
    )
    NP_TARGET_REGIONS = (
        (0.05, 0.15, 0.30, 0.55),
        (0.30, 0.15, 0.55, 0.55),
        (0.55, 0.15, 0.80, 0.55),
    )
    SKILL_GROUP_STARTS = (0.035, 0.283, 0.532)

    def __init__(
        self,
        template_root: str | Path,
        ocr: OCREngine,
        *,
        threshold: float = 0.86,
    ) -> None:
        root = Path(template_root)
        self.attack_template = self._load(root / "battle-attack.png")
        self.back_template = self._load(root / "battle-back.png")
        self.menu_template = self._load(root / "battle-menu.png")
        self.speed_template = self._load(root / "battle-speed.png")
        self.skill_confirm_title_template = self._load(root / "battle-skill-confirm-title.png")
        self.skill_confirm_ok_template = self._load(root / "battle-skill-confirm-ok.png")
        self.skill_confirm_cancel_template = self._load(root / "battle-skill-confirm-cancel.png")
        self.ocr = ocr
        self.threshold = threshold
        self._pending_selection: tuple[ActionKind, Rect] | None = None
        self._pending_skill: Rect | None = None
        self.last_state: BattleState | None = None

    @staticmethod
    def _load(path: Path) -> np.ndarray:
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            raise FileNotFoundError(path)
        return image

    @staticmethod
    def _gray(frame: np.ndarray) -> np.ndarray:
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError("battle vision expects an RGB uint8 frame")
        return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    def _locate(
        self,
        gray: np.ndarray,
        mapping: ViewportMapping,
        template: np.ndarray,
        region: tuple[float, float, float, float],
    ) -> tuple[float, Rect] | None:
        search_rect = mapping.normalized_rect(region)
        search = gray[search_rect.top : search_rect.bottom, search_rect.left : search_rect.right]
        best: tuple[float, Rect] | None = None
        for scale in (0.9, 0.95, 1.0, 1.05, 1.1):
            width = round(template.shape[1] * scale)
            height = round(template.shape[0] * scale)
            if width <= 0 or height <= 0 or width > search.shape[1] or height > search.shape[0]:
                continue
            resized = template if (height, width) == template.shape else cv2.resize(template, (width, height), interpolation=cv2.INTER_AREA)
            scores = cv2.matchTemplate(search, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(scores)
            rect = Rect(
                search_rect.left + location[0],
                search_rect.top + location[1],
                search_rect.left + location[0] + width,
                search_rect.top + location[1] + height,
            )
            if best is None or (score, -rect.top, -rect.left) > (best[0], -best[1].top, -best[1].left):
                best = float(score), rect
        return best if best is not None and best[0] >= self.threshold else None

    def _wave(self, frame: np.ndarray, mapping: ViewportMapping) -> tuple[int, int]:
        region = mapping.normalized_rect((0.65, 0.0, 0.73, 0.065))
        crop = frame[region.top : region.bottom, region.left : region.right]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        white_text = (hsv[:, :, 1] < 100) & (hsv[:, :, 2] > 120)
        mask = np.where(white_text, 0, 255).astype(np.uint8)
        mask = cv2.copyMakeBorder(mask, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
        try:
            text = self.ocr.read(mask, whitelist="0123456789/").text
        except (RuntimeError, ValueError):
            text = ""
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if match:
            wave, total = map(int, match.groups())
            if 1 <= wave <= total <= 9:
                return wave, total
        return 1, 2

    @staticmethod
    def _card_color(frame: np.ndarray, rect: Rect) -> CardColor:
        top = rect.top + round(rect.height * 0.35)
        crop = frame[top : rect.bottom, rect.left : rect.right]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1] > 80
        hue = hsv[:, :, 0]
        counts = {
            CardColor.BUSTER: int(np.count_nonzero(saturation & ((hue < 15) | (hue > 170)))),
            CardColor.ARTS: int(np.count_nonzero(saturation & (hue >= 90) & (hue <= 135))),
            CardColor.QUICK: int(np.count_nonzero(saturation & (hue >= 35) & (hue <= 85))),
        }
        return max(counts, key=lambda color: (counts[color], color.value))

    def _cards(self, frame: np.ndarray, mapping: ViewportMapping) -> tuple[CommandCard, ...]:
        cards: list[CommandCard] = []
        for index, region in enumerate(self.CARD_REGIONS):
            rect = mapping.normalized_rect(region)
            cards.append(
                CommandCard(
                    card_id=f"visible-{index}",
                    owner_id=f"unknown-owner-{index}",
                    target=rect,
                    color=self._card_color(frame, rect),
                    effectiveness=0,
                    critical_chance=0,
                    damage_rank=5 - index,
                    selected=self._card_selected(frame, rect),
                )
            )
        return tuple(cards)

    @staticmethod
    def _card_selected(frame: np.ndarray, rect: Rect) -> bool:
        badge = frame[
            rect.top + round(rect.height * 0.12) : rect.top + round(rect.height * 0.43),
            rect.left + round(rect.width * 0.20) : rect.left + round(rect.width * 0.80),
        ]
        gray = cv2.cvtColor(badge, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(badge, cv2.COLOR_RGB2HSV)
        gold = (
            (hsv[:, :, 0] >= 15)
            & (hsv[:, :, 0] <= 40)
            & (hsv[:, :, 1] > 80)
            & (hsv[:, :, 2] > 80)
        )
        return float(np.mean(gray < 70)) > 0.30 and float(np.mean(gold)) > 0.02

    @staticmethod
    def _np_ready(frame: np.ndarray, rect: Rect) -> bool:
        crop = frame[rect.top : rect.bottom, rect.left : rect.right]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        yellow = (
            (hsv[:, :, 0] >= 15)
            & (hsv[:, :, 0] <= 40)
            & (hsv[:, :, 1] >= 80)
            & (hsv[:, :, 2] >= 100)
        )
        return float(np.mean(yellow)) >= 0.03

    def _np_percent(
        self,
        frame: np.ndarray,
        mapping: ViewportMapping,
        index: int,
    ) -> int | None:
        center = (0.22, 0.47, 0.72)[index]
        region = mapping.normalized_rect((center - 0.04, 0.90, center + 0.04, 0.965))
        crop = frame[region.top : region.bottom, region.left : region.right]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        white_text = (hsv[:, :, 1] < 130) & (hsv[:, :, 2] > 100)
        mask = np.where(white_text, 0, 255).astype(np.uint8)
        mask = cv2.copyMakeBorder(mask, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
        try:
            text = self.ocr.read(mask, whitelist="0123456789%").text.replace(" ", "")
        except (RuntimeError, ValueError):
            return None
        match = re.search(r"(\d{1,3})%", text)
        if match is None:
            return None
        value = int(match.group(1))
        return value if 0 <= value <= 300 else None

    @staticmethod
    def _np_selected(frame: np.ndarray, rect: Rect) -> bool:
        badge = frame[
            rect.top + round(rect.height * 0.15) : rect.top + round(rect.height * 0.65),
            rect.left + round(rect.width * 0.25) : rect.left + round(rect.width * 0.80),
        ]
        gray = cv2.cvtColor(badge, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(badge, cv2.COLOR_RGB2HSV)
        gold = (
            (hsv[:, :, 0] >= 15)
            & (hsv[:, :, 0] <= 40)
            & (hsv[:, :, 1] > 80)
            & (hsv[:, :, 2] > 80)
        )
        return float(np.mean(gray < 70)) > 0.40 and float(np.mean(gold)) > 0.10

    def _noble_phantasms(self, frame: np.ndarray, mapping: ViewportMapping) -> tuple[NoblePhantasm, ...]:
        items: list[NoblePhantasm] = []
        for index, (bar_region, target_region) in enumerate(zip(self.NP_BAR_REGIONS, self.NP_TARGET_REGIONS, strict=True)):
            bar = mapping.normalized_rect(bar_region)
            target = mapping.normalized_rect(target_region)
            percent = self._np_percent(frame, mapping, index)
            ready = percent >= 100 if percent is not None else self._np_ready(frame, bar)
            if ready:
                items.append(
                    NoblePhantasm(
                        np_id=f"visible-np-{index}",
                        owner_id=f"ally-{index}",
                        target=target,
                        ready=True,
                        selected=self._np_selected(frame, target),
                        effectiveness=0,
                    )
                )
        return tuple(items)

    @staticmethod
    def _skill_available(frame: np.ndarray, rect: Rect) -> bool:
        crop = frame[rect.top : rect.bottom, rect.left : rect.right]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        colorful = (hsv[:, :, 1] > 55) & (hsv[:, :, 2] > 55)
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 60, 140) > 0
        band = max(2, round(min(edges.shape) * 0.12))
        border_support = min(
            float(np.max(np.mean(edges[:band], axis=1))),
            float(np.max(np.mean(edges[-band:], axis=1))),
            float(np.max(np.mean(edges[:, :band], axis=0))),
            float(np.max(np.mean(edges[:, -band:], axis=0))),
        )
        return (
            border_support >= 0.60
            and float(np.mean(colorful)) > 0.25
            and float(np.std(gray)) > 35.0
            and float(np.mean(gray)) > 110.0
        )

    def _skills(self, frame: np.ndarray, mapping: ViewportMapping) -> tuple[SkillState, ...]:
        skills: list[SkillState] = []
        for owner_index, start in enumerate(self.SKILL_GROUP_STARTS):
            for skill_index in (0,):
                left = start + skill_index * 0.069
                rect = mapping.normalized_rect((left, 0.755, left + 0.052, 0.855))
                if not self._skill_available(frame, rect):
                    continue
                skills.append(
                    SkillState(
                        skill_id=f"visible-{owner_index}-{skill_index}",
                        owner_id=f"ally-{owner_index}",
                        target=rect,
                        purpose=SkillPurpose.GENERIC_SAFE,
                        power=25 - skill_index,
                        available=True,
                        target_required=False,
                        is_master=False,
                    )
                )
        return tuple(skills)

    def _allies(self, mapping: ViewportMapping) -> tuple[AllyState, ...]:
        return tuple(
            AllyState(f"ally-{index}", 100, 100, 0, mapping.normalized_rect(region), True)
            for index, region in enumerate(self.ALLY_REGIONS)
        )

    def record_action(self, proposal: ActionProposal) -> None:
        if proposal.kind is ActionKind.ATTACK:
            self._pending_selection = None
            self._pending_skill = None
            return
        if proposal.target is None:
            return
        if proposal.kind in {
            ActionKind.SELECT_COMMAND_CARD,
            ActionKind.SELECT_NOBLE_PHANTASM,
        }:
            self._pending_selection = proposal.kind, proposal.target
        elif proposal.kind is ActionKind.USE_SKILL:
            self._pending_skill = proposal.target

    @staticmethod
    def _target_contains(container: Rect, target: Rect) -> bool:
        x = target.left + target.width // 2
        y = target.top + target.height // 2
        return container.left <= x < container.right and container.top <= y < container.bottom

    def _pending_is_confirmed(
        self,
        cards: tuple[CommandCard, ...],
        nobles: tuple[NoblePhantasm, ...],
    ) -> bool:
        pending = self._pending_selection
        if pending is None:
            return True
        kind, target = pending
        if kind is ActionKind.SELECT_COMMAND_CARD:
            return any(card.selected and self._target_contains(card.target, target) for card in cards)
        return any(noble.selected and self._target_contains(noble.target, target) for noble in nobles)

    def build(
        self,
        frame: np.ndarray,
        mapping: ViewportMapping,
        recognition: Recognition,
    ) -> BattleState:
        gray = self._gray(frame)
        wave, total_waves = self._wave(frame, mapping)
        attack = self._locate(gray, mapping, self.attack_template, (0.74, 0.64, 1.0, 1.0))
        back = self._locate(gray, mapping, self.back_template, (0.82, 0.84, 1.0, 1.0))
        menu = self._locate(gray, mapping, self.menu_template, (0.80, 0.16, 1.0, 0.42))
        skill_confirm_title = self._locate(
            gray,
            mapping,
            self.skill_confirm_title_template,
            (0.35, 0.15, 0.70, 0.40),
        )
        skill_confirm_ok = self._locate(
            gray,
            mapping,
            self.skill_confirm_ok_template,
            (0.50, 0.45, 0.85, 0.75),
        )
        skill_confirm_cancel = self._locate(
            gray,
            mapping,
            self.skill_confirm_cancel_template,
            (0.15, 0.45, 0.55, 0.75),
        )
        if skill_confirm_title is not None:
            phase = BattlePhase.ACTION
            self._pending_selection = None
            attack_target = None
            skills = ()
            if skill_confirm_cancel is not None:
                ok_rect = (
                    skill_confirm_ok[1]
                    if skill_confirm_ok is not None
                    else mapping.normalized_rect((0.621, 0.544, 0.720, 0.625))
                )
                ok_mean = float(np.mean(gray[ok_rect.top : ok_rect.bottom, ok_rect.left : ok_rect.right]))
                if ok_mean >= 170.0:
                    skills = (
                        SkillState(
                            skill_id="confirm-skill-use",
                            owner_id="system",
                            target=ok_rect,
                            purpose=SkillPurpose.CONFIRMATION,
                            power=100,
                            available=True,
                            target_required=False,
                            is_master=False,
                        ),
                    )
                elif ok_mean <= 150.0:
                    skills = (
                        SkillState(
                            skill_id="cancel-disabled-skill",
                            owner_id="system",
                            target=skill_confirm_cancel[1],
                            purpose=SkillPurpose.CONFIRMATION,
                            power=100,
                            available=True,
                            target_required=False,
                            is_master=False,
                        ),
                    )
            if not skills:
                phase = BattlePhase.ANIMATION
            cards = ()
            nobles = ()
        elif attack is not None or menu is not None:
            phase = BattlePhase.ACTION
            self._pending_selection = None
            attack_target = (
                attack[1]
                if attack is not None
                else mapping.normalized_rect((0.76, 0.68, 0.98, 0.98))
            )
            skills = self._skills(frame, mapping)
            if self._pending_skill is not None:
                if any(self._target_contains(skill.target, self._pending_skill) for skill in skills):
                    phase = BattlePhase.ANIMATION
                    attack_target = None
                    skills = ()
                else:
                    self._pending_skill = None
            cards = ()
            nobles = ()
        elif back is not None:
            phase = BattlePhase.COMMAND_CARDS
            self._pending_skill = None
            attack_target = None
            skills = ()
            cards = self._cards(frame, mapping)
            nobles = self._noble_phantasms(frame, mapping)
            if self._pending_selection is not None:
                if self._pending_is_confirmed(cards, nobles):
                    self._pending_selection = None
                else:
                    phase = BattlePhase.ANIMATION
                    cards = ()
                    nobles = ()
        else:
            phase = BattlePhase.ANIMATION
            self._pending_selection = None
            attack_target = None
            skills = ()
            cards = ()
            nobles = ()
        state = BattleState(
            frame_sha256=recognition.frame_sha256,
            phase=phase,
            wave=wave,
            total_waves=total_waves,
            turn=1,
            allies=self._allies(mapping),
            enemies=(
                EnemyState(
                    "visible-enemy",
                    10000,
                    10000,
                    True,
                    1,
                    mapping.normalized_rect((0.08, 0.08, 0.52, 0.58)),
                ),
            ),
            servant_skills=skills,
            master_skills=(),
            noble_phantasms=nobles,
            cards=cards,
            attack_target=attack_target,
            pending_target_strategy=None,
        )
        self.last_state = state
        return state
