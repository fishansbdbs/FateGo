from fgo_guardian.agent_models import (
    ActionKind,
    ActionProposal,
    Observation,
    ResourceKind,
    ScreenKind,
)
from fgo_guardian.models import Rect
from fgo_guardian.policy import PolicyGate


def observation(screen: ScreenKind = ScreenKind.TUTORIAL_MAP, labels: tuple[str, ...] = ()) -> Observation:
    return Observation(
        observation_id="obs-1",
        screen=screen,
        confidence=0.99,
        frame_sha256="a" * 64,
        viewport=Rect(0, 0, 1600, 900),
        prohibited_regions=(Rect(0, 800, 400, 900),),
        labels=labels,
    )


def proposal(**overrides) -> ActionProposal:
    values = {
        "observation_id": "obs-1",
        "kind": ActionKind.SELECT_QUEST,
        "target": Rect(700, 300, 900, 500),
        "labels": ("NEXT",),
        "resource": ResourceKind.NONE,
        "resource_cost": 0,
        "mandatory": False,
    }
    values.update(overrides)
    return ActionProposal(**values)


def test_all_saint_quartz_actions_are_rejected() -> None:
    gate = PolicyGate(minimum_confidence=0.92)
    decision = gate.evaluate(
        observation(),
        proposal(kind=ActionKind.RESTORE_AP, resource=ResourceKind.SAINT_QUARTZ, resource_cost=1),
    )
    assert not decision.allowed
    assert decision.reason == "saint_quartz_forbidden"


def test_collecting_an_explicit_saint_quartz_quest_reward_is_allowed_without_spend_authority() -> None:
    gate = PolicyGate(minimum_confidence=0.92)
    state = observation(
        ScreenKind.QUEST_RESULT,
        ("Quest Clear Rewards", "You got Saint Quartz x 1!", "Please Tap the Screen"),
    )
    collect = proposal(
        kind=ActionKind.COLLECT_RESULT,
        labels=("Please Tap the Screen", "Quest Clear Rewards"),
        resource=ResourceKind.NONE,
        resource_cost=0,
    )

    assert gate.evaluate(state, collect).allowed
    assert gate.evaluate(
        observation(ScreenKind.QUEST_RESULT, ("Use Saint Quartz x 1",)),
        collect,
    ).reason == "saint_quartz_forbidden"
    assert gate.evaluate(
        observation(
            ScreenKind.QUEST_RESULT,
            ("You got Saint Quartz x 1; spend Saint Quartz to continue",),
        ),
        collect,
    ).reason == "saint_quartz_forbidden"
    assert gate.evaluate(
        state,
        proposal(
            kind=ActionKind.COLLECT_RESULT,
            resource=ResourceKind.SAINT_QUARTZ,
            resource_cost=1,
        ),
    ).reason == "saint_quartz_forbidden"


def test_zero_cost_mandatory_tutorial_summon_is_narrowly_allowed() -> None:
    gate = PolicyGate(minimum_confidence=0.92)
    state = observation(ScreenKind.TUTORIAL_SUMMON)
    action = proposal(
        kind=ActionKind.TUTORIAL_FREE_SUMMON,
        resource=ResourceKind.NONE,
        resource_cost=0,
        mandatory=True,
    )
    assert gate.evaluate(state, action).allowed


def test_optional_or_ticket_summon_is_rejected() -> None:
    gate = PolicyGate(minimum_confidence=0.92)
    state = observation(ScreenKind.TUTORIAL_SUMMON)
    action = proposal(kind=ActionKind.OPTIONAL_SUMMON, resource=ResourceKind.SUMMON_TICKET)
    assert gate.evaluate(state, action).reason == "action_forbidden"
    assert gate.evaluate(
        observation(),
        proposal(resource=ResourceKind.SUMMON_TICKET, resource_cost=1),
    ).reason == "summon_ticket_forbidden"
    assert gate.evaluate(
        observation(),
        proposal(resource=ResourceKind.BLUE_APPLE, resource_cost=1),
    ).reason == "resource_not_valid_for_action"
    assert gate.evaluate(
        observation(ScreenKind.TUTORIAL_SUMMON, ("Summon Ticket",)),
        proposal(kind=ActionKind.TUTORIAL_FREE_SUMMON, mandatory=True),
    ).reason == "summon_ticket_forbidden"
    assert gate.evaluate(
        observation(ScreenKind.TUTORIAL_SUMMON, ("Paid Summon",)),
        proposal(kind=ActionKind.TUTORIAL_FREE_SUMMON, mandatory=True),
    ).reason == "paid_currency_forbidden"
    assert gate.evaluate(
        observation(ScreenKind.TUTORIAL_SUMMON, ("SummonTicket",)),
        proposal(kind=ActionKind.TUTORIAL_FREE_SUMMON, mandatory=True),
    ).reason == "summon_ticket_forbidden"
    assert gate.evaluate(
        observation(ScreenKind.TUTORIAL_SUMMON, ("PaidSummon",)),
        proposal(kind=ActionKind.TUTORIAL_FREE_SUMMON, mandatory=True),
    ).reason == "paid_currency_forbidden"


def test_short_sq_label_is_rejected_even_when_resource_is_none() -> None:
    gate = PolicyGate(0.92)
    for state, action in (
        (observation(), proposal(labels=("SQ",))),
        (observation(), proposal(labels=("SQ x1",))),
        (observation((ScreenKind.TUTORIAL_MAP), ("Saint Quartz",)), proposal()),
    ):
        assert gate.evaluate(state, action).reason == "saint_quartz_forbidden"


def test_action_must_match_screen_and_forced_tutorial_step() -> None:
    gate = PolicyGate(0.92)
    assert gate.evaluate(
        observation(ScreenKind.TITLE, ("Touch Screen",)),
        proposal(
            kind=ActionKind.ADVANCE_TUTORIAL,
            target=Rect(650, 630, 950, 710),
            labels=("Touch Screen",),
            mandatory=True,
        ),
    ).allowed
    assert gate.evaluate(
        observation(ScreenKind.TITLE, ("Touch Screen",)),
        proposal(
            kind=ActionKind.ADVANCE_TUTORIAL,
            target=Rect(650, 630, 950, 710),
            labels=("Data Transfer",),
            mandatory=True,
        ),
    ).reason == "title_touch_screen_required"
    assert gate.evaluate(
        observation(ScreenKind.TITLE, ("Touch Screen",)),
        proposal(
            kind=ActionKind.ADVANCE_TUTORIAL,
            target=Rect(650, 630, 950, 710),
            labels=("Clear Cache",),
            mandatory=True,
        ),
    ).reason == "title_touch_screen_required"
    for observed_label in ("Data Transfer", "Clear Cache"):
        assert gate.evaluate(
            observation(ScreenKind.TITLE, (observed_label,)),
            proposal(
                kind=ActionKind.ADVANCE_TUTORIAL,
                target=Rect(650, 630, 950, 710),
                labels=("Touch Screen",),
                mandatory=True,
            ),
        ).reason == "title_touch_screen_required"
    assert gate.evaluate(
        observation(ScreenKind.TITLE, ("Touch Screen",)),
        proposal(
            kind=ActionKind.ADVANCE_TUTORIAL,
            target=Rect(50, 50, 150, 150),
            labels=("Touch Screen",),
            mandatory=True,
        ),
    ).reason == "title_touch_target_required"
    assert gate.evaluate(
        observation(ScreenKind.BATTLE),
        proposal(kind=ActionKind.SELECT_QUEST),
    ).reason == "action_not_valid_for_screen"
    assert gate.evaluate(
        observation(ScreenKind.TUTORIAL_FORMATION),
        proposal(kind=ActionKind.TUTORIAL_FORMATION, mandatory=False),
    ).reason == "tutorial_formation_not_mandatory"
    assert gate.evaluate(
        observation(ScreenKind.TUTORIAL_PROMPT),
        proposal(kind=ActionKind.ADVANCE_TUTORIAL, mandatory=False),
    ).reason == "tutorial_advance_not_mandatory"
    assert gate.evaluate(
        observation(ScreenKind.TITLE, ("Touch Screen",)),
        proposal(
            kind=ActionKind.ADVANCE_TUTORIAL,
            target=Rect(650, 630, 950, 710),
            labels=("Touch Screen",),
            mandatory=False,
        ),
    ).reason == "tutorial_advance_not_mandatory"
    assert gate.evaluate(
        observation(ScreenKind.STORY, ("Skip",)),
        proposal(kind=ActionKind.SELECT_DIALOGUE, mandatory=True),
    ).reason == "skip_required"
    assert gate.evaluate(
        observation(ScreenKind.STORY, ("Skip",)),
        proposal(kind=ActionKind.WAIT, target=None),
    ).reason == "skip_required"
    assert gate.evaluate(
        observation(ScreenKind.DIALOGUE_CHOICE),
        proposal(kind=ActionKind.SELECT_DIALOGUE, mandatory=False),
    ).reason == "dialogue_choice_not_mandatory"


def test_stale_low_confidence_and_blocked_targets_are_rejected() -> None:
    gate = PolicyGate(minimum_confidence=0.92)
    assert gate.evaluate(observation(), proposal(observation_id="old")).reason == "stale_observation"
    low = observation()
    low = Observation(low.observation_id, low.screen, 0.50, low.frame_sha256, low.viewport, low.prohibited_regions, low.labels)
    assert gate.evaluate(low, proposal()).reason == "low_confidence"
    for invalid in (float("nan"), float("inf"), -0.1, 1.1):
        malformed = Observation(low.observation_id, low.screen, invalid, low.frame_sha256, low.viewport, low.prohibited_regions, low.labels)
        assert gate.evaluate(malformed, proposal()).reason == "invalid_confidence"
    assert gate.evaluate(observation(), proposal(target=Rect(10, 820, 200, 880))).reason == "prohibited_region"
