from __future__ import annotations

import math
import re

from .agent_models import ActionKind, ActionProposal, Observation, PolicyDecision, ResourceKind, ScreenKind
from .models import Rect


FORBIDDEN_ACTIONS = {
    ActionKind.OPTIONAL_SUMMON,
    ActionKind.PURCHASE,
    ActionKind.ACCOUNT_ACTION,
    ActionKind.DELETE_DATA,
    ActionKind.CLEAR_CACHE,
}
APPLE_RESOURCES = {
    ResourceKind.BLUE_APPLE,
    ResourceKind.BRONZE_APPLE,
    ResourceKind.SILVER_APPLE,
    ResourceKind.GOLDEN_APPLE,
}
ALLOWED_BY_SCREEN = {
    ScreenKind.TITLE: {ActionKind.ADVANCE_TUTORIAL, ActionKind.WAIT},
    ScreenKind.TUTORIAL_MAP: {ActionKind.SELECT_QUEST, ActionKind.WAIT},
    ScreenKind.TUTORIAL_PROMPT: {ActionKind.ADVANCE_TUTORIAL, ActionKind.WAIT},
    ScreenKind.STORY: {ActionKind.SKIP_STORY},
    ScreenKind.SKIP_CONFIRM: {ActionKind.CONFIRM_SKIP, ActionKind.WAIT},
    ScreenKind.DIALOGUE_CHOICE: {ActionKind.SELECT_DIALOGUE, ActionKind.WAIT},
    ScreenKind.SUPPORT_SELECT: {ActionKind.SELECT_SUPPORT, ActionKind.WAIT},
    ScreenKind.PARTY_CONFIRM: {ActionKind.CONFIRM_PARTY, ActionKind.START_QUEST, ActionKind.WAIT},
    ScreenKind.BATTLE: {
        ActionKind.USE_SKILL,
        ActionKind.SELECT_TARGET,
        ActionKind.ATTACK,
        ActionKind.SELECT_COMMAND_CARD,
        ActionKind.SELECT_NOBLE_PHANTASM,
        ActionKind.WAIT,
    },
    ScreenKind.QUEST_RESULT: {ActionKind.COLLECT_RESULT, ActionKind.WAIT},
    ScreenKind.AP_REFILL: {ActionKind.RESTORE_AP, ActionKind.WAIT},
    ScreenKind.DEFEAT: {ActionKind.WAIT},
    ScreenKind.TUTORIAL_SUMMON: {ActionKind.TUTORIAL_FREE_SUMMON, ActionKind.ADVANCE_TUTORIAL, ActionKind.WAIT},
    ScreenKind.TUTORIAL_FORMATION: {ActionKind.TUTORIAL_FORMATION, ActionKind.ADVANCE_TUTORIAL, ActionKind.WAIT},
    ScreenKind.LOADING: {ActionKind.RETRY, ActionKind.WAIT},
}


class PolicyGate:
    def __init__(self, minimum_confidence: float) -> None:
        if not 0.0 < minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be in (0, 1]")
        self.minimum_confidence = minimum_confidence

    @staticmethod
    def _inside(inner, outer) -> bool:
        return outer.left <= inner.left < inner.right <= outer.right and outer.top <= inner.top < inner.bottom <= outer.bottom

    @staticmethod
    def _label_signals(labels: tuple[str, ...]) -> tuple[set[str], set[str]]:
        tokens: set[str] = set()
        compact: set[str] = set()
        for label in labels:
            normalized = label.strip().casefold()
            tokens.update(re.findall(r"[a-z0-9]+", normalized))
            compact.add(re.sub(r"[^a-z0-9]", "", normalized))
        return tokens, compact

    @classmethod
    def _is_explicit_saint_quartz_reward_collection(
        cls,
        state: Observation,
        action: ActionProposal,
    ) -> bool:
        if not (
            state.screen is ScreenKind.QUEST_RESULT
            and action.kind is ActionKind.COLLECT_RESULT
            and action.resource is ResourceKind.NONE
            and action.resource_cost == 0
        ):
            return False
        _, state_compact = cls._label_signals(state.labels)
        quartz_labels = {
            label
            for label in state_compact
            if "quartz" in label or label.startswith("sq")
        }
        return bool(quartz_labels) and all(
            re.fullmatch(r"yougotsaintquartzx[0-9]+", label) is not None
            for label in quartz_labels
        )

    def evaluate(self, state: Observation, action: ActionProposal) -> PolicyDecision:
        if action.observation_id != state.observation_id:
            return PolicyDecision(False, "stale_observation")
        if not math.isfinite(state.confidence) or not 0.0 <= state.confidence <= 1.0:
            return PolicyDecision(False, "invalid_confidence")
        if state.screen is ScreenKind.UNKNOWN or state.confidence < self.minimum_confidence:
            return PolicyDecision(False, "low_confidence")
        all_labels = state.labels + action.labels
        tokens, compact_labels = self._label_signals(all_labels)
        _, action_compact_labels = self._label_signals(action.labels)
        has_saint_quartz_label = any(
            "quartz" in label or label.startswith("sq") for label in compact_labels
        )
        action_has_saint_quartz_label = any(
            "quartz" in label or label.startswith("sq") for label in action_compact_labels
        )
        if (
            action.resource is ResourceKind.SAINT_QUARTZ
            or action_has_saint_quartz_label
            or (
                has_saint_quartz_label
                and not self._is_explicit_saint_quartz_reward_collection(state, action)
            )
        ):
            return PolicyDecision(False, "saint_quartz_forbidden")
        if action.resource is ResourceKind.PAID_CURRENCY or "paid" in tokens or any(
            "paid" in label for label in compact_labels
        ):
            return PolicyDecision(False, "paid_currency_forbidden")
        if (
            action.kind is ActionKind.USE_COMMAND_SPELL
            or action.resource is ResourceKind.COMMAND_SPELL
            or ({"command", "spell"} <= tokens)
            or any("commandspell" in label for label in compact_labels)
        ):
            return PolicyDecision(False, "command_spells_forbidden")
        if action.kind in FORBIDDEN_ACTIONS:
            return PolicyDecision(False, "action_forbidden")
        if action.resource is ResourceKind.SUMMON_TICKET or "ticket" in tokens or any(
            "ticket" in label for label in compact_labels
        ):
            return PolicyDecision(False, "summon_ticket_forbidden")
        if action.resource_cost < 0:
            return PolicyDecision(False, "invalid_resource_cost")
        if action.resource is ResourceKind.NONE and action.resource_cost != 0:
            return PolicyDecision(False, "invalid_resource_cost")
        if action.resource is not ResourceKind.NONE and action.resource_cost == 0:
            return PolicyDecision(False, "invalid_resource_cost")
        if action.resource is not ResourceKind.NONE and action.kind not in {
            ActionKind.RESTORE_AP,
        }:
            return PolicyDecision(False, "resource_not_valid_for_action")
        observed_tokens, observed_compact_labels = self._label_signals(state.labels)
        if state.screen is ScreenKind.STORY and "skip" in observed_tokens and action.kind is not ActionKind.SKIP_STORY:
            return PolicyDecision(False, "skip_required")
        if action.kind not in ALLOWED_BY_SCREEN.get(state.screen, set()):
            return PolicyDecision(False, "action_not_valid_for_screen")
        if action.kind is ActionKind.TUTORIAL_FREE_SUMMON:
            if not (state.screen is ScreenKind.TUTORIAL_SUMMON and action.mandatory and action.resource is ResourceKind.NONE and action.resource_cost == 0):
                return PolicyDecision(False, "tutorial_summon_not_mandatory_free")
        if action.kind is ActionKind.TUTORIAL_FORMATION and not action.mandatory:
            return PolicyDecision(False, "tutorial_formation_not_mandatory")
        if action.kind is ActionKind.ADVANCE_TUTORIAL and not action.mandatory:
            return PolicyDecision(False, "tutorial_advance_not_mandatory")
        if (
            state.screen is ScreenKind.TITLE
            and action.kind is ActionKind.ADVANCE_TUTORIAL
            and (
                action_compact_labels != {"touchscreen"}
                or "touchscreen" not in observed_compact_labels
            )
        ):
            return PolicyDecision(False, "title_touch_screen_required")
        if (
            state.screen is ScreenKind.TITLE
            and action.kind is ActionKind.ADVANCE_TUTORIAL
            and action.target is not None
        ):
            title_touch_region = Rect(
                state.viewport.left + round(state.viewport.width * 0.34),
                state.viewport.top + round(state.viewport.height * 0.68),
                state.viewport.left + round(state.viewport.width * 0.66),
                state.viewport.top + round(state.viewport.height * 0.80),
            )
            if not self._inside(action.target, title_touch_region):
                return PolicyDecision(False, "title_touch_target_required")
        if action.kind is ActionKind.SELECT_DIALOGUE and not action.mandatory:
            return PolicyDecision(False, "dialogue_choice_not_mandatory")
        if action.kind is ActionKind.RESTORE_AP and action.resource not in APPLE_RESOURCES:
            return PolicyDecision(False, "ap_restore_resource_forbidden")
        if action.target is not None:
            if not self._inside(action.target, state.viewport):
                return PolicyDecision(False, "outside_viewport")
            if any(action.target.intersects(blocked) for blocked in state.prohibited_regions):
                return PolicyDecision(False, "prohibited_region")
        elif action.kind is not ActionKind.WAIT:
            return PolicyDecision(False, "missing_target")
        return PolicyDecision(True, "allowed")
