from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4

import cv2
import numpy as np

from .agent_models import ResourceKind, ScreenKind
from .battle import BattleState
from .controller import AutomationController, StopReason
from .experience import CandidateProposal, ExperienceStore
from .models import Rect
from .viewport_mapper import ViewportMapping


class RecoveryKind(str, Enum):
    WAIT = "WAIT"
    RETRY = "RETRY"
    USE_APPLE = "USE_APPLE"
    PAUSE = "PAUSE"
    STOP = "STOP"


@dataclass(frozen=True, slots=True)
class RecoveryState:
    screen: ScreenKind
    frame_sha256: str
    confidence: float
    labels: tuple[str, ...]
    evidence: tuple[str, ...]
    battle: BattleState | None
    proposed_screen: ScreenKind | None
    current_ap: int | None
    quest_ap_cost: int | None
    available_apples: Mapping[ResourceKind, int]
    resource_targets: Mapping[ResourceKind, Rect]
    loading_seconds: float
    network_retry_count: int
    retry_target: Rect | None


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    kind: RecoveryKind
    reason: StopReason | None = None
    resource: ResourceKind = ResourceKind.NONE
    resource_cost: int = 0
    target: Rect | None = None
    incident_id: str | None = None
    candidate_id: str | None = None
    message: str = ""


class IncidentRedactor:
    """Local conservative redaction that preserves layout but hides common identity zones."""

    def __init__(
        self,
        masks: tuple[tuple[float, float, float, float], ...] = (
            (0.0, 0.0, 0.25, 0.16),
            (0.0, 0.76, 0.30, 1.0),
        ),
    ) -> None:
        self.masks = masks

    def redact(self, frame: np.ndarray, mapping: ViewportMapping) -> np.ndarray:
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError("incident frame must be uint8 RGB")
        height, width = frame.shape[:2]
        viewport = mapping.viewport
        if not (
            0 <= viewport.left < viewport.right <= width
            and 0 <= viewport.top < viewport.bottom <= height
        ):
            raise ValueError("incident viewport is outside the frame")
        safe = np.zeros_like(frame)
        safe[viewport.top : viewport.bottom, viewport.left : viewport.right] = frame[
            viewport.top : viewport.bottom,
            viewport.left : viewport.right,
        ]
        for values in self.masks:
            mask = mapping.normalized_rect(values)
            safe[mask.top : mask.bottom, mask.left : mask.right] = 0
        return safe

    def png(self, frame: np.ndarray, mapping: ViewportMapping) -> bytes:
        safe = self.redact(frame, mapping)
        try:
            encoded, output = cv2.imencode(".png", cv2.cvtColor(safe, cv2.COLOR_RGB2BGR))
            if not encoded:
                raise RuntimeError("failed to encode redacted incident screenshot")
            return output.tobytes()
        finally:
            safe.fill(0)


def _json_safe(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Rect):
        return value.as_tuple()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(_json_safe(key)): _json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value


class RecoveryManager:
    APPLE_PRIORITY = (
        ResourceKind.BRONZE_APPLE,
        ResourceKind.BLUE_APPLE,
        ResourceKind.SILVER_APPLE,
        ResourceKind.GOLDEN_APPLE,
    )
    PROHIBITED_PATTERNS = (
        "saintquartz",
        "commandspell",
        "summonticket",
        "paidcurrency",
    )

    def __init__(
        self,
        root: str | Path,
        *,
        controller: AutomationController,
        experience: ExperienceStore,
        redactor: IncidentRedactor,
        catalog_version: str = "fuyuki-m1-v1",
        loading_timeout_seconds: float = 30.0,
        maximum_network_retries: int = 2,
    ) -> None:
        self.root = Path(root)
        self.controller = controller
        self.experience = experience
        self.redactor = redactor
        self.catalog_version = catalog_version
        self.loading_timeout_seconds = loading_timeout_seconds
        self.maximum_network_retries = maximum_network_retries

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def _write_json(cls, path: Path, payload: object) -> None:
        cls._write_atomic(
            path,
            (json.dumps(_json_safe(payload), sort_keys=True, indent=2) + "\n").encode("utf-8"),
        )

    @staticmethod
    def _diagnose_defeat(state: RecoveryState) -> dict[str, object]:
        battle = state.battle
        if battle is None:
            return {
                "primary_cause": "unclassified_defeat",
                "explanation": "The defeat screen was recognized without a complete battle snapshot.",
                "enemy_hp_remaining": None,
            }
        living = [ally for ally in battle.allies if ally.alive and ally.hp > 0]
        enemy_hp = sum(max(0, enemy.hp) for enemy in battle.enemies if enemy.targetable)
        if not living:
            cause = "party_wiped"
            explanation = "All observed allies reached zero HP before the quest ended."
        elif battle.turn >= 15 and enemy_hp > 0:
            cause = "insufficient_damage"
            explanation = "The fight ran long while an enemy still had substantial HP."
        else:
            cause = "battle_strategy_insufficient"
            explanation = "The party could not complete the observed wave with the current strategy."
        return {
            "primary_cause": cause,
            "explanation": explanation,
            "wave": battle.wave,
            "total_waves": battle.total_waves,
            "turn": battle.turn,
            "enemy_hp_remaining": enemy_hp,
            "recommended_user_action": "Review party level, class advantage, and skill timing before resuming.",
        }

    def _save_defeat(
        self,
        state: RecoveryState,
        frame: np.ndarray,
        mapping: ViewportMapping,
    ) -> str:
        incident_id = f"defeat-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:10]}"
        incident = self.root / "incidents" / "defeats" / incident_id
        screenshot = self.redactor.png(frame, mapping)
        self._write_atomic(incident / "screenshot.png", screenshot)
        self._write_json(incident / "state.json", state)
        diagnosis = self._diagnose_defeat(state)
        self._write_json(incident / "diagnosis.json", diagnosis)
        event = {
            "incident_id": incident_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "frame_sha256": state.frame_sha256,
            "diagnosis": diagnosis,
        }
        events = self.root / "incidents" / "defeats.jsonl"
        events.parent.mkdir(parents=True, exist_ok=True)
        with events.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return incident_id

    @classmethod
    def _has_prohibited_prompt(cls, labels: tuple[str, ...]) -> bool:
        compact = tuple(re.sub(r"[^a-z0-9]", "", label.casefold()) for label in labels)
        return any(pattern in label for pattern in cls.PROHIBITED_PATTERNS for label in compact)

    def _unknown(
        self,
        state: RecoveryState,
        frame: np.ndarray,
        mapping: ViewportMapping,
    ) -> RecoveryDecision:
        proposal = CandidateProposal(
            proposed_screen=state.proposed_screen or ScreenKind.UNKNOWN,
            confidence=state.confidence,
            evidence=state.evidence or ("unclassified-new-screen",),
            source_catalog_version=self.catalog_version,
        )
        candidate = self.experience.quarantine_unknown(self.redactor.png(frame, mapping), proposal)
        self.controller.pause()
        return RecoveryDecision(
            RecoveryKind.PAUSE,
            StopReason.UNKNOWN_SCREEN,
            candidate_id=candidate.candidate_id,
            message="Unknown screen quarantined; no gameplay action was attempted.",
        )

    def _ap_refill(self, state: RecoveryState) -> RecoveryDecision:
        for resource in self.APPLE_PRIORITY:
            if state.available_apples.get(resource, 0) <= 0:
                continue
            target = state.resource_targets.get(resource)
            if target is None:
                self.controller.pause()
                return RecoveryDecision(
                    RecoveryKind.PAUSE,
                    StopReason.POLICY_REJECTED,
                    message=f"{resource.value} is available but its target was not verified.",
                )
            return RecoveryDecision(
                RecoveryKind.USE_APPLE,
                resource=resource,
                resource_cost=1,
                target=target,
                message=f"Use one {resource.value}; automatic Apple use is authorized.",
            )
        self.controller.stop(StopReason.POLICY_REJECTED)
        return RecoveryDecision(
            RecoveryKind.STOP,
            StopReason.POLICY_REJECTED,
            message="No verified Apple is available; premium AP restoration is forbidden.",
        )

    def _loading(self, state: RecoveryState) -> RecoveryDecision:
        if state.loading_seconds < self.loading_timeout_seconds:
            return RecoveryDecision(RecoveryKind.WAIT, message="Loading is within the bounded wait window.")
        network_error = any("network" in label.casefold() for label in state.labels)
        if (
            network_error
            and state.retry_target is not None
            and state.network_retry_count < self.maximum_network_retries
        ):
            return RecoveryDecision(
                RecoveryKind.RETRY,
                target=state.retry_target,
                message="Retry the verified network prompt once and recapture.",
            )
        self.controller.pause()
        return RecoveryDecision(
            RecoveryKind.PAUSE,
            StopReason.UNKNOWN_SCREEN,
            message="Loading or network recovery exceeded its bounded retry policy.",
        )

    def handle(
        self,
        state: RecoveryState,
        frame: np.ndarray,
        mapping: ViewportMapping,
    ) -> RecoveryDecision:
        if state.screen is ScreenKind.DEFEAT:
            incident_id = self._save_defeat(state, frame, mapping)
            self.controller.stop(StopReason.BATTLE_DEFEAT)
            return RecoveryDecision(
                RecoveryKind.STOP,
                StopReason.BATTLE_DEFEAT,
                incident_id=incident_id,
                message="Battle defeat captured and diagnosed; control returned to the user.",
            )
        if state.screen is ScreenKind.UNKNOWN:
            return self._unknown(state, frame, mapping)
        if self._has_prohibited_prompt(state.labels):
            self.controller.stop(StopReason.POLICY_REJECTED)
            return RecoveryDecision(
                RecoveryKind.STOP,
                StopReason.POLICY_REJECTED,
                message="A premium or limited-resource prompt is prohibited.",
            )
        if state.screen is ScreenKind.AP_REFILL:
            return self._ap_refill(state)
        if state.screen is ScreenKind.LOADING:
            return self._loading(state)
        self.controller.pause()
        return RecoveryDecision(
            RecoveryKind.PAUSE,
            StopReason.UNKNOWN_SCREEN,
            message=f"No recovery rule exists for {state.screen.value}.",
        )
