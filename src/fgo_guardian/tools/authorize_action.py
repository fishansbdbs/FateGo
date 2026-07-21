from __future__ import annotations

import argparse

from fgo_guardian.agent_models import ActionKind, ActionProposal, ResourceKind
from fgo_guardian.policy import PolicyGate
from fgo_guardian.privacy import PrivacyPolicy
from fgo_guardian.recording import RecordingStore
from fgo_guardian.tools.common import (
    ensure_not_stopped,
    latest_observation,
    parse_normalized_rect,
    project_root,
    session_root,
    session_state_lock,
)
from fgo_guardian.viewport_mapper import ViewportMapping


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--action", required=True, choices=[item.value for item in ActionKind])
    parser.add_argument("--target", nargs=4, type=float)
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument(
        "--resource",
        choices=[item.value for item in ResourceKind],
        default=ResourceKind.NONE.value,
    )
    parser.add_argument("--resource-cost", type=int, default=0)
    parser.add_argument("--mandatory", action="store_true")
    args = parser.parse_args()
    if args.resource_cost < 0:
        parser.error("--resource-cost cannot be negative")

    root = project_root()
    session = session_root(args.session)
    with session_state_lock(session):
        ensure_not_stopped(session, locked=True)
        state = latest_observation(session)
        mapping = ViewportMapping(
            viewport=state.viewport,
            titlebar_bottom=state.viewport.top,
            toolbar_left=state.viewport.right,
        )
        target = (
            None
            if args.target is None
            else mapping.normalized_rect(parse_normalized_rect(args.target))
        )
        proposal = ActionProposal(
            observation_id=state.observation_id,
            kind=ActionKind(args.action),
            target=target,
            labels=tuple(args.label),
            resource=ResourceKind(args.resource),
            resource_cost=args.resource_cost,
            mandatory=args.mandatory,
        )
        store = RecordingStore(session, PrivacyPolicy.load(root / "config" / "privacy.json"))
        try:
            token = store.authorize(state, proposal, PolicyGate(0.92))
        except PermissionError as error:
            parser.exit(2, f"{error}\n")
    print(token)


if __name__ == "__main__":
    main()
