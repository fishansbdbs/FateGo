from __future__ import annotations

from types import MappingProxyType

import pytest

from fgo_guardian.agent_models import ActionKind, ResourceKind, ScreenKind
from fgo_guardian.models import Rect
from fgo_guardian.quest_planner import (
    NoEligibleQuestError,
    PlannerSafetyError,
    QuestGraph,
    QuestMode,
    QuestPlanner,
    UnknownScreenError,
)
from fgo_guardian.recognition import Recognition


def _recognition(screen: ScreenKind, **anchors: Rect) -> Recognition:
    return Recognition(
        screen=screen,
        confidence=0.99,
        anchors=MappingProxyType(anchors),
        text=MappingProxyType({}),
        evidence=("test",),
        frame_sha256=screen.value.lower().ljust(64, "0")[:64],
    )


def test_story_skip_has_priority_over_every_other_control() -> None:
    planner = QuestPlanner(QuestMode.STORY)
    state = _recognition(
        ScreenKind.STORY,
        skip=Rect(900, 10, 990, 60),
        choice_1=Rect(300, 200, 700, 260),
        dialogue_controls=Rect(900, 300, 990, 550),
    )

    action = planner.plan(state)

    assert action.kind is ActionKind.SKIP_STORY
    assert action.target == state.anchors["skip"]
    assert action.resource is ResourceKind.NONE


def test_skip_confirmation_uses_only_the_verified_yes_anchor() -> None:
    planner = QuestPlanner(QuestMode.STORY)
    state = _recognition(
        ScreenKind.SKIP_CONFIRM,
        prompt=Rect(200, 100, 800, 250),
        no=Rect(250, 400, 450, 480),
        yes=Rect(550, 400, 750, 480),
    )

    action = planner.plan(state)

    assert action.kind is ActionKind.CONFIRM_SKIP
    assert action.target == state.anchors["yes"]


def test_story_map_selects_verified_next_main_quest_before_free_quest() -> None:
    planner = QuestPlanner(QuestMode.STORY)
    state = _recognition(
        ScreenKind.TUTORIAL_MAP,
        close=Rect(0, 0, 100, 50),
        main_quest=Rect(500, 100, 850, 260),
        free_quest=Rect(500, 300, 850, 460),
        menu=Rect(850, 500, 990, 590),
    )

    action = planner.plan(state)

    assert action.kind is ActionKind.SELECT_QUEST
    assert action.target == state.anchors["main_quest"]
    assert action.labels == ("mode:STORY", "anchor:main_quest")


def test_all_quests_mode_uses_free_quest_when_no_story_node_is_visible() -> None:
    planner = QuestPlanner(QuestMode.ALL_QUESTS)
    state = _recognition(
        ScreenKind.TUTORIAL_MAP,
        close=Rect(0, 0, 100, 50),
        free_quest=Rect(500, 300, 850, 460),
        menu=Rect(850, 500, 990, 590),
    )

    action = planner.plan(state)

    assert action.kind is ActionKind.SELECT_QUEST
    assert action.target == state.anchors["free_quest"]


def test_persisted_graph_controls_stable_story_node_order(tmp_path) -> None:
    path = tmp_path / "quest-graph.json"
    path.write_text(
        '{"version":1,"nodes":['
        '{"quest_id":"sect6-2","anchor":"main_quest_2","kind":"STORY","order":2},'
        '{"quest_id":"sect6-1","anchor":"main_quest_1","kind":"STORY","order":1}'
        '],"completed":["sect6-1"]}',
        encoding="utf-8",
    )
    planner = QuestPlanner(QuestMode.STORY, graph=QuestGraph.load(path))
    state = _recognition(
        ScreenKind.TUTORIAL_MAP,
        main_quest_1=Rect(500, 100, 850, 260),
        main_quest_2=Rect(500, 300, 850, 460),
    )

    assert planner.plan(state).target == state.anchors["main_quest_2"]


def test_farming_mode_requires_its_configured_visible_anchor() -> None:
    planner = QuestPlanner(QuestMode.FARMING, farming_anchor="free_quest:giant_bridge")
    missing = _recognition(ScreenKind.TUTORIAL_MAP, free_quest=Rect(500, 300, 850, 460))
    visible = _recognition(
        ScreenKind.TUTORIAL_MAP,
        **{"free_quest:giant_bridge": Rect(500, 300, 850, 460)},
    )

    with pytest.raises(NoEligibleQuestError, match="configured farming quest"):
        planner.plan(missing)
    assert planner.plan(visible).target == visible.anchors["free_quest:giant_bridge"]


def test_support_selects_guest_then_highest_ranked_compatible_row() -> None:
    guest = Rect(50, 100, 950, 240)
    planner = QuestPlanner(QuestMode.STORY)
    assert planner.plan(
        _recognition(
            ScreenKind.SUPPORT_SELECT,
            guest=guest,
            support_compatible_090=Rect(50, 260, 950, 390),
        )
    ).target == guest

    compatible = _recognition(
        ScreenKind.SUPPORT_SELECT,
        support_compatible_090=Rect(50, 260, 950, 390),
        support_compatible_120=Rect(50, 410, 950, 540),
    )
    assert planner.plan(compatible).target == compatible.anchors["support_compatible_120"]


def test_party_start_requires_auto_teapot_off() -> None:
    planner = QuestPlanner(QuestMode.STORY)
    unsafe = _recognition(ScreenKind.PARTY_CONFIRM, start=Rect(800, 500, 990, 590))
    safe = _recognition(
        ScreenKind.PARTY_CONFIRM,
        start=Rect(800, 500, 990, 590),
        teapot_off=Rect(650, 520, 730, 590),
    )

    with pytest.raises(PlannerSafetyError, match="Teapot"):
        planner.plan(unsafe)
    assert planner.plan(safe).kind is ActionKind.START_QUEST
    assert planner.plan(safe).target == safe.anchors["start"]


def test_result_and_dialogue_choice_use_visible_anchors_deterministically() -> None:
    planner = QuestPlanner(QuestMode.STORY)
    result = _recognition(ScreenKind.QUEST_RESULT, next=Rect(800, 500, 990, 590))
    choice = _recognition(
        ScreenKind.DIALOGUE_CHOICE,
        choice_2=Rect(300, 300, 700, 360),
        choice_1=Rect(300, 200, 700, 260),
    )

    assert planner.plan(result).kind is ActionKind.COLLECT_RESULT
    assert planner.plan(choice).target == choice.anchors["choice_1"]


def test_unknown_or_unhandled_screen_never_produces_a_guess() -> None:
    planner = QuestPlanner(QuestMode.STORY)

    with pytest.raises(UnknownScreenError):
        planner.plan(_recognition(ScreenKind.UNKNOWN))
    with pytest.raises(UnknownScreenError):
        planner.plan(_recognition(ScreenKind.DEFEAT))
