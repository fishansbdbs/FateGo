from __future__ import annotations

import argparse

from fgo_guardian.privacy import PrivacyPolicy
from fgo_guardian.recording import RecordingStore
from fgo_guardian.replay import ReplaySession
from fgo_guardian.tools.common import (
    ensure_not_stopped,
    project_root,
    session_root,
    session_state_lock,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--after-observation", required=True)
    args = parser.parse_args()

    root = project_root()
    session = session_root(args.session)
    with session_state_lock(session):
        ensure_not_stopped(session, locked=True)
        observation_ids = {item["observation_id"] for item in ReplaySession(session).observations()}
        if args.after_observation not in observation_ids:
            parser.error("--after-observation must exist in the same session")
        store = RecordingStore(session, PrivacyPolicy.load(root / "config" / "privacy.json"))
        store.complete(args.token, args.after_observation)
    print(args.token)


if __name__ == "__main__":
    main()
