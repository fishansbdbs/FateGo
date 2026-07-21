from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Iterable

from .agent_models import ActionKind, ActionProposal, ResourceKind, ScreenKind
from .models import Rect
from .recognition import Recognition


class QuestMode(str, Enum):
    STORY = "STORY"
    ALL_QUESTS = "ALL_QUESTS"
    FARMING = "FARMING"


class QuestKind(str, Enum):
    STORY = "STORY"
    FREE = "FREE"


class UnknownScreenError(RuntimeError):
    pass


class NoEligibleQuestError(RuntimeError):
    pass


class PlannerSafetyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class QuestNode:
    quest_id: str
    anchor: str
    kind: QuestKind
    order: int


@dataclass(frozen=True, slots=True)
class QuestGraph:
    nodes: tuple[QuestNode, ...] = ()
    completed: frozenset[str] = frozenset()

    @classmethod
    def load(cls, path: str | Path) -> "QuestGraph":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("quest graph must use version 1")
        raw_nodes = data.get("nodes")
        raw_completed = data.get("completed", [])
        if not isinstance(raw_nodes, list) or not isinstance(raw_completed, list):
            raise ValueError("quest graph nodes and completed entries must be lists")
        nodes: list[QuestNode] = []
        quest_ids: set[str] = set()
        anchors: set[str] = set()
        for raw in raw_nodes:
            if not isinstance(raw, dict):
                raise ValueError("quest graph node must be an object")
            try:
                node = QuestNode(
                    quest_id=str(raw["quest_id"]),
                    anchor=str(raw["anchor"]),
                    kind=QuestKind(str(raw["kind"])),
                    order=int(raw["order"]),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("quest graph contains an invalid node") from error
            if not node.quest_id or not node.anchor or node.order < 0:
                raise ValueError("quest graph contains an invalid node")
            if node.quest_id in quest_ids or node.anchor in anchors:
                raise ValueError("quest graph quest IDs and anchors must be unique")
            quest_ids.add(node.quest_id)
            anchors.add(node.anchor)
            nodes.append(node)
        completed = frozenset(str(item) for item in raw_completed)
        if not completed <= quest_ids:
            raise ValueError("quest graph completed list references an unknown quest")
        nodes.sort(key=lambda item: (item.order, item.quest_id))
        return cls(tuple(nodes), completed)

    def eligible_anchors(self, mode: QuestMode, visible: Iterable[str]) -> tuple[str, ...]:
        visible_set = set(visible)
        if mode is QuestMode.FARMING:
            return ()
        kinds = {QuestKind.STORY} if mode is QuestMode.STORY else {QuestKind.STORY, QuestKind.FREE}
        return tuple(
            node.anchor
            for node in self.nodes
            if node.kind in kinds and node.quest_id not in self.completed and node.anchor in visible_set
        )


class QuestPlanner:
    def __init__(
        self,
        mode: QuestMode,
        *,
        graph: QuestGraph | None = None,
        farming_anchor: str | None = None,
    ) -> None:
        if mode is QuestMode.FARMING and not farming_anchor:
            raise ValueError("farming mode requires a configured quest anchor")
        self.mode = mode
        self.graph = graph if graph is not None else QuestGraph()
        self.farming_anchor = farming_anchor

    @staticmethod
    def _target(state: Recognition, name: str) -> Rect:
        try:
            return state.anchors[name]
        except KeyError as error:
            raise PlannerSafetyError(f"required anchor is missing: {name}") from error

    @staticmethod
    def _proposal(
        state: Recognition,
        kind: ActionKind,
        target: Rect | None,
        labels: tuple[str, ...],
        *,
        mandatory: bool = False,
    ) -> ActionProposal:
        return ActionProposal(
            observation_id=state.frame_sha256,
            kind=kind,
            target=target,
            labels=labels,
            resource=ResourceKind.NONE,
            resource_cost=0,
            mandatory=mandatory,
        )

    def _story(self, state: Recognition) -> ActionProposal:
        return self._proposal(
            state,
            ActionKind.SKIP_STORY,
            self._target(state, "skip"),
            ("Skip", "anchor:skip"),
        )

    def _skip_confirm(self, state: Recognition) -> ActionProposal:
        return self._proposal(
            state,
            ActionKind.CONFIRM_SKIP,
            self._target(state, "yes"),
            ("Skip confirmation", "anchor:yes"),
        )

    def _dialogue_choice(self, state: Recognition) -> ActionProposal:
        choices = [
            (name, rect)
            for name, rect in state.anchors.items()
            if name.startswith("choice_")
        ]
        if not choices:
            raise PlannerSafetyError("dialogue choice has no verified target")
        name, target = min(choices, key=lambda item: (item[1].top, item[1].left, item[0]))
        return self._proposal(
            state,
            ActionKind.SELECT_DIALOGUE,
            target,
            ("mandatory dialogue choice", f"anchor:{name}"),
            mandatory=True,
        )

    def _map(self, state: Recognition) -> ActionProposal:
        visible = set(state.anchors)
        if self.mode is QuestMode.FARMING:
            assert self.farming_anchor is not None
            if self.farming_anchor not in visible:
                raise NoEligibleQuestError("configured farming quest is not visible")
            anchor = self.farming_anchor
        else:
            graph_anchors = self.graph.eligible_anchors(self.mode, visible)
            if graph_anchors:
                anchor = graph_anchors[0]
            else:
                story_anchors = sorted(name for name in visible if name == "main_quest" or name.startswith("main_quest_"))
                free_anchors = sorted(name for name in visible if name == "free_quest" or name.startswith("free_quest_"))
                if story_anchors:
                    anchor = story_anchors[0]
                elif self.mode is QuestMode.ALL_QUESTS and free_anchors:
                    anchor = free_anchors[0]
                else:
                    raise NoEligibleQuestError("no eligible verified quest is visible")
        return self._proposal(
            state,
            ActionKind.SELECT_QUEST,
            state.anchors[anchor],
            (f"mode:{self.mode.value}", f"anchor:{anchor}"),
        )

    def _support(self, state: Recognition) -> ActionProposal:
        guest_names = sorted(name for name in state.anchors if name in {"guest", "guest_row"} or name.startswith("guest_"))
        if guest_names:
            name = guest_names[0]
        else:
            compatible = sorted(
                (name for name in state.anchors if name.startswith("support_compatible_")),
                reverse=True,
            )
            generic = sorted(name for name in state.anchors if name.startswith("support_row_"))
            choices = compatible or generic
            if not choices:
                raise PlannerSafetyError("support screen has no verified support row")
            name = choices[0]
        return self._proposal(
            state,
            ActionKind.SELECT_SUPPORT,
            state.anchors[name],
            (f"anchor:{name}", "deterministic support selection"),
        )

    def _party(self, state: Recognition) -> ActionProposal:
        if "teapot_off" not in state.anchors:
            raise PlannerSafetyError("Auto Teapot OFF was not verified")
        return self._proposal(
            state,
            ActionKind.START_QUEST,
            self._target(state, "start"),
            ("Auto Teapot OFF", "anchor:start"),
        )

    def _result(self, state: Recognition) -> ActionProposal:
        if "next" in state.anchors:
            anchor = "next"
        elif {"bond_title", "bond_progress"} <= set(state.anchors):
            anchor = "bond_title"
        elif {"exp_heading", "exp_title"} <= set(state.anchors):
            anchor = "exp_title"
        elif {"clear_rewards_title", "tap_to_continue"} <= set(state.anchors):
            anchor = "tap_to_continue"
        else:
            raise PlannerSafetyError("quest result has no verified continue target")
        return self._proposal(
            state,
            ActionKind.COLLECT_RESULT,
            self._target(state, anchor),
            ("Quest result", f"anchor:{anchor}"),
        )

    def _loading(self, state: Recognition) -> ActionProposal:
        return self._proposal(state, ActionKind.WAIT, None, ("loading",))

    def plan(self, state: Recognition) -> ActionProposal:
        handlers = {
            ScreenKind.STORY: self._story,
            ScreenKind.SKIP_CONFIRM: self._skip_confirm,
            ScreenKind.DIALOGUE_CHOICE: self._dialogue_choice,
            ScreenKind.TUTORIAL_MAP: self._map,
            ScreenKind.SUPPORT_SELECT: self._support,
            ScreenKind.PARTY_CONFIRM: self._party,
            ScreenKind.QUEST_RESULT: self._result,
            ScreenKind.LOADING: self._loading,
        }
        handler = handlers.get(state.screen)
        if handler is None:
            raise UnknownScreenError(f"no navigation handler for {state.screen.value}:{state.frame_sha256}")
        return handler(state)
