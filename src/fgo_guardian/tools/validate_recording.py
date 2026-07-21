from __future__ import annotations

import argparse
import re
from pathlib import Path

from fgo_guardian.agent_models import (
    ActionKind,
    ActionProposal,
    Observation,
    ResourceKind,
    ScreenKind,
)
from fgo_guardian.models import Rect
from fgo_guardian.policy import PolicyGate
from fgo_guardian.replay import ReplaySession
from fgo_guardian.tools.common import is_owned_unobservable_state


FORBIDDEN_KINDS = {
    ActionKind.OPTIONAL_SUMMON.value,
    ActionKind.PURCHASE.value,
    ActionKind.ACCOUNT_ACTION.value,
    ActionKind.DELETE_DATA.value,
    ActionKind.CLEAR_CACHE.value,
}


def _proposal_has_quartz(proposal: dict[str, object]) -> bool:
    labels = proposal.get("labels", ())
    normalized_labels: set[str] = set()
    if isinstance(labels, (list, tuple)):
        normalized_labels = {
            re.sub(r"[^a-z0-9]", "", label.strip().casefold())
            for label in labels
            if isinstance(label, str)
        }
    return proposal.get("resource") == "SAINT_QUARTZ" or any(
        "quartz" in label or label.startswith("sq") for label in normalized_labels
    )


def _normalized_proposal_labels(proposal: dict[str, object]) -> set[str]:
    labels = proposal.get("labels", ())
    if not isinstance(labels, (list, tuple)):
        return set()
    return {
        re.sub(r"[^a-z0-9]", "", label.strip().casefold())
        for label in labels
        if isinstance(label, str)
    }


def _validate_proposal_enums_and_currency(proposal: dict[str, object]) -> None:
    labels = _normalized_proposal_labels(proposal)
    if _proposal_has_quartz(proposal):
        raise ValueError("recording contains a Saint Quartz proposal")
    if proposal.get("resource") == ResourceKind.SUMMON_TICKET.value or any(
        "ticket" in label for label in labels
    ):
        raise ValueError("recording contains a Summon Ticket proposal")
    if proposal.get("resource") == ResourceKind.PAID_CURRENCY.value or any(
        "paid" in label for label in labels
    ):
        raise ValueError("recording contains a paid currency proposal")
    try:
        action_kind = ActionKind(proposal.get("kind"))
    except (TypeError, ValueError) as error:
        raise ValueError("recording contains an unknown action kind") from error
    try:
        ResourceKind(proposal.get("resource"))
    except (TypeError, ValueError) as error:
        raise ValueError("recording contains an unknown resource") from error
    if action_kind.value in FORBIDDEN_KINDS:
        raise ValueError("recording contains a permanently forbidden action proposal")


def _read_state(root: Path, name: str) -> str:
    try:
        return (root / name).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"safe-stop recording is missing readable {name}") from error


def _validate_one_safe_stop_tail(
    root: Path,
    observations: list[dict[str, object]],
    actions: list[dict[str, object]],
    transitions: list[dict[str, object]],
) -> None:
    allowed_actions = [
        action
        for action in actions
        if isinstance(action.get("decision"), dict)
        and action["decision"].get("allowed") is True
    ]
    transitioned_tokens = {
        transition.get("token")
        for transition in transitions
        if isinstance(transition.get("token"), str)
    }
    missing = [
        action
        for action in allowed_actions
        if action.get("token") not in transitioned_tokens
    ]
    if len(missing) != 1 or not allowed_actions or missing[0] is not allowed_actions[-1]:
        raise ValueError("safe-stop recording must have exactly one trailing incomplete action")
    pending = missing[0]
    if not actions or pending is not actions[-1] or not observations:
        raise ValueError("safe-stop recording must end at its incomplete action")
    proposal = pending.get("proposal")
    if not isinstance(proposal, dict):
        raise ValueError("invalid actions.jsonl")
    _validate_proposal_enums_and_currency(proposal)
    final_observation_id = observations[-1].get("observation_id")
    if proposal.get("observation_id") != final_observation_id:
        raise ValueError("safe-stop action does not follow the final observation")
    if pending.get("required_after_sequence") != len(observations):
        raise ValueError("safe-stop action does not require the next observation")
    if _read_state(root, "STOPPED") != "emergency_stop":
        raise ValueError("safe-stop recording is missing emergency_stop")
    pause = _read_state(root, "VIEWPORT_PAUSED")
    if not is_owned_unobservable_state(pause):
        raise ValueError("safe-stop recording is missing an owned unobservable viewport")


def _as_rect(value: object) -> Rect:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        raise ValueError("recording contains invalid policy geometry")
    return Rect(*value)


def _validate_allowed_action_policies(
    observations: list[dict[str, object]],
    actions: list[dict[str, object]],
) -> None:
    observations_by_id = {
        observation.get("observation_id"): observation for observation in observations
    }
    gate = PolicyGate(0.92)
    for item in actions:
        decision = item.get("decision")
        if not isinstance(decision, dict) or decision.get("allowed") is not True:
            continue
        proposal_raw = item.get("proposal")
        if not isinstance(proposal_raw, dict):
            raise ValueError("invalid actions.jsonl")
        before_id = proposal_raw.get("observation_id")
        observation_raw = observations_by_id.get(before_id)
        if not isinstance(before_id, str) or not isinstance(observation_raw, dict):
            raise ValueError("allowed action is missing its policy observation")
        try:
            confidence = observation_raw["confidence"]
            state_labels = observation_raw.get("labels", [])
            if (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not isinstance(state_labels, list)
                or not all(isinstance(label, str) for label in state_labels)
            ):
                raise ValueError("invalid policy observation fields")
            state = Observation(
                observation_id=before_id,
                screen=ScreenKind(observation_raw["screen"]),
                confidence=float(confidence),
                frame_sha256=str(observation_raw["frame_sha256"]),
                viewport=_as_rect(observation_raw["viewport"]),
                prohibited_regions=tuple(
                    _as_rect(region)
                    for region in observation_raw.get("prohibited_regions", [])
                ),
                labels=tuple(state_labels),
            )
            target_raw = proposal_raw.get("target")
            proposal = ActionProposal(
                observation_id=before_id,
                kind=ActionKind(proposal_raw["kind"]),
                target=None if target_raw is None else _as_rect(target_raw),
                labels=tuple(proposal_raw["labels"]),
                resource=ResourceKind(proposal_raw["resource"]),
                resource_cost=proposal_raw["resource_cost"],
                mandatory=proposal_raw["mandatory"],
            )
            evaluated = gate.evaluate(state, proposal)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise ValueError("recording contains an invalid policy state") from error
        if not evaluated.allowed or decision.get("reason") != evaluated.reason:
            raise ValueError(
                "recorded policy rejects an allowed action: " + evaluated.reason
            )


def validate_recording(
    root: Path,
    required_screens: set[ScreenKind],
    *,
    allow_incomplete_safe_stop: bool = False,
) -> dict[str, int]:
    replay = ReplaySession(root)
    observations = replay.observations()
    actions = replay.actions()
    transitions = replay.transitions()
    screens: set[ScreenKind] = set()
    for observation in observations:
        try:
            screen = ScreenKind(observation["screen"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid observation screen") from error
        if screen is ScreenKind.UNKNOWN:
            raise ValueError("recording contains an UNKNOWN observation")
        if screen is ScreenKind.TITLE and int(observation.get("masks_applied", 0)) < 1:
            raise ValueError("TITLE observation is missing its privacy mask")
        screens.add(screen)
    for action in actions:
        proposal = action.get("proposal")
        if not isinstance(proposal, dict):
            raise ValueError("invalid actions.jsonl")
        _validate_proposal_enums_and_currency(proposal)
    missing_screens = required_screens - screens
    if missing_screens:
        raise ValueError(
            "missing required screens: "
            + ",".join(sorted(item.value for item in missing_screens))
        )

    pending_actions = 0
    try:
        replay.validate()
    except ValueError as error:
        if not (
            allow_incomplete_safe_stop
            and str(error) == "allowed actions and transitions are not one-to-one"
        ):
            raise
        _validate_one_safe_stop_tail(root, observations, actions, transitions)
        pending_actions = 1

    _validate_allowed_action_policies(observations, actions)

    counts = {
        "observations": len(observations),
        "actions": len(actions),
        "transitions": len(transitions),
    }
    if allow_incomplete_safe_stop:
        counts["pending_actions"] = pending_actions
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--allow-incomplete-safe-stop", action="store_true")
    parser.add_argument(
        "--required-screen",
        action="append",
        choices=[item.value for item in ScreenKind if item is not ScreenKind.UNKNOWN],
    )
    args = parser.parse_args()
    required = {
        ScreenKind.TUTORIAL_MAP,
        ScreenKind.STORY,
        ScreenKind.SUPPORT_SELECT,
        ScreenKind.PARTY_CONFIRM,
        ScreenKind.BATTLE,
        ScreenKind.QUEST_RESULT,
    }
    if args.required_screen is not None:
        required = {ScreenKind(value) for value in args.required_screen}
    counts = validate_recording(
        args.root,
        required,
        allow_incomplete_safe_stop=args.allow_incomplete_safe_stop,
    )
    fields = [
        f"observations={counts['observations']}",
        f"actions={counts['actions']}",
        f"transitions={counts['transitions']}",
    ]
    if "pending_actions" in counts:
        fields.append(f"pending_actions={counts['pending_actions']}")
    print(" ".join(fields))


if __name__ == "__main__":
    main()
