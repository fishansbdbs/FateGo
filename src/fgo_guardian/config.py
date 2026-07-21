from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    target_executable: Path
    target_title: str
    ldplayer_version: str
    game_tab_title: str
    game_package: str
    game_version: str
    android_resolution: tuple[int, int]
    android_dpi: int
    orientation: str
    confidence_threshold: float
    stale_timeout_seconds: float
    emergency_hotkey: str
    capture_interval_ms: int

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        confidence = float(raw["confidence_threshold"])
        if not 0.0 < confidence <= 1.0:
            raise ValueError("confidence_threshold must be in (0, 1]")
        resolution = tuple(int(value) for value in raw["android_resolution"])
        if len(resolution) != 2 or min(resolution) <= 0:
            raise ValueError("android_resolution must contain two positive integers")
        orientation = str(raw["orientation"]).lower()
        if orientation not in {"landscape", "portrait"}:
            raise ValueError("orientation must be landscape or portrait")
        return cls(
            target_executable=Path(raw["target_executable"]),
            target_title=str(raw["target_title"]),
            ldplayer_version=str(raw["ldplayer_version"]),
            game_tab_title=str(raw["game_tab_title"]),
            game_package=str(raw["game_package"]),
            game_version=str(raw["game_version"]),
            android_resolution=(resolution[0], resolution[1]),
            android_dpi=int(raw["android_dpi"]),
            orientation=orientation,
            confidence_threshold=confidence,
            stale_timeout_seconds=float(raw["stale_timeout_seconds"]),
            emergency_hotkey=str(raw["emergency_hotkey"]).lower(),
            capture_interval_ms=int(raw["capture_interval_ms"]),
        )
