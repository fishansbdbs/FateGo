from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from fgo_guardian.agent_models import ActionKind, ActionProposal, ResourceKind, ScreenKind
from fgo_guardian.battle import BattlePhase, SkillPurpose
from fgo_guardian.battle_vision import BattleVisionProvider
from fgo_guardian.models import Rect
from fgo_guardian.ocr import NullOCREngine, OCRResult
from fgo_guardian.recognition import Recognition
from fgo_guardian.viewport_mapper import ViewportMapping


RECORDED_ROOT = Path(
    r"C:\Users\User\Documents\New project\fgo-supervised-assistant\data\recordings\tutorial-fuyuki-formation-run-9\frames"
)
MAPPING = ViewportMapping(Rect(55, 40, 1819, 1032), 40, 1819)


def _frame(observation_id: str):
    bgr = cv2.imread(str(RECORDED_ROOT / f"{observation_id}.png"))
    assert bgr is not None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _recognition(digest: str = "a" * 64) -> Recognition:
    return Recognition(ScreenKind.BATTLE, 0.99, {}, {}, ("test",), digest)


@pytest.mark.skipif(not RECORDED_ROOT.exists(), reason="local redacted Fuyuki recording is unavailable")
def test_recorded_attack_and_command_card_phases_are_detected() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())

    attack = provider.build(
        _frame("obs-a55a3ba1e0d044b5a57f287e3e185fb9"), MAPPING, _recognition("a" * 64)
    )
    cards = provider.build(
        _frame("obs-872c3b0e81594fb7b1be64ab9ab3046e"), MAPPING, _recognition("b" * 64)
    )

    assert attack.phase is BattlePhase.ACTION
    assert attack.attack_target is not None
    assert {skill.skill_id for skill in attack.servant_skills} == {
        "visible-0-0",
        "visible-1-0",
        "visible-2-0",
    }
    assert cards.phase is BattlePhase.COMMAND_CARDS
    assert len(cards.cards) == 5
    assert all(MAPPING.viewport.left <= card.target.left < card.target.right <= MAPPING.viewport.right for card in cards.cards)


@pytest.mark.skipif(not RECORDED_ROOT.exists(), reason="local redacted Fuyuki recording is unavailable")
def test_np_readiness_and_selection_are_derived_from_pixels() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())
    before_selection = provider.build(
        _frame("obs-6fa0fe5e6223496caf0556af438d844e"), MAPPING, _recognition("c" * 64)
    )
    after_selection = provider.build(
        _frame("obs-0d4490a3f21240f8a5dd53c16b6157cb"), MAPPING, _recognition("d" * 64)
    )

    assert before_selection.phase is BattlePhase.COMMAND_CARDS
    assert any(noble.ready and not noble.selected for noble in before_selection.noble_phantasms)
    assert any(noble.ready and noble.selected for noble in after_selection.noble_phantasms)


@pytest.mark.skipif(not RECORDED_ROOT.exists(), reason="local redacted Fuyuki recording is unavailable")
def test_selected_command_cards_are_derived_from_pixels() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())
    state = provider.build(
        _frame("obs-872c3b0e81594fb7b1be64ab9ab3046e"), MAPPING, _recognition("e" * 64)
    )

    assert state.phase is BattlePhase.COMMAND_CARDS
    assert any(card.selected for card in state.cards)


def test_half_np_gauge_is_not_ready() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())
    hsv = np.zeros((100, 100, 3), dtype=np.uint8)
    hsv.reshape(-1, 3)[:130, :] = (25, 200, 200)
    half_gauge = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)

    assert provider._np_ready(half_gauge, Rect(0, 0, 100, 100)) is False

    hsv.reshape(-1, 3)[:300, :] = (25, 200, 200)
    full_gauge = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    assert provider._np_ready(full_gauge, Rect(0, 0, 100, 100)) is True


@pytest.mark.skipif(not RECORDED_ROOT.exists(), reason="local redacted Fuyuki recording is unavailable")
def test_card_action_waits_until_the_selected_badge_is_visible() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())
    initial = provider.build(
        _frame("obs-3947607626ac44b289f50f523ae58b38"), MAPPING, _recognition("f" * 64)
    )
    target = initial.cards[0].target
    provider.record_action(
        ActionProposal("f" * 64, ActionKind.SELECT_COMMAND_CARD, target, (), ResourceKind.NONE, 0, False)
    )

    waiting = provider.build(
        _frame("obs-3947607626ac44b289f50f523ae58b38"), MAPPING, _recognition("1" * 64)
    )
    confirmed = provider.build(
        _frame("obs-9c45fd3c7c7e4b0080f84bceda45ef21"), MAPPING, _recognition("2" * 64)
    )

    assert waiting.phase is BattlePhase.ANIMATION
    assert confirmed.phase is BattlePhase.COMMAND_CARDS
    assert confirmed.cards[0].selected is True


@pytest.mark.skipif(not RECORDED_ROOT.exists(), reason="local redacted Fuyuki recording is unavailable")
def test_skill_action_waits_until_the_icon_is_no_longer_available() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())
    frame = _frame("obs-a55a3ba1e0d044b5a57f287e3e185fb9")
    initial = provider.build(frame, MAPPING, _recognition("4" * 64))
    skill = initial.servant_skills[0]
    provider.record_action(
        ActionProposal("4" * 64, ActionKind.USE_SKILL, skill.target, (), ResourceKind.NONE, 0, False)
    )

    waiting = provider.build(frame, MAPPING, _recognition("5" * 64))

    assert waiting.phase is BattlePhase.ANIMATION
    assert waiting.attack_target is None


def test_battle_speed_anchor_alone_does_not_expose_command_cards() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())
    frame = np.zeros((1032, 1920, 3), dtype=np.uint8)
    template = cv2.cvtColor(provider.speed_template, cv2.COLOR_GRAY2RGB)
    top, left = 60, 1500
    frame[top : top + template.shape[0], left : left + template.shape[1]] = template

    state = provider.build(frame, MAPPING, _recognition("3" * 64))

    assert state.phase is BattlePhase.ANIMATION
    assert state.cards == ()


class _PercentageOCR:
    def __init__(self, values: tuple[str, ...]) -> None:
        self.values = iter(values)

    def read(self, image, *, whitelist=None) -> OCRResult:
        del image, whitelist
        return OCRResult(next(self.values), 0.95)


def test_np_percentage_must_reach_one_hundred() -> None:
    frame = np.zeros((1032, 1920, 3), dtype=np.uint8)
    not_ready = BattleVisionProvider(Path("templates"), _PercentageOCR(("13%", "11%", "83%")))
    ready = BattleVisionProvider(Path("templates"), _PercentageOCR(("0%", "9%", "103%")))

    assert not_ready._noble_phantasms(frame, MAPPING) == ()
    nobles = ready._noble_phantasms(frame, MAPPING)
    assert [noble.np_id for noble in nobles] == ["visible-np-2"]


def test_skill_confirmation_modal_exposes_only_its_ok_button() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())
    frame = np.zeros((1032, 1920, 3), dtype=np.uint8)
    title = cv2.cvtColor(provider.skill_confirm_title_template, cv2.COLOR_GRAY2RGB)
    ok = cv2.cvtColor(provider.skill_confirm_ok_template, cv2.COLOR_GRAY2RGB)
    cancel = cv2.cvtColor(provider.skill_confirm_cancel_template, cv2.COLOR_GRAY2RGB)
    frame[255 : 255 + title.shape[0], 815 : 815 + title.shape[1]] = title
    frame[580 : 580 + ok.shape[0], 1150 : 1150 + ok.shape[1]] = ok
    frame[580 : 580 + cancel.shape[0], 520 : 520 + cancel.shape[1]] = cancel

    state = provider.build(frame, MAPPING, _recognition("6" * 64))

    assert state.phase is BattlePhase.ACTION
    assert state.attack_target is None
    assert [skill.skill_id for skill in state.servant_skills] == ["confirm-skill-use"]
    assert state.servant_skills[0].purpose is SkillPurpose.CONFIRMATION


def test_disabled_skill_confirmation_exposes_only_cancel() -> None:
    provider = BattleVisionProvider(Path("templates"), NullOCREngine())
    frame = np.zeros((1032, 1920, 3), dtype=np.uint8)
    title = cv2.cvtColor(provider.skill_confirm_title_template, cv2.COLOR_GRAY2RGB)
    disabled_ok = cv2.cvtColor(
        (provider.skill_confirm_ok_template.astype(np.float32) * 0.5).astype(np.uint8),
        cv2.COLOR_GRAY2RGB,
    )
    cancel = cv2.cvtColor(provider.skill_confirm_cancel_template, cv2.COLOR_GRAY2RGB)
    frame[255 : 255 + title.shape[0], 815 : 815 + title.shape[1]] = title
    frame[580 : 580 + disabled_ok.shape[0], 1150 : 1150 + disabled_ok.shape[1]] = disabled_ok
    frame[580 : 580 + cancel.shape[0], 520 : 520 + cancel.shape[1]] = cancel

    state = provider.build(frame, MAPPING, _recognition("7" * 64))

    assert state.phase is BattlePhase.ACTION
    assert state.attack_target is None
    assert [skill.skill_id for skill in state.servant_skills] == ["cancel-disabled-skill"]
    assert state.servant_skills[0].purpose is SkillPurpose.CONFIRMATION
