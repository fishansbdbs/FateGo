from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import Rect


class ScreenKind(str, Enum):
    TITLE = "TITLE"
    TUTORIAL_MAP = "TUTORIAL_MAP"
    TUTORIAL_PROMPT = "TUTORIAL_PROMPT"
    STORY = "STORY"
    SKIP_CONFIRM = "SKIP_CONFIRM"
    DIALOGUE_CHOICE = "DIALOGUE_CHOICE"
    SUPPORT_SELECT = "SUPPORT_SELECT"
    PARTY_CONFIRM = "PARTY_CONFIRM"
    BATTLE = "BATTLE"
    QUEST_RESULT = "QUEST_RESULT"
    AP_REFILL = "AP_REFILL"
    DEFEAT = "DEFEAT"
    TUTORIAL_SUMMON = "TUTORIAL_SUMMON"
    TUTORIAL_FORMATION = "TUTORIAL_FORMATION"
    LOADING = "LOADING"
    UNKNOWN = "UNKNOWN"


class ActionKind(str, Enum):
    SELECT_QUEST = "SELECT_QUEST"
    ADVANCE_TUTORIAL = "ADVANCE_TUTORIAL"
    SKIP_STORY = "SKIP_STORY"
    CONFIRM_SKIP = "CONFIRM_SKIP"
    SELECT_DIALOGUE = "SELECT_DIALOGUE"
    SELECT_SUPPORT = "SELECT_SUPPORT"
    CONFIRM_PARTY = "CONFIRM_PARTY"
    START_QUEST = "START_QUEST"
    USE_SKILL = "USE_SKILL"
    SELECT_TARGET = "SELECT_TARGET"
    ATTACK = "ATTACK"
    SELECT_COMMAND_CARD = "SELECT_COMMAND_CARD"
    SELECT_NOBLE_PHANTASM = "SELECT_NOBLE_PHANTASM"
    COLLECT_RESULT = "COLLECT_RESULT"
    RESTORE_AP = "RESTORE_AP"
    RETRY = "RETRY"
    USE_COMMAND_SPELL = "USE_COMMAND_SPELL"
    TUTORIAL_FREE_SUMMON = "TUTORIAL_FREE_SUMMON"
    TUTORIAL_FORMATION = "TUTORIAL_FORMATION"
    OPTIONAL_SUMMON = "OPTIONAL_SUMMON"
    PURCHASE = "PURCHASE"
    ACCOUNT_ACTION = "ACCOUNT_ACTION"
    DELETE_DATA = "DELETE_DATA"
    CLEAR_CACHE = "CLEAR_CACHE"
    WAIT = "WAIT"


class ResourceKind(str, Enum):
    NONE = "NONE"
    BLUE_APPLE = "BLUE_APPLE"
    BRONZE_APPLE = "BRONZE_APPLE"
    SILVER_APPLE = "SILVER_APPLE"
    GOLDEN_APPLE = "GOLDEN_APPLE"
    COMMAND_SPELL = "COMMAND_SPELL"
    SUMMON_TICKET = "SUMMON_TICKET"
    SAINT_QUARTZ = "SAINT_QUARTZ"
    PAID_CURRENCY = "PAID_CURRENCY"


@dataclass(frozen=True, slots=True)
class Observation:
    observation_id: str
    screen: ScreenKind
    confidence: float
    frame_sha256: str
    viewport: Rect
    prohibited_regions: tuple[Rect, ...]
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionProposal:
    observation_id: str
    kind: ActionKind
    target: Rect | None
    labels: tuple[str, ...]
    resource: ResourceKind
    resource_cost: int
    mandatory: bool


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
