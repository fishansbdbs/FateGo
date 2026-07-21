from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from PIL import Image

from .agent_models import ActionKind, ActionProposal, Observation, PolicyDecision, ScreenKind
from .models import Rect
from .policy import PolicyGate
from .privacy import PrivacyPolicy
from .viewport_mapper import ViewportMapping


@dataclass(frozen=True, slots=True)
class ObservationRecord:
    observation_id: str
    timestamp: str
    screen: str
    confidence: float
    frame_sha256: str
    image_path: str
    viewport: tuple[int, int, int, int]
    prohibited_regions: tuple[tuple[int, int, int, int], ...]
    masks_applied: int
    labels: tuple[str, ...]


class RecordingStore:
    def __init__(self, root: Path, privacy: PrivacyPolicy) -> None:
        self.root = root
        self.privacy = privacy
        self.frames = root / "frames"
        self.frames.mkdir(parents=True, exist_ok=True)
        self.observations_path = root / "observations.jsonl"
        self.actions_path = root / "actions.jsonl"
        self.transitions_path = root / "transitions.jsonl"
        self.lock_path = root / ".recording.lock"

    @contextmanager
    def _mutation_lock(self):
        """Serialize read/check/append mutations across RecordingStore processes."""
        with self.lock_path.open("a+b") as handle:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.01)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _write_line(handle, line: str) -> None:
        handle.write(line)

    def _append(self, path: Path, payload: dict[str, object]) -> None:
        existed = path.exists()
        original_size = path.stat().st_size if existed else 0
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        try:
            with path.open("a", encoding="utf-8") as handle:
                self._write_line(handle, line)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            if path.exists():
                if existed:
                    with path.open("r+b") as handle:
                        handle.truncate(original_size)
                else:
                    path.unlink()
            raise

    def record_observation(
        self,
        frame: np.ndarray,
        mapping: ViewportMapping,
        screen: ScreenKind,
        confidence: float,
        labels: tuple[str, ...],
    ) -> ObservationRecord:
        safe, masks = self.privacy.redact(frame, screen, mapping)
        digest = hashlib.sha256(safe.tobytes()).hexdigest()
        observation_id = f"obs-{uuid4().hex}"
        relative = Path("frames") / f"{observation_id}.png"
        safe_labels = self._sanitize_labels(screen, labels)
        record = ObservationRecord(
            observation_id=observation_id,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            screen=screen.value,
            confidence=confidence,
            frame_sha256=digest,
            image_path=relative.as_posix(),
            viewport=mapping.viewport.as_tuple(),
            prohibited_regions=tuple(mask.as_tuple() for mask in masks),
            masks_applied=len(masks),
            labels=safe_labels,
        )
        final_path = self.root / relative
        temporary_path = self.frames / f".{observation_id}.tmp"
        try:
            with self._mutation_lock():
                try:
                    Image.fromarray(safe, mode="RGB").save(temporary_path, format="PNG")
                    temporary_path.replace(final_path)
                    self._append(self.observations_path, asdict(record))
                except BaseException:
                    temporary_path.unlink(missing_ok=True)
                    final_path.unlink(missing_ok=True)
                    raise
        finally:
            safe.fill(0)
        return record

    @staticmethod
    def _sanitize_labels(screen: ScreenKind, labels: tuple[str, ...]) -> tuple[str, ...]:
        if screen is ScreenKind.TITLE:
            compact = {
                re.sub(r"[^a-z0-9]", "", label.strip().casefold())
                for label in labels
            }
            safe = ["[TITLE_LABELS_REDACTED]"]
            if "touchscreen" in compact:
                safe.append("Touch Screen")
            return tuple(safe)
        return tuple(
            re.sub(r"\d", "x", label) if sum(character.isdigit() for character in label) >= 8 else label
            for label in labels
        )

    @classmethod
    def _sanitize_action_labels(
        cls,
        screen: ScreenKind,
        proposal: ActionProposal,
    ) -> tuple[str, ...]:
        compact = {
            re.sub(r"[^a-z0-9]", "", label.strip().casefold())
            for label in proposal.labels
        }
        if (
            screen is ScreenKind.TITLE
            and proposal.kind is ActionKind.ADVANCE_TUTORIAL
            and compact == {"touchscreen"}
        ):
            return ("Touch Screen",)
        return cls._sanitize_labels(screen, proposal.labels)

    def _record_authorization(
        self,
        proposal: ActionProposal,
        decision: PolicyDecision,
        attempt_id: str,
        token: str | None,
        bound_frame_sha256: str | None,
        required_after_sequence: int | None,
        proposal_labels: tuple[str, ...],
    ) -> None:
        self._append(self.actions_path, {
            "attempt_id": attempt_id,
            "token": token,
            "proposal": {
                "observation_id": proposal.observation_id,
                "kind": proposal.kind.value,
                "target": None if proposal.target is None else proposal.target.as_tuple(),
                "labels": proposal_labels,
                "resource": proposal.resource.value,
                "resource_cost": proposal.resource_cost,
                "mandatory": proposal.mandatory,
            },
            "decision": {"allowed": decision.allowed, "reason": decision.reason},
            "bound_frame_sha256": bound_frame_sha256,
            "required_after_sequence": required_after_sequence,
        })

    def record_authorization(
        self,
        proposal: ActionProposal,
        decision: PolicyDecision,
        attempt_id: str,
        token: str | None,
        bound_frame_sha256: str | None = None,
        required_after_sequence: int | None = None,
    ) -> None:
        with self._mutation_lock():
            self._record_authorization(
                proposal,
                decision,
                attempt_id,
                token,
                bound_frame_sha256,
                required_after_sequence,
                self._sanitize_labels(ScreenKind.UNKNOWN, proposal.labels),
            )

    def _record_transition(self, token: str, before_id: str, after_id: str) -> None:
        self._append(self.transitions_path, {"token": token, "before_id": before_id, "after_id": after_id})

    def record_transition(self, token: str, before_id: str, after_id: str) -> None:
        with self._mutation_lock():
            self._record_transition(token, before_id, after_id)

    @staticmethod
    def _read_records(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        try:
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid {path.name}") from error
        if not all(isinstance(record, dict) for record in records):
            raise ValueError(f"invalid {path.name}")
        return records

    @staticmethod
    def _canonical_observation(record: dict[str, object]) -> Observation:
        try:
            viewport = Rect(*record["viewport"])
            prohibited_regions = tuple(Rect(*region) for region in record["prohibited_regions"])
            return Observation(
                str(record["observation_id"]),
                ScreenKind(str(record["screen"])),
                float(record["confidence"]),
                str(record["frame_sha256"]),
                viewport,
                prohibited_regions,
                tuple(str(label) for label in record["labels"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid observations.jsonl") from error

    def authorize(self, state: Observation, proposal: ActionProposal, gate: PolicyGate) -> str:
        with self._mutation_lock():
            observations = self._read_records(self.observations_path)
            matching = [record for record in observations if record.get("observation_id") == state.observation_id]
            if len(matching) != 1:
                decision = gate.evaluate(state, proposal)
                if decision.allowed or decision.reason == "stale_observation":
                    decision = PolicyDecision(False, "observation_not_recorded")
                canonical = None
            else:
                canonical = self._canonical_observation(matching[0])
                if matching[0] is not observations[-1]:
                    decision = PolicyDecision(False, "observation_not_latest")
                elif canonical != state:
                    decision = PolicyDecision(False, "observation_state_mismatch")
                else:
                    decision = gate.evaluate(canonical, proposal)
            prior = self._read_records(self.actions_path)
            if decision.allowed and any(
                item["decision"]["allowed"]
                and item["proposal"]["observation_id"] == state.observation_id
                for item in prior
            ):
                decision = PolicyDecision(False, "observation_already_used")
            attempt_id = secrets.token_urlsafe(24)
            while any(item.get("attempt_id") == attempt_id for item in prior):
                attempt_id = secrets.token_urlsafe(24)
            token = secrets.token_urlsafe(24) if decision.allowed else None
            while token is not None and any(item.get("token") == token for item in prior):
                token = secrets.token_urlsafe(24)
            self._record_authorization(
                proposal,
                decision,
                attempt_id,
                token,
                canonical.frame_sha256 if decision.allowed and canonical is not None else None,
                len(observations) if decision.allowed else None,
                self._sanitize_action_labels(
                    canonical.screen if canonical is not None else ScreenKind.UNKNOWN,
                    proposal,
                ),
            )
        if not decision.allowed:
            raise PermissionError(decision.reason)
        assert token is not None
        return token

    def complete(self, token: str, after_id: str) -> None:
        with self._mutation_lock():
            actions = self._read_records(self.actions_path)
            matching = [item for item in actions if item["token"] == token and item["decision"]["allowed"]]
            if len(matching) != 1:
                raise ValueError("token does not identify one allowed action")
            observations = self._read_records(self.observations_path)
            required_after_sequence = matching[0].get("required_after_sequence")
            if not isinstance(required_after_sequence, int) or required_after_sequence < 1:
                raise ValueError("allowed action has invalid required after sequence")
            if required_after_sequence >= len(observations):
                raise ValueError("after observation must be strictly later than authorization")
            if observations[required_after_sequence].get("observation_id") != after_id:
                raise ValueError("after observation must be the first strictly later observation")
            transitions = self._read_records(self.transitions_path)
            if any(item["token"] == token for item in transitions):
                raise ValueError("authorization token is already complete")
            self._record_transition(token, matching[0]["proposal"]["observation_id"], after_id)
