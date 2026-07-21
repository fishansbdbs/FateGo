from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Sequence

from .agent_models import ActionKind, ActionProposal, ResourceKind
from .models import Rect


class BattlePhase(str, Enum):
    ACTION = "ACTION"
    TARGET_SELECTION = "TARGET_SELECTION"
    COMMAND_CARDS = "COMMAND_CARDS"
    ANIMATION = "ANIMATION"
    DEFEAT = "DEFEAT"


class CardColor(str, Enum):
    BUSTER = "BUSTER"
    ARTS = "ARTS"
    QUICK = "QUICK"


class SkillPurpose(str, Enum):
    SURVIVAL = "SURVIVAL"
    HEAL = "HEAL"
    NP_CHARGE = "NP_CHARGE"
    DAMAGE_BUFF = "DAMAGE_BUFF"
    DEFENSE_DOWN = "DEFENSE_DOWN"
    CONTROL = "CONTROL"
    GENERIC_SAFE = "GENERIC_SAFE"


class TargetStrategy(str, Enum):
    LOWEST_HP_ALLY = "LOWEST_HP_ALLY"
    HIGHEST_NP_ALLY = "HIGHEST_NP_ALLY"
    FIRST_ENEMY = "FIRST_ENEMY"


class BattlePlanningError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AllyState:
    servant_id: str
    hp: int
    max_hp: int
    np_percent: int
    target: Rect
    alive: bool

    @property
    def hp_ratio(self) -> float:
        return self.hp / self.max_hp if self.max_hp > 0 else 0.0


@dataclass(frozen=True, slots=True)
class EnemyState:
    enemy_id: str
    hp: int
    max_hp: int
    targetable: bool
    danger: int
    target: Rect | None = None

    @property
    def hp_ratio(self) -> float:
        return self.hp / self.max_hp if self.max_hp > 0 else 0.0


@dataclass(frozen=True, slots=True)
class SkillState:
    skill_id: str
    owner_id: str
    target: Rect
    purpose: SkillPurpose
    power: int
    available: bool
    target_required: bool
    is_master: bool


@dataclass(frozen=True, slots=True)
class NoblePhantasm:
    np_id: str
    owner_id: str
    target: Rect
    ready: bool
    selected: bool
    effectiveness: int


@dataclass(frozen=True, slots=True)
class CommandCard:
    card_id: str
    owner_id: str
    target: Rect
    color: CardColor
    effectiveness: int
    critical_chance: int
    damage_rank: int
    selected: bool


@dataclass(frozen=True, slots=True)
class BattleState:
    frame_sha256: str
    phase: BattlePhase
    wave: int
    total_waves: int
    turn: int
    allies: tuple[AllyState, ...]
    enemies: tuple[EnemyState, ...]
    servant_skills: tuple[SkillState, ...]
    master_skills: tuple[SkillState, ...]
    noble_phantasms: tuple[NoblePhantasm, ...]
    cards: tuple[CommandCard, ...]
    attack_target: Rect | None
    pending_target_strategy: TargetStrategy | None
    offered_resource: ResourceKind = ResourceKind.NONE

    def __post_init__(self) -> None:
        if self.wave < 1 or self.total_waves < self.wave:
            raise ValueError("battle wave must be within the total wave count")
        if self.turn < 1:
            raise ValueError("battle turn must be positive")


@dataclass(frozen=True, slots=True)
class BattlePolicy:
    low_hp_ratio: float = 0.45
    near_ready_np: int = 70
    attack_score: int = 100
    survival_score: int = 1600
    heal_score: int = 1500
    np_charge_score: int = 1400
    final_wave_damage_score: int = 1000
    high_hp_enemy_bonus: int = 200
    master_skill_bonus: int = 20
    np_score: int = 3000
    effectiveness_score: int = 500
    brave_chain_bonus: int = 300

    @classmethod
    def load(cls, path: str | Path) -> "BattlePolicy":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("battle policy must use version 1")
        weights = data.get("weights")
        if not isinstance(weights, dict):
            raise ValueError("battle policy requires weights")
        fields = {
            "low_hp_ratio": float(data.get("low_hp_ratio", 0.45)),
            "near_ready_np": int(data.get("near_ready_np", 70)),
            **{name: int(value) for name, value in weights.items()},
        }
        allowed = set(cls.__dataclass_fields__)
        if not set(fields) <= allowed:
            raise ValueError("battle policy contains an unknown weight")
        policy = cls(**fields)
        if not 0.0 < policy.low_hp_ratio < 1.0 or not 0 <= policy.near_ready_np <= 100:
            raise ValueError("battle policy thresholds are invalid")
        return policy


@dataclass(frozen=True, slots=True)
class ScoredAction:
    proposal: ActionProposal
    score: int
    reasons: tuple[str, ...]

    def stable_key(self) -> tuple[object, ...]:
        target = self.proposal.target.as_tuple() if self.proposal.target is not None else ()
        return self.proposal.kind.value, self.proposal.labels, target


class BattleDecisionEngine:
    def __init__(self, policy: BattlePolicy | None = None) -> None:
        self.policy = policy if policy is not None else BattlePolicy()

    @staticmethod
    def _proposal(
        state: BattleState,
        kind: ActionKind,
        target: Rect | None,
        labels: tuple[str, ...],
    ) -> ActionProposal:
        return ActionProposal(
            observation_id=state.frame_sha256,
            kind=kind,
            target=target,
            labels=labels,
            resource=ResourceKind.NONE,
            resource_cost=0,
            mandatory=False,
        )

    @staticmethod
    def choose(candidates: Sequence[ScoredAction]) -> ScoredAction:
        if not candidates:
            raise BattlePlanningError("battle state has no legal candidate")
        return max(candidates, key=lambda item: (item.score, item.stable_key()))

    def _skill_candidate(self, state: BattleState, skill: SkillState) -> ScoredAction | None:
        if not skill.available:
            return None
        living_allies = tuple(ally for ally in state.allies if ally.alive)
        living_enemies = tuple(enemy for enemy in state.enemies if enemy.targetable)
        lowest_hp = min((ally.hp_ratio for ally in living_allies), default=1.0)
        final_wave = state.wave == state.total_waves
        high_hp_enemy = any(enemy.hp >= 15000 or enemy.max_hp >= 20000 for enemy in living_enemies)
        reasons: list[str] = []
        score = 0
        if skill.purpose is SkillPurpose.SURVIVAL and lowest_hp <= self.policy.low_hp_ratio:
            score = self.policy.survival_score + skill.power
            reasons.append("low ally HP")
        elif skill.purpose is SkillPurpose.HEAL and lowest_hp <= self.policy.low_hp_ratio:
            score = self.policy.heal_score + skill.power
            reasons.append("low ally HP")
        elif skill.purpose is SkillPurpose.NP_CHARGE and any(
            self.policy.near_ready_np <= ally.np_percent < 100 for ally in living_allies
        ):
            score = self.policy.np_charge_score + skill.power
            reasons.append("NP near ready")
        elif skill.purpose in {SkillPurpose.DAMAGE_BUFF, SkillPurpose.DEFENSE_DOWN} and final_wave:
            score = self.policy.final_wave_damage_score + skill.power
            reasons.append("final wave")
            if high_hp_enemy:
                score += self.policy.high_hp_enemy_bonus
                reasons.append("high HP enemy")
        elif skill.purpose is SkillPurpose.CONTROL and any(enemy.danger >= 2 for enemy in living_enemies):
            score = self.policy.final_wave_damage_score + skill.power
            reasons.append("dangerous enemy")
        elif skill.purpose is SkillPurpose.GENERIC_SAFE and final_wave:
            score = self.policy.attack_score + 1 + skill.power
            reasons.append("safe final-wave utility")
        if score <= self.policy.attack_score:
            return None
        if skill.is_master:
            score += self.policy.master_skill_bonus
            reasons.append("Master skill")
        if skill.target_required:
            reasons.append("fresh target selection required")
        return ScoredAction(
            self._proposal(
                state,
                ActionKind.USE_SKILL,
                skill.target,
                (f"skill:{skill.skill_id}", f"owner:{skill.owner_id}"),
            ),
            score,
            tuple(reasons),
        )

    def _action_candidates(self, state: BattleState) -> tuple[ScoredAction, ...]:
        items = tuple(
            candidate
            for skill in state.servant_skills + state.master_skills
            if (candidate := self._skill_candidate(state, skill)) is not None
        )
        attack = ()
        if state.attack_target is not None:
            attack = (
                ScoredAction(
                    self._proposal(state, ActionKind.ATTACK, state.attack_target, ("Attack",)),
                    self.policy.attack_score,
                    ("advance to command cards",),
                ),
            )
        return items + attack

    @staticmethod
    def _color_score(color: CardColor) -> int:
        return {
            CardColor.BUSTER: 150,
            CardColor.ARTS: 100,
            CardColor.QUICK: 50,
        }[color]

    def _card_score(self, card: CommandCard, selected_owners: set[str]) -> tuple[int, tuple[str, ...]]:
        score = card.effectiveness * self.policy.effectiveness_score
        score += self._color_score(card.color)
        score += card.critical_chance
        score += card.damage_rank * 5
        reasons = [f"class effectiveness:{card.effectiveness}", f"color:{card.color.value}"]
        if card.owner_id in selected_owners:
            score += self.policy.brave_chain_bonus
            reasons.append("brave chain")
        return score, tuple(reasons)

    def rank_cards(self, cards: Sequence[CommandCard]) -> tuple[str, ...]:
        selected_owners = {card.owner_id for card in cards if card.selected}
        ranked = sorted(
            (card for card in cards if not card.selected),
            key=lambda card: (self._card_score(card, selected_owners)[0], card.card_id),
            reverse=True,
        )
        return tuple(card.card_id for card in ranked)

    def _command_candidates(self, state: BattleState) -> tuple[ScoredAction, ...]:
        selected_count = sum(card.selected for card in state.cards) + sum(
            noble.selected for noble in state.noble_phantasms
        )
        if selected_count >= 3:
            return (
                ScoredAction(
                    self._proposal(state, ActionKind.WAIT, None, ("command chain complete",)),
                    0,
                    ("three commands selected",),
                ),
            )
        selected_owners = {card.owner_id for card in state.cards if card.selected}
        selected_owners.update(noble.owner_id for noble in state.noble_phantasms if noble.selected)
        candidates: list[ScoredAction] = []
        for noble in state.noble_phantasms:
            if not noble.ready or noble.selected:
                continue
            candidates.append(
                ScoredAction(
                    self._proposal(
                        state,
                        ActionKind.SELECT_NOBLE_PHANTASM,
                        noble.target,
                        (f"np:{noble.np_id}", f"owner:{noble.owner_id}"),
                    ),
                    self.policy.np_score + noble.effectiveness * self.policy.effectiveness_score,
                    ("NP ready", f"class effectiveness:{noble.effectiveness}"),
                )
            )
        for card in state.cards:
            if card.selected:
                continue
            score, reasons = self._card_score(card, selected_owners)
            candidates.append(
                ScoredAction(
                    self._proposal(
                        state,
                        ActionKind.SELECT_COMMAND_CARD,
                        card.target,
                        (f"card:{card.card_id}", f"owner:{card.owner_id}"),
                    ),
                    score,
                    reasons,
                )
            )
        return tuple(candidates)

    def _target_candidates(self, state: BattleState) -> tuple[ScoredAction, ...]:
        strategy = state.pending_target_strategy
        if strategy is TargetStrategy.LOWEST_HP_ALLY:
            choices = tuple(ally for ally in state.allies if ally.alive)
            if not choices:
                return ()
            chosen = min(choices, key=lambda ally: (ally.hp_ratio, ally.servant_id))
            label = chosen.servant_id
            target = chosen.target
        elif strategy is TargetStrategy.HIGHEST_NP_ALLY:
            choices = tuple(ally for ally in state.allies if ally.alive)
            if not choices:
                return ()
            chosen = max(choices, key=lambda ally: (ally.np_percent, ally.servant_id))
            label = chosen.servant_id
            target = chosen.target
        elif strategy is TargetStrategy.FIRST_ENEMY:
            choices = tuple(enemy for enemy in state.enemies if enemy.targetable and enemy.target is not None)
            if not choices:
                return ()
            chosen = sorted(choices, key=lambda enemy: (-enemy.danger, -enemy.hp, enemy.enemy_id))[0]
            label = chosen.enemy_id
            assert chosen.target is not None
            target = chosen.target
        else:
            return ()
        return (
            ScoredAction(
                self._proposal(
                    state,
                    ActionKind.SELECT_TARGET,
                    target,
                    (f"target:{label}", f"strategy:{strategy.value}"),
                ),
                1000,
                (f"pending target strategy:{strategy.value}",),
            ),
        )

    def candidates(self, state: BattleState) -> tuple[ScoredAction, ...]:
        if state.phase is BattlePhase.DEFEAT:
            return ()
        if state.phase is BattlePhase.ACTION:
            return self._action_candidates(state)
        if state.phase is BattlePhase.COMMAND_CARDS:
            return self._command_candidates(state)
        if state.phase is BattlePhase.TARGET_SELECTION:
            return self._target_candidates(state)
        if state.phase is BattlePhase.ANIMATION:
            return (
                ScoredAction(
                    self._proposal(state, ActionKind.WAIT, None, ("battle animation",)),
                    0,
                    ("wait for a fresh actionable frame",),
                ),
            )
        return ()

    def plan(self, state: BattleState) -> ScoredAction:
        return self.choose(self.candidates(state))
