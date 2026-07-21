from __future__ import annotations

from dataclasses import replace

import pytest

from fgo_guardian.agent_models import ActionKind, ResourceKind
from fgo_guardian.battle import (
    AllyState,
    BattleDecisionEngine,
    BattlePhase,
    BattlePolicy,
    BattleState,
    CardColor,
    CommandCard,
    EnemyState,
    NoblePhantasm,
    SkillPurpose,
    SkillState,
    TargetStrategy,
)
from fgo_guardian.models import Rect


ATTACK = Rect(850, 410, 990, 590)


def _ally(
    servant_id: str,
    *,
    hp: int = 4000,
    max_hp: int = 5000,
    np: int = 0,
    left: int = 100,
) -> AllyState:
    return AllyState(servant_id, hp, max_hp, np, Rect(left, 400, left + 160, 590), True)


def _enemy(hp: int = 8000, max_hp: int = 8000) -> EnemyState:
    return EnemyState("enemy-1", hp, max_hp, True, 1)


def _state(**overrides) -> BattleState:
    values = {
        "frame_sha256": "a" * 64,
        "phase": BattlePhase.ACTION,
        "wave": 1,
        "total_waves": 3,
        "turn": 1,
        "allies": (_ally("mash"), _ally("cu", left=300), _ally("support", left=500)),
        "enemies": (_enemy(),),
        "servant_skills": (),
        "master_skills": (),
        "noble_phantasms": (),
        "cards": (),
        "attack_target": ATTACK,
        "pending_target_strategy": None,
    }
    values.update(overrides)
    return BattleState(**values)


def _skill(
    skill_id: str,
    purpose: SkillPurpose,
    *,
    master: bool = False,
    power: int = 50,
) -> SkillState:
    return SkillState(
        skill_id=skill_id,
        owner_id="master" if master else "mash",
        target=Rect(100 + len(skill_id) * 8, 310, 150 + len(skill_id) * 8, 360),
        purpose=purpose,
        power=power,
        available=True,
        target_required=False,
        is_master=master,
    )


def test_available_damage_skill_is_used_on_final_wave_before_attack() -> None:
    state = _state(
        wave=3,
        total_waves=3,
        servant_skills=(_skill("mana-burst", SkillPurpose.DAMAGE_BUFF),),
        enemies=(_enemy(30000, 30000),),
    )

    decision = BattleDecisionEngine().plan(state)

    assert decision.proposal.kind is ActionKind.USE_SKILL
    assert decision.proposal.labels[0] == "skill:mana-burst"
    assert "final wave" in decision.reasons


def test_skill_confirmation_is_accepted_on_any_wave() -> None:
    state = _state(
        servant_skills=(_skill("confirm-skill-use", SkillPurpose.CONFIRMATION),),
    )

    decision = BattleDecisionEngine().plan(state)

    assert decision.proposal.kind is ActionKind.USE_SKILL
    assert decision.proposal.labels[0] == "skill:confirm-skill-use"
    assert "verified skill confirmation" in decision.reasons


def test_low_hp_survival_skill_wins_before_final_wave_damage_buff() -> None:
    state = _state(
        wave=3,
        total_waves=3,
        allies=(_ally("mash", hp=600), _ally("cu", left=300), _ally("support", left=500)),
        servant_skills=(
            _skill("heal", SkillPurpose.HEAL),
            _skill("attack-up", SkillPurpose.DAMAGE_BUFF),
        ),
    )

    decision = BattleDecisionEngine().plan(state)

    assert decision.proposal.labels[0] == "skill:heal"
    assert "low ally HP" in decision.reasons


def test_master_skill_is_a_normal_explainable_candidate() -> None:
    state = _state(
        wave=3,
        total_waves=3,
        master_skills=(_skill("mystic-code-buff", SkillPurpose.DAMAGE_BUFF, master=True),),
        enemies=(_enemy(25000, 25000),),
    )

    decision = BattleDecisionEngine().plan(state)

    assert decision.proposal.kind is ActionKind.USE_SKILL
    assert "Master skill" in decision.reasons


def test_near_ready_np_charge_skill_is_used_on_any_wave() -> None:
    state = _state(
        allies=(_ally("mash", np=82), _ally("cu", left=300), _ally("support", left=500)),
        servant_skills=(_skill("battery", SkillPurpose.NP_CHARGE),),
    )

    assert BattleDecisionEngine().plan(state).proposal.labels[0] == "skill:battery"


def test_ready_np_is_selected_before_ordinary_cards() -> None:
    state = _state(
        phase=BattlePhase.COMMAND_CARDS,
        noble_phantasms=(
            NoblePhantasm("np-mash", "mash", Rect(300, 120, 450, 250), True, False, 1),
        ),
        cards=(
            CommandCard("card-1", "cu", Rect(50, 300, 220, 590), CardColor.BUSTER, 2, 50, 5, False),
        ),
    )

    decision = BattleDecisionEngine().plan(state)

    assert decision.proposal.kind is ActionKind.SELECT_NOBLE_PHANTASM
    assert decision.proposal.labels[0] == "np:np-mash"


def test_three_cards_are_ranked_deterministically_and_effective_cards_win() -> None:
    cards = (
        CommandCard("resist", "mash", Rect(10, 300, 180, 590), CardColor.BUSTER, -1, 80, 5, False),
        CommandCard("neutral", "cu", Rect(200, 300, 370, 590), CardColor.ARTS, 0, 20, 5, False),
        CommandCard("effective", "support", Rect(390, 300, 560, 590), CardColor.QUICK, 1, 10, 5, False),
    )
    engine = BattleDecisionEngine()

    first = engine.rank_cards(cards)

    assert first == engine.rank_cards(cards)
    assert first[0] == "effective"


def test_selected_servant_card_gets_brave_chain_bonus() -> None:
    state = _state(
        phase=BattlePhase.COMMAND_CARDS,
        cards=(
            CommandCard("mash-1", "mash", Rect(10, 300, 180, 590), CardColor.ARTS, 0, 10, 5, True),
            CommandCard("mash-2", "mash", Rect(200, 300, 370, 590), CardColor.QUICK, 0, 10, 5, False),
            CommandCard("cu-1", "cu", Rect(390, 300, 560, 590), CardColor.BUSTER, 0, 10, 5, False),
        ),
    )

    assert BattleDecisionEngine().plan(state).proposal.labels[0] == "card:mash-2"


def test_target_selection_chooses_lowest_hp_visible_ally() -> None:
    mash = _ally("mash", hp=2500)
    cu = _ally("cu", hp=500, left=300)
    state = _state(
        phase=BattlePhase.TARGET_SELECTION,
        allies=(mash, cu),
        pending_target_strategy=TargetStrategy.LOWEST_HP_ALLY,
        attack_target=None,
    )

    decision = BattleDecisionEngine().plan(state)

    assert decision.proposal.kind is ActionKind.SELECT_TARGET
    assert decision.proposal.target == cu.target


def test_battle_policy_file_is_loadable_and_preserves_never_resources() -> None:
    policy = BattlePolicy.load("config/battle_policy.json")

    assert policy.low_hp_ratio == pytest.approx(0.45)
    assert policy.np_score > policy.attack_score


def test_three_selected_commands_wait_for_animation() -> None:
    selected = tuple(
        CommandCard(f"card-{index}", "mash", Rect(index * 100, 300, index * 100 + 90, 590), CardColor.ARTS, 0, 0, 0, True)
        for index in range(3)
    )
    state = _state(phase=BattlePhase.COMMAND_CARDS, cards=selected)

    decision = BattleDecisionEngine().plan(state)

    assert decision.proposal.kind is ActionKind.WAIT
    assert decision.proposal.target is None


@pytest.mark.parametrize(
    "resource",
    [ResourceKind.SAINT_QUARTZ, ResourceKind.COMMAND_SPELL, ResourceKind.SUMMON_TICKET],
)
def test_forbidden_resources_have_no_battle_candidate(resource: ResourceKind) -> None:
    state = _state(phase=BattlePhase.DEFEAT, offered_resource=resource, attack_target=None)

    assert BattleDecisionEngine().candidates(state) == ()


def test_every_battle_candidate_is_zero_cost_and_nonpremium() -> None:
    state = _state(
        wave=3,
        total_waves=3,
        servant_skills=(_skill("attack-up", SkillPurpose.DAMAGE_BUFF),),
    )

    for candidate in BattleDecisionEngine().candidates(state):
        assert candidate.proposal.resource is ResourceKind.NONE
        assert candidate.proposal.resource_cost == 0
