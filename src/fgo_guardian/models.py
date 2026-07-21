from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class VisualState(str, Enum):
    FGO_TITLE = "FGO_TITLE"
    FGO_TUTORIAL_MAP = "FGO_TUTORIAL_MAP"
    LDPLAYER_SETTINGS = "LDPLAYER_SETTINGS"
    LDPLAYER_OPERATION_RECORDER = "LDPLAYER_OPERATION_RECORDER"
    LDPLAYER_KEYMAP_EDITOR = "LDPLAYER_KEYMAP_EDITOR"
    UNKNOWN = "UNKNOWN"


class SafetyStatus(str, Enum):
    DISARMED = "DISARMED"
    READY = "READY"
    INSPECTING = "INSPECTING"
    PAUSED = "PAUSED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"


@dataclass(frozen=True, slots=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right <= other.left
            or other.right <= self.left
            or self.bottom <= other.top
            or other.bottom <= self.top
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom


@dataclass(frozen=True, slots=True)
class WindowSnapshot:
    hwnd: int
    pid: int
    process_path: Path
    title: str
    outer_rect: Rect
    client_rect: Rect
    monitor_name: str
    monitor_rect: Rect
    windows_dpi: int
    visible: bool
    minimized: bool
    foreground: bool
    work_rect: Rect | None = None

    def geometry_signature(self) -> tuple[object, ...]:
        return (
            self.outer_rect,
            self.client_rect,
            self.monitor_name,
            self.monitor_rect,
            self.windows_dpi,
            self.work_rect,
        )

    @staticmethod
    def _to_logical(rect: Rect, dpi: int) -> Rect:
        scale = 96 / dpi
        return Rect(
            round(rect.left * scale),
            round(rect.top * scale),
            round(rect.right * scale),
            round(rect.bottom * scale),
        )

    @property
    def logical_outer_rect(self) -> Rect:
        return self._to_logical(self.outer_rect, self.windows_dpi)

    @property
    def logical_client_rect(self) -> Rect:
        return self._to_logical(self.client_rect, self.windows_dpi)


@dataclass(frozen=True, slots=True)
class Baseline:
    hwnd: int
    pid: int
    process_path: Path
    title: str
    geometry_signature: tuple[object, ...]
    android_resolution: tuple[int, int]
    android_dpi: int
    orientation: str
    logical_outer_rect: Rect | None = None
    logical_client_rect: Rect | None = None
    windows_dpi: int = 96


@dataclass(frozen=True, slots=True)
class DetectionResult:
    state: VisualState
    confidence: float
    anchors: tuple[Rect, ...] = ()
    masks: tuple[Rect, ...] = ()


@dataclass(frozen=True, slots=True)
class GuardReport:
    safe: bool
    reasons: tuple[str, ...]
    snapshot: WindowSnapshot | None
    blockers: tuple[int, ...] = ()
