from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


class ReplaySession:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _read(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        try:
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid {path.name}") from error
        if not all(isinstance(record, dict) for record in records):
            raise ValueError(f"invalid {path.name}")
        return records

    def observations(self) -> list[dict[str, object]]:
        return self._read(self.root / "observations.jsonl")

    def actions(self) -> list[dict[str, object]]:
        return self._read(self.root / "actions.jsonl")

    def transitions(self) -> list[dict[str, object]]:
        return self._read(self.root / "transitions.jsonl")

    def validate(self) -> None:
        observation_items = self.observations()
        action_items = self.actions()
        transition_items = self.transitions()
        try:
            observation_ids = [item["observation_id"] for item in observation_items]
        except KeyError as error:
            raise ValueError("invalid observations.jsonl") from error
        if not all(isinstance(observation_id, str) and observation_id for observation_id in observation_ids):
            raise ValueError("invalid observations.jsonl")
        observations = {observation_id: item for observation_id, item in zip(observation_ids, observation_items, strict=True)}
        if len(observations) != len(observation_items):
            raise ValueError("duplicate observation id")
        observation_sequences = {observation_id: sequence for sequence, observation_id in enumerate(observation_ids)}

        resolved_root = self.root.resolve()
        for observation_id, item in observations.items():
            try:
                path = (self.root / str(item["image_path"])).resolve()
                expected_digest = item["frame_sha256"]
            except KeyError as error:
                raise ValueError("invalid observations.jsonl") from error
            if not isinstance(item["image_path"], str) or not isinstance(expected_digest, str):
                raise ValueError("invalid observations.jsonl")
            if path != resolved_root and resolved_root not in path.parents:
                raise ValueError("observation image escapes session root")
            try:
                frame = np.asarray(Image.open(path).convert("RGB"))
            except (FileNotFoundError, OSError) as error:
                raise ValueError(f"observation image is unavailable: {observation_id}") from error
            digest = hashlib.sha256(frame.tobytes()).hexdigest()
            if digest != expected_digest:
                raise ValueError(f"observation hash mismatch: {observation_id}")

        allowed_actions: dict[str, dict[str, object]] = {}
        attempt_ids: set[str] = set()
        allowed_before_ids: set[object] = set()
        for action in action_items:
            try:
                attempt_id = action["attempt_id"]
                token = action["token"]
                decision = action["decision"]
                proposal = action["proposal"]
            except (KeyError, TypeError) as error:
                raise ValueError("invalid actions.jsonl") from error
            if not isinstance(decision, dict) or not isinstance(proposal, dict):
                raise ValueError("invalid actions.jsonl")
            try:
                allowed = decision["allowed"]
                reason = decision["reason"]
                before_id = proposal["observation_id"]
                kind = proposal["kind"]
                target = proposal["target"]
                labels = proposal["labels"]
                resource = proposal["resource"]
                resource_cost = proposal["resource_cost"]
                mandatory = proposal["mandatory"]
            except KeyError as error:
                raise ValueError("invalid actions.jsonl") from error
            if (
                not isinstance(allowed, bool)
                or not isinstance(reason, str)
                or not isinstance(before_id, str)
                or not before_id
                or not isinstance(kind, str)
                or not isinstance(labels, list)
                or not all(isinstance(label, str) for label in labels)
                or not isinstance(resource, str)
                or not isinstance(resource_cost, int)
                or isinstance(resource_cost, bool)
                or not isinstance(mandatory, bool)
                or (
                    target is not None
                    and (
                        not isinstance(target, list)
                        or len(target) != 4
                        or any(not isinstance(value, int) or isinstance(value, bool) for value in target)
                    )
                )
            ):
                raise ValueError("invalid actions.jsonl")
            if not isinstance(attempt_id, str) or not attempt_id or attempt_id in attempt_ids:
                raise ValueError("duplicate action attempt id")
            attempt_ids.add(attempt_id)
            if allowed is False:
                if token is not None:
                    raise ValueError("denied action has an authorization token")
                continue
            if allowed is not True:
                raise ValueError("invalid actions.jsonl")
            if not isinstance(token, str) or not token or token in allowed_actions:
                raise ValueError("duplicate action token")
            try:
                bound_frame_sha256 = action["bound_frame_sha256"]
                required_after_sequence = action["required_after_sequence"]
            except KeyError as error:
                raise ValueError("invalid actions.jsonl") from error
            if not isinstance(bound_frame_sha256, str):
                raise ValueError("invalid actions.jsonl")
            if before_id not in observations:
                raise ValueError("action proposal references a missing observation")
            if bound_frame_sha256 != observations[before_id]["frame_sha256"]:
                raise ValueError("action bound frame hash does not match observation")
            if (
                not isinstance(required_after_sequence, int)
                or isinstance(required_after_sequence, bool)
                or required_after_sequence != observation_sequences[before_id] + 1
            ):
                raise ValueError("action required after sequence does not match observation order")
            if before_id in allowed_before_ids:
                raise ValueError("observation authorizes more than one allowed action")
            allowed_before_ids.add(before_id)
            allowed_actions[token] = action

        transition_tokens: list[str] = []
        for transition in transition_items:
            try:
                token = transition["token"]
            except KeyError as error:
                raise ValueError("invalid transitions.jsonl") from error
            if not isinstance(token, str) or not token:
                raise ValueError("invalid transitions.jsonl")
            transition_tokens.append(token)
        if len(set(transition_tokens)) != len(transition_tokens):
            raise ValueError("duplicate transition token")
        for transition in transition_items:
            try:
                before_id = transition["before_id"]
                after_id = transition["after_id"]
                token = transition["token"]
            except KeyError as error:
                raise ValueError("invalid transitions.jsonl") from error
            if not isinstance(before_id, str) or not isinstance(after_id, str) or not isinstance(token, str):
                raise ValueError("invalid transitions.jsonl")
            if before_id not in observations or after_id not in observations:
                raise ValueError("transition references a missing observation")
            action = allowed_actions.get(token)
            if action is None:
                raise ValueError("transition does not reference an allowed action")
            proposal = action["proposal"]
            if before_id != proposal["observation_id"]:
                raise ValueError("transition before id does not match its proposal")
            if observation_sequences[after_id] != action["required_after_sequence"]:
                raise ValueError("transition after id does not match required observation sequence")

        if set(transition_tokens) != set(allowed_actions):
            raise ValueError("allowed actions and transitions are not one-to-one")
