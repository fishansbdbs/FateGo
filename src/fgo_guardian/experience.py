from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import RLock

import cv2
import numpy as np

from .agent_models import ActionKind, ScreenKind


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class CandidateProposal:
    proposed_screen: ScreenKind
    confidence: float
    evidence: tuple[str, ...]
    source_catalog_version: str

    def __post_init__(self) -> None:
        if self.proposed_screen is ScreenKind.UNKNOWN:
            raise ValueError("candidate proposal must name a screen family")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("candidate confidence must be between zero and one")
        if not self.evidence or not all(item for item in self.evidence):
            raise ValueError("candidate proposal requires evidence")
        if not self.source_catalog_version.strip():
            raise ValueError("candidate proposal requires a source catalog version")


@dataclass(frozen=True, slots=True)
class ExperienceCandidate:
    candidate_id: str
    dataset: str
    created_at: str
    image_path: str
    frame_sha256: str
    proposed_screen: ScreenKind
    confidence: float
    evidence: tuple[str, ...]
    source_catalog_version: str


@dataclass(frozen=True, slots=True)
class RegressionReport:
    passed_cases: int = 0
    failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.passed_cases < 0:
            raise ValueError("passed case count cannot be negative")


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    version_id: str
    parent_version_id: str | None
    created_at: str
    candidate_ids: tuple[str, ...]
    added_candidate_id: str
    regression_passed_cases: int
    regression_report_sha256: str


@dataclass(frozen=True, slots=True)
class TransitionExperience:
    transition_id: str
    created_at: str
    before_frame_sha256: str
    before_screen: ScreenKind
    action: ActionKind
    after_frame_sha256: str
    after_screen: ScreenKind
    verified: bool


class ExperienceStore:
    """Append-only quarantine, active-version, and verified-transition storage."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.quarantine_root = self.root / "quarantine"
        self.frames_root = self.quarantine_root / "frames"
        self.candidates_path = self.quarantine_root / "candidates.jsonl"
        self.versions_path = self.root / "active" / "versions.jsonl"
        self.transitions_path = self.root / "transitions.jsonl"
        self._lock = RLock()

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        try:
            items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid {path.name}") from error
        if not all(isinstance(item, dict) for item in items):
            raise ValueError(f"invalid {path.name}")
        return items

    @staticmethod
    def _append(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        existed = path.exists()
        size = path.stat().st_size if existed else 0
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            if path.exists():
                if existed:
                    with path.open("r+b") as handle:
                        handle.truncate(size)
                else:
                    path.unlink()
            raise

    @staticmethod
    def _candidate_from_dict(item: dict[str, object]) -> ExperienceCandidate:
        try:
            return ExperienceCandidate(
                candidate_id=str(item["candidate_id"]),
                dataset=str(item["dataset"]),
                created_at=str(item["created_at"]),
                image_path=str(item["image_path"]),
                frame_sha256=str(item["frame_sha256"]),
                proposed_screen=ScreenKind(str(item["proposed_screen"])),
                confidence=float(item["confidence"]),
                evidence=tuple(str(value) for value in item["evidence"]),
                source_catalog_version=str(item["source_catalog_version"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid candidates.jsonl") from error

    @staticmethod
    def _version_from_dict(item: dict[str, object]) -> DatasetVersion:
        try:
            return DatasetVersion(
                version_id=str(item["version_id"]),
                parent_version_id=None if item["parent_version_id"] is None else str(item["parent_version_id"]),
                created_at=str(item["created_at"]),
                candidate_ids=tuple(str(value) for value in item["candidate_ids"]),
                added_candidate_id=str(item["added_candidate_id"]),
                regression_passed_cases=int(item["regression_passed_cases"]),
                regression_report_sha256=str(item["regression_report_sha256"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid versions.jsonl") from error

    @staticmethod
    def _validate_png(payload: bytes) -> None:
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("redacted observation must be a valid PNG")
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            raise ValueError("redacted observation must be a valid PNG")

    def quarantine_unknown(
        self,
        redacted_png: bytes,
        proposal: CandidateProposal,
    ) -> ExperienceCandidate:
        self._validate_png(redacted_png)
        frame_digest = sha256(redacted_png).hexdigest()
        identity = {
            "frame_sha256": frame_digest,
            "proposed_screen": proposal.proposed_screen.value,
            "confidence": proposal.confidence,
            "evidence": proposal.evidence,
            "source_catalog_version": proposal.source_catalog_version,
        }
        candidate_id = f"candidate-{sha256(_canonical(identity)).hexdigest()[:24]}"
        with self._lock:
            existing = {
                item.candidate_id: item
                for item in map(self._candidate_from_dict, self._read_jsonl(self.candidates_path))
            }
            if candidate_id in existing:
                return existing[candidate_id]
            relative = Path("quarantine") / "frames" / f"{candidate_id}.png"
            candidate = ExperienceCandidate(
                candidate_id=candidate_id,
                dataset="quarantine",
                created_at=_now(),
                image_path=relative.as_posix(),
                frame_sha256=frame_digest,
                proposed_screen=proposal.proposed_screen,
                confidence=proposal.confidence,
                evidence=proposal.evidence,
                source_catalog_version=proposal.source_catalog_version,
            )
            self.frames_root.mkdir(parents=True, exist_ok=True)
            final_path = self.root / relative
            temporary_path = self.frames_root / f".{candidate_id}.tmp"
            try:
                with temporary_path.open("xb") as handle:
                    handle.write(redacted_png)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary_path.replace(final_path)
                payload = asdict(candidate)
                payload["proposed_screen"] = candidate.proposed_screen.value
                self._append(self.candidates_path, payload)
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                final_path.unlink(missing_ok=True)
                raise
            return candidate

    def active_version(self) -> DatasetVersion | None:
        with self._lock:
            versions = [self._version_from_dict(item) for item in self._read_jsonl(self.versions_path)]
            return versions[-1] if versions else None

    def active_examples(self) -> tuple[ExperienceCandidate, ...]:
        with self._lock:
            version = self.active_version()
            if version is None:
                return ()
            candidates = {
                item.candidate_id: item
                for item in map(self._candidate_from_dict, self._read_jsonl(self.candidates_path))
            }
            try:
                selected = tuple(candidates[candidate_id] for candidate_id in version.candidate_ids)
            except KeyError as error:
                raise ValueError("active dataset references a missing candidate") from error
            resolved_root = self.root.resolve()
            for candidate in selected:
                image_path = (self.root / candidate.image_path).resolve()
                if image_path != resolved_root and resolved_root not in image_path.parents:
                    raise ValueError("active dataset image escapes the experience root")
                try:
                    digest = sha256(image_path.read_bytes()).hexdigest()
                except OSError as error:
                    raise ValueError("active dataset image is unavailable") from error
                if digest != candidate.frame_sha256:
                    raise ValueError("active dataset image hash mismatch")
            return selected

    def promote(self, candidate_id: str, report: RegressionReport) -> DatasetVersion:
        if report.failures:
            raise PermissionError("regression suite did not pass")
        if report.passed_cases <= 0:
            raise PermissionError("regression report contains no passing cases")
        with self._lock:
            candidates = {
                item.candidate_id: item
                for item in map(self._candidate_from_dict, self._read_jsonl(self.candidates_path))
            }
            if candidate_id not in candidates:
                raise KeyError(candidate_id)
            parent = self.active_version()
            active_ids = parent.candidate_ids if parent is not None else ()
            if candidate_id in active_ids:
                raise PermissionError("candidate is already active")
            candidate_ids = active_ids + (candidate_id,)
            report_payload = asdict(report)
            report_digest = sha256(_canonical(report_payload)).hexdigest()
            sequence = len(self._read_jsonl(self.versions_path)) + 1
            identity = {
                "parent": None if parent is None else parent.version_id,
                "candidate_ids": candidate_ids,
                "report": report_digest,
            }
            version_id = f"dataset-{sequence:06d}-{sha256(_canonical(identity)).hexdigest()[:12]}"
            version = DatasetVersion(
                version_id=version_id,
                parent_version_id=None if parent is None else parent.version_id,
                created_at=_now(),
                candidate_ids=candidate_ids,
                added_candidate_id=candidate_id,
                regression_passed_cases=report.passed_cases,
                regression_report_sha256=report_digest,
            )
            self._append(self.versions_path, asdict(version))
            return version

    @staticmethod
    def _validate_digest(value: str) -> None:
        if not _SHA256.fullmatch(value):
            raise ValueError("frame digest must be lowercase SHA-256")

    def record_transition(
        self,
        *,
        before_frame_sha256: str,
        before_screen: ScreenKind,
        action: ActionKind,
        after_frame_sha256: str,
        after_screen: ScreenKind,
        verified: bool,
    ) -> TransitionExperience:
        if not verified:
            raise PermissionError("only verified transitions may enter experience storage")
        self._validate_digest(before_frame_sha256)
        self._validate_digest(after_frame_sha256)
        identity = {
            "before_frame_sha256": before_frame_sha256,
            "before_screen": before_screen.value,
            "action": action.value,
            "after_frame_sha256": after_frame_sha256,
            "after_screen": after_screen.value,
            "verified": True,
        }
        transition_id = f"transition-{sha256(_canonical(identity)).hexdigest()[:24]}"
        with self._lock:
            existing = self._read_jsonl(self.transitions_path)
            for item in existing:
                if item.get("transition_id") == transition_id:
                    return TransitionExperience(
                        transition_id=transition_id,
                        created_at=str(item["created_at"]),
                        before_frame_sha256=before_frame_sha256,
                        before_screen=before_screen,
                        action=action,
                        after_frame_sha256=after_frame_sha256,
                        after_screen=after_screen,
                        verified=True,
                    )
            transition = TransitionExperience(
                transition_id=transition_id,
                created_at=_now(),
                before_frame_sha256=before_frame_sha256,
                before_screen=before_screen,
                action=action,
                after_frame_sha256=after_frame_sha256,
                after_screen=after_screen,
                verified=True,
            )
            payload = asdict(transition)
            payload["before_screen"] = before_screen.value
            payload["action"] = action.value
            payload["after_screen"] = after_screen.value
            self._append(self.transitions_path, payload)
            return transition
