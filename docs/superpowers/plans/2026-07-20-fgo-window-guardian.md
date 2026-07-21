# FGO Window Guardian and Recognition Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows-only dry-run application that selects one LDPlayer window, records an exact safe baseline, captures only its visible region, recognizes approved FGO/LDPlayer states, and pauses on every configured safety violation without generating gameplay input.

**Architecture:** A Python package wraps Win32 window metadata behind a testable protocol, captures the physical desktop region with MSS, maps the Android viewport, classifies states with OpenCV templates, and drives a strict safety state machine. A Tkinter UI exposes baseline, confidence, pause reason, preview, test-image mode, and emergency stop; no module capable of mouse or keyboard output is included.

**Tech Stack:** Python 3.14, pywin32 312, MSS 10.2.0, NumPy 2.5.1, OpenCV headless 5.0.0.93, Pillow 12.3.0, Tkinter, pytest 9.1.1, pytest-cov 7.1.0, PyInstaller 6.21.0.

## Global Constraints

- Work only inside `C:\Users\User\Documents\New project\fgo-supervised-assistant`.
- Target Windows with Python `>=3.14,<3.15`.
- Control only the one user-selected `C:\LDPlayer\LDPlayer14\dnplayer.exe` window titled `LDPlayer`.
- Expected Android profile is Tablet, `1920 x 1080`, DPI `280`, landscape.
- The inspected LDPlayer build is `14.0.15.0`; the inspected FGO package is `com.aniplex.fategrandorder.en` and game version is `2.90.2`.
- Never use root, ADB control, memory inspection, process injection, APK modification, packet interception, emulator tampering, or anti-detection behavior.
- Never automate authentication, CAPTCHA, purchases, Saint Quartz spending, summoning, account transfer, data deletion, Clear Cache, or communication with other players.
- Never use LDPlayer Synchronizer.
- Never capture or retain unrelated application content.
- Never OCR, display, or log the FGO account-ID area.
- Default state-confidence threshold is `0.92`.
- Default emergency-stop hotkey is `Ctrl+Shift+F12`.
- The first milestone must contain no functional gameplay-input path.
- Git metadata exists, but the `git` executable was unavailable during planning. Run commit steps only after Git becomes available; otherwise record each completed task and its test output in `docs/execution-log.md`.

## File Structure

```text
fgo-supervised-assistant/
â”œâ”€â”€ config/
â”‚   â””â”€â”€ default.json                 # Inspected environment and safety defaults
â”œâ”€â”€ docs/
â”‚   â”œâ”€â”€ execution-log.md             # Checkpoints when Git is unavailable
â”‚   â””â”€â”€ superpowers/
â”‚       â”œâ”€â”€ plans/
â”‚       â””â”€â”€ specs/
â”œâ”€â”€ packaging/
â”‚   â””â”€â”€ fgo_guardian.spec            # PyInstaller entry point and bundled assets
â”œâ”€â”€ scripts/
â”‚   â””â”€â”€ build.ps1                    # Reproducible Windows build
â”œâ”€â”€ src/fgo_guardian/
â”‚   â”œâ”€â”€ __init__.py                  # Package version
â”‚   â”œâ”€â”€ __main__.py                  # `python -m fgo_guardian`
â”‚   â”œâ”€â”€ app.py                       # Dependency composition and inspection loop
â”‚   â”œâ”€â”€ app_support.py               # Non-UI dependency bundle factory
â”‚   â”œâ”€â”€ audit_log.py                 # Redacted JSONL events and masked screenshots
â”‚   â”œâ”€â”€ config.py                    # Strict JSON configuration loader
â”‚   â”œâ”€â”€ dry_run_ui.py                # Tkinter UI with no output controls
â”‚   â”œâ”€â”€ hotkey.py                    # Win32 RegisterHotKey emergency stop
â”‚   â”œâ”€â”€ models.py                    # Shared immutable types and enums
â”‚   â”œâ”€â”€ screen_capture.py            # Safe pre/post-checked desktop capture
â”‚   â”œâ”€â”€ safety_controller.py         # State machine and repeated-state timeout
â”‚   â”œâ”€â”€ state_detector.py            # Template repository and confidence scoring
â”‚   â”œâ”€â”€ viewport_mapper.py           # LDPlayer chrome and 16:9 viewport mapping
â”‚   â”œâ”€â”€ win32_api.py                 # Testable pywin32 metadata adapter
â”‚   â”œâ”€â”€ window_guardian.py           # Unique target, baseline, focus, geometry, overlap
â”‚   â””â”€â”€ tools/
â”‚       â”œâ”€â”€ __init__.py
â”‚       â””â”€â”€ capture_reference.py     # Safe reference-crop acquisition
â”œâ”€â”€ src/fgo_guardian_entry.py        # PyInstaller-safe absolute entry point
â”œâ”€â”€ templates/
â”‚   â””â”€â”€ manifest.json                # State anchors and permanent privacy masks
â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ conftest.py
â”‚   â”œâ”€â”€ test_audit_log.py
â”‚   â”œâ”€â”€ test_config_models.py
â”‚   â”œâ”€â”€ test_hotkey.py
â”‚   â”œâ”€â”€ test_integration_loop.py
â”‚   â”œâ”€â”€ test_reference_capture.py
â”‚   â”œâ”€â”€ test_safety_controller.py
â”‚   â”œâ”€â”€ test_screen_capture.py
â”‚   â”œâ”€â”€ test_state_detector.py
â”‚   â”œâ”€â”€ test_viewport_mapper.py
â”‚   â”œâ”€â”€ test_win32_api.py
â”‚   â””â”€â”€ test_window_guardian.py
â”œâ”€â”€ README.md
â””â”€â”€ pyproject.toml
```

---

### Task 1: Package foundation, immutable models, and strict configuration

**Files:**
- Create: `pyproject.toml`
- Create: `config/default.json`
- Create: `src/fgo_guardian/__init__.py`
- Create: `src/fgo_guardian/models.py`
- Create: `src/fgo_guardian/config.py`
- Create: `tests/test_config_models.py`
- Create: `docs/execution-log.md`

**Interfaces:**
- Consumes: the approved values in `docs/superpowers/specs/2026-07-20-fgo-window-guardian-design.md`.
- Produces: `Rect`, `WindowSnapshot`, `Baseline`, `VisualState`, `DetectionResult`, `SafetyStatus`, `GuardReport`, and `AppConfig` used by every later task.

- [ ] **Step 1: Create project metadata and pin the verified package versions**

```toml
[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"

[project]
name = "fgo-window-guardian"
version = "0.1.0"
description = "Supervised LDPlayer window guardian and FGO recognition harness"
requires-python = ">=3.14,<3.15"
dependencies = [
  "mss==10.2.0",
  "numpy==2.5.1",
  "opencv-python-headless==5.0.0.93",
  "Pillow==12.3.0",
  "pywin32==312; platform_system == 'Windows'",
]

[project.optional-dependencies]
dev = [
  "pytest==9.1.1",
  "pytest-cov==7.1.0",
  "pyinstaller==6.21.0",
]

[project.scripts]
fgo-guardian = "fgo_guardian.app:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-ra --strict-markers"
testpaths = ["tests"]
```

Run:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Expected: all pinned packages install successfully under Python 3.14.

- [ ] **Step 2: Write failing model and configuration tests**

```python
from pathlib import Path

import pytest

from fgo_guardian.config import AppConfig
from fgo_guardian.models import Rect, SafetyStatus, VisualState, WindowSnapshot


def test_rect_geometry_and_intersection() -> None:
    left = Rect(-1920, 0, 0, 1040)
    blocker = Rect(-100, 50, 40, 200)
    separate = Rect(10, 10, 20, 20)
    assert left.width == 1920
    assert left.height == 1040
    assert left.intersects(blocker)
    assert not left.intersects(separate)


def test_window_snapshot_derives_logical_geometry_from_dpi() -> None:
    snapshot = WindowSnapshot(
        hwnd=1,
        pid=2,
        process_path=Path("dnplayer.exe"),
        title="LDPlayer",
        outer_rect=Rect(-1920, 0, 0, 1080),
        client_rect=Rect(-1920, 32, 0, 1080),
        monitor_name="DISPLAY2",
        monitor_rect=Rect(-1920, 0, 0, 1080),
        windows_dpi=192,
        visible=True,
        minimized=False,
        foreground=True,
    )
    assert snapshot.logical_outer_rect == Rect(-960, 0, 0, 540)


def test_default_config_matches_inspection() -> None:
    config = AppConfig.load(Path("config/default.json"))
    assert config.target_executable == Path(r"C:\LDPlayer\LDPlayer14\dnplayer.exe")
    assert config.ldplayer_version == "14.0.15.0"
    assert config.game_tab_title == "Fate/GO"
    assert config.game_package == "com.aniplex.fategrandorder.en"
    assert config.game_version == "2.90.2"
    assert config.android_resolution == (1920, 1080)
    assert config.android_dpi == 280
    assert config.confidence_threshold == pytest.approx(0.92)
    assert config.emergency_hotkey == "ctrl+shift+f12"
    assert VisualState.UNKNOWN.value == "UNKNOWN"
    assert SafetyStatus.DISARMED.value == "DISARMED"


def test_config_rejects_out_of_range_confidence(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        '{"target_executable":"C:\\\\LDPlayer\\\\LDPlayer14\\\\dnplayer.exe",'
        '"target_title":"LDPlayer","android_resolution":[1920,1080],'
        '"android_dpi":280,"orientation":"landscape",'
        '"confidence_threshold":1.2,"stale_timeout_seconds":10.0,'
        '"emergency_hotkey":"ctrl+shift+f12","capture_interval_ms":250}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="confidence_threshold"):
        AppConfig.load(path)
```

- [ ] **Step 3: Run the tests and verify the expected failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_config_models.py -v
```

Expected: collection fails because `fgo_guardian.config` and `fgo_guardian.models` do not exist.

- [ ] **Step 4: Implement the models and configuration loader**

```python
# src/fgo_guardian/models.py
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
```

```python
# src/fgo_guardian/config.py
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
```

```json
{
  "target_executable": "C:\\LDPlayer\\LDPlayer14\\dnplayer.exe",
  "target_title": "LDPlayer",
  "ldplayer_version": "14.0.15.0",
  "game_tab_title": "Fate/GO",
  "game_package": "com.aniplex.fategrandorder.en",
  "game_version": "2.90.2",
  "android_resolution": [1920, 1080],
  "android_dpi": 280,
  "orientation": "landscape",
  "confidence_thrÛo8öÚ$z{-®éÜj×7FFR"Â&WV—&VCÕG'VRÂ6†ö–6W3Õ·7FFRçfÇVRf÷"7FFR–âf—7VÅ7FFR–b7FFR—2æ÷Bf—7VÅ7FFRåTä´äõtåÒ¢'6W"æFEö&wVÖVçB‚"Ò×66÷R"Â&WV—&VCÕG'VRÂ6†ö–6W3Ò‚'f–Ww÷'B"Â'v–æF÷r"’¢'6W"æFEö&wVÖVçB‚"ÒÖ7&÷"Âæ&w3ÓBÂG—SÖfÆöBÂÖWFf#Ò‚$ÄTeB"Â%Dõ"Â%$”t…B"Â$$õEDôÒ"’Â&WV—&VCÕG'VR¢'6W"æFEö&wVÖVçB‚"ÒÖf—‡GW&R"ÂG—SÕF‚Â&WV—&VCÕG'VR¢'6W"æFEö&wVÖVçB‚"ÒÖfö7W2ÖFVÆ’×6V6öæG2"ÂG—SÖfÆöBÂFVfVÇCÓ2ã¢&w2Ò'6W"ç'6Uö&w2‚¢&ö÷BÒF‚…õöf–ÆUõò’ç&W6öÇfR‚’ç&VçG5³5Ð¢Öæ–fW7E÷F‚Ò&ö÷Bò'FV×ÆFW2"ò&Öæ–fW7Bæ§6öâ ¢'VæFÆRÒ7&VFUö'VæFÆR€¢&ö÷Bò&6öæf–r"ò&FVfVÇBæ§6öâ"À¢Öæ–fW7E÷F‚À¢&ö÷Bò&Æöw2"À¢6WB‚’À¢¢&–çB†b$fö7W2F†RVæö'7G'V7FVBÄEÆ–W"v–æF÷s²6GW&R7F'G2–â¶&w2æfö7W5öFVÆ•÷6V6öæG3¢ãgÒ6V6öæG2"¢F–ÖRç6ÆVW†&w2æfö7W5öFVÆ•÷6V6öæG2¢‡væBÒ'VæFÆRæwV&F–âç6VÆV7E÷Væ—VR‚¢&6VÆ–æRÒ'VæFÆRæwV&F–âæW7F&Æ—6…ö&6VÆ–æR†‡væB¢g&ÖRÒ'VæFÆRæ6öçG&öÆÆW"æ6GW&Ræ6GW&R†&6VÆ–æR¢Ö–ærÒ'VæFÆRæ6öçG&öÆÆW"æÖW"æÆö6FR†g&ÖRæ–ÖvR¢7&÷ÒGWÆR†&w2æ7&÷¢&V7BÒ€¢Ö–ærææ÷&ÖÆ—¦VE÷&V7B†7&÷¢–b&w2ç66÷RÓÒ'f–Ww÷'B ¢VÇ6Ræ÷&ÖÆ—¦VE÷&V7B†g&ÖRæ–ÖvRç6†U³ÒÂg&ÖRæ–ÖvRç6†U³ÒÂ7&÷¢¢6fU÷&VfW&Væ6R†g&ÖRæ–ÖvRÂ&V7BÂ&ö÷Bò'FV×ÆFW2"òb'¶&w2ææÖWÒçær"¢Ö6·2Ò&—f7•öÖ6·2†Öæ–fW7E÷F‚Âf—7VÅ7FFR†&w2ç7FFR’ÂÖ–ær¢f—‡GW&U÷F‚Ò&w2æf—‡GW&R–b&w2æf—‡GW&Ræ—5ö'6öÇWFR‚’VÇ6R&ö÷Bò&w2æf—‡GW&P¢6fUöf—‡GW&R†g&ÖRæ–ÖvRÂÖ6·2Âf—‡GW&U÷F‚¢&–çB†b'6fVBFV×ÆFW2÷¶&w2ææÖWÒçæræB¶f—‡GW&U÷F‚ç&VÆF—fU÷Fò‡&ö÷B—Ò"  ¦–bõöæÖUõòÓÒ%õöÖ–åõò# ¢Ö–â‚¦  ¤W‡÷6R6GW&VæBÖW&2&VBÖöæÇ’GG&–'WFW2Ç&VG’76–væVB'’6fWG”6öçG&öÆÆW"åõö–æ—Eõö²æòFF—F–öæÂ6öçG&öÆÆW"×WFF–öâ—2&WV—&VBà ¢Ò²Ò¢¥7FWC¢'VâF†R7&÷FW7B¢  ¥'Vã  ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—FW7BFW7G2÷FW7E÷&VfW&Væ6Uö6GW&Rç’×`¦  ¤W‡V7FVC¢276VBà ¢Ò²Ò¢¥7FWS¢7V—&RF†Rf—fR&VfW&Væ6W2VæFW"7WW'f—6–öâ¢  ¤f÷"V6‚6öÖÖæBÂf—'7BÆ6RÄEÆ–W"öâF†RæÖVB7FFRÂ¶VW—Bfö7W6VBæBVæö'7G'V7FVBÂæBFòæ÷BÖ÷fR÷"&W6—¦R—Bv†–ÆRF†R6öÖÖæB'Vç3  ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒfvõöwV&F–âçFööÇ2æ6GW&U÷&VfW&Væ6RÒÖæÖRfvõ÷F—FÆUöÆövòÒ×7FFRdtõõD•DÄRÒ×66÷Rf–Ww÷'BÒÖ7&÷ãbãRãƒBãs"ÒÖf—‡GW&RFW7G2öf—‡GW&W2ôdtõõD•DÄRçæp¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒfvõöwV&F–âçFööÇ2æ6GW&U÷&VfW&Væ6RÒÖæÖRfvõ÷GWF÷&–ÅöæW‡BÒ×7FFRdtõõEUDõ$”ÅôÔÒ×66÷Rf–Ww÷'BÒÖ7&÷ã3bã#BãcbãsBÒÖf—‡GW&RFW7G2öf—‡GW&W2ôdtõõEUDõ$”ÅôÔçæp¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒfvõöwV&F–âçFööÇ2æ6GW&U÷&VfW&Væ6RÒÖæÖRÆGÆ–W%÷6WGF–æw5÷F—FÆRÒ×7FFRÄEÄ”U%õ4UED”äu2Ò×66÷Rv–æF÷rÒÖ7&÷ã#‚ã‚ãC‚ã3"ÒÖf—‡GW&RFW7G2öf—‡GW&W2ôÄEÄ”U%õ4UED”äu2çæp¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒfvõöwV&F–âçFööÇ2æ6GW&U÷&VfW&Væ6RÒÖæÖR÷W&F–öå÷&V6÷&FW%÷F—FÆRÒ×7FFRÄEÄ”U%ôõU$D”ôåõ$T4õ$DU"Ò×66÷Rv–æF÷rÒÖ7&÷ã#‚ã#ãSRã3"ÒÖf—‡GW&RFW7G2öf—‡GW&W2ôÄEÄ”U%ôõU$D”ôåõ$T4õ$DU"çæp¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒfvõöwV&F–âçFööÇ2æ6GW&U÷&VfW&Væ6RÒÖæÖR¶W–ÖöVF—F÷%÷F—FÆRÒ×7FFRÄEÄ”U%ô´U”ÔôTD•Dõ"Ò×66÷Rv–æF÷rÒÖ7&÷ããã#Rã"ÒÖf—‡GW&RFW7G2öf—‡GW&W2ôÄEÄ”U%ô´U”ÔôTD•Dõ"çæp¦  ¤V6‚6öÖÖæBv—fW2F‡&VR×6V6öæBfö7W2†æFöfbÂF†Vâ6GW&W2öæÇ’gFW"F†R&6VÆ–æRæB÷fW&Æ6†V6·272âW‡V7FVC¢öæRÆ–æRæÖ–ær&÷F‚F†Ræ6†÷"æBf—‡GW&Râ–ç7V7BWfW'’æ6†÷"æBÖ6¶VBf—‡GW&S²FVÆWFRV—F†W"–ÖÖVF–FVÇ’–b—B6öçF–ç266÷VçB”BFW‡B÷"Vç&VÆFVBÆ–6F–öâ6öçFVçBâv–æF÷r×66÷VB7&÷2&R&VÆF—fRFòF†R6ö×ÆWFRÄEÆ–W"÷WFW"g&ÖRÂv†–ÆRf–Ww÷'B×66÷VB7&÷2&R&VÆF—fRöæÇ’FòF†RÖVBæG&ö–B–ÖvRà ¢Ò²Ò¢¥7FWc¢&Vv—7FW"F†R&Wf–WvVBæ6†÷'2–âF†RÖæ–fW7B¢  ¥&WÆ6RF†R7FFW6ö&¦V7B–âFV×ÆFW2öÖæ–fW7Bæ§6öæv—Fƒ  ¦§6öà§°¢$dtõõD•DÄR#¢°¢²&f–ÆR#¢&fvõ÷F—FÆUöÆövòçær"Â'66÷R#¢'f–Ww÷'B"Â'&Vv–öâ#¢³ãÂãÂã“Âãs…×Ð¢ÒÀ¢$dtõõEUDõ$”ÅôÔ#¢°¢²&f–ÆR#¢&fvõ÷GWF÷&–ÅöæW‡Bçær"Â'66÷R#¢'f–Ww÷'B"Â'&Vv–öâ#¢³ã#RÂãRÂãs‚Âãƒ%×Ð¢ÒÀ¢$ÄEÄ”U%õ4UED”äu2#¢°¢²&f–ÆR#¢&ÆGÆ–W%÷6WGF–æw5÷F—FÆRçær"Â'66÷R#¢'v–æF÷r"Â'&Vv–öâ#¢³ã#ÂãÂãƒÂãs×Ð¢ÒÀ¢$ÄEÄ”U%ôõU$D”ôåõ$T4õ$DU"#¢°¢²&f–ÆR#¢&÷W&F–öå÷&V6÷&FW%÷F—FÆRçær"Â'66÷R#¢'v–æF÷r"Â'&Vv–öâ#¢³ã#ÂãÂãƒÂãs×Ð¢ÒÀ¢$ÄEÄ”U%ô´U”ÔôTD•Dõ"#¢°¢²&f–ÆR#¢&¶W–ÖöVF—F÷%÷F—FÆRçær"Â'66÷R#¢'v–æF÷r"Â'&Vv–öâ#¢³ãÂãÂãÂã#U×Ð¢Ð§Ð¦  ¥&WF–âF†RW†—7F–ærfW'6–öææB&—f7•öÖ6·6f–VÆG2à ¢Ò²Ò¢¥7FWs¢FBÖ6¶VB&VÂÖg&ÖR6Æ76–f–6F–öâ76W'F–öç2æB'VâÆÂFWFV7F÷"FW7G2¢  ¤FB–×÷'B—FW7FÂg&öÒ”Â–×÷'B–ÖvVÂæBg&öÒfvõöwV&F–âçf–Ww÷'EöÖW"–×÷'Bf–Ww÷'DÖW&FòFW7G2÷FW7E÷7FFUöFWFV7F÷"ç–ÂF†VâFBF†—2&ÖWFW&—¦VBFW7Bâ—BW†W&6—6W2F†R&öGV7F–öâÖW"ÂÖæ–fW7B'6W"ÂFV×ÆFW2ÂæBF‡&W6†öÆBv–ç7BF†Rf—fR&Wf–WvVBgVÆÂÄEÆ–W"f—‡GW&W>(	Fæ÷BÖW&VÇ’F†R7&÷VBæ6†÷"f–ÆW2à ¦—F†öà¤—FW7BæÖ&²ç&ÖWG&—¦R€¢‚'7FFR"Â&f—‡GW&UöæÖR"’À¢°¢…f—7VÅ7FFRädtõõD•DÄRÂ$dtõõD•DÄRçær"’À¢…f—7VÅ7FFRädtõõEUDõ$”ÅôÔÂ$dtõõEUDõ$”ÅôÔçær"’À¢…f—7VÅ7FFRäÄEÄ”U%õ4UED”äu2Â$ÄEÄ”U%õ4UED”äu2çær"’À¢…f—7VÅ7FFRäÄEÄ”U%ôõU$D”ôåõ$T4õ$DU"Â$ÄEÄ”U%ôõU$D”ôåõ$T4õ$DU"çær"’À¢…f—7VÅ7FFRäÄEÄ”U%ô´U”ÔôTD•Dõ"Â$ÄEÄ”U%ô´U”ÔôTD•Dõ"çær"’À¢ÒÀ¢¦FVbFW7E÷&Wf–WvVEöf—‡GW&Uö6Æ76–f–W2‡7FFS¢f—7VÅ7FFRÂf—‡GW&UöæÖS¢7G"’ÓâæöæS ¢g&ÖRÒçæ6'&’„–ÖvRæ÷Vâ…F‚‚'FW7G2öf—‡GW&W2"’òf—‡GW&UöæÖR’æ6öçfW'B‚%$t""’¢Ö–ærÒf–Ww÷'DÖW"‚’æÆö6FR†g&ÖR¢&W÷6—F÷'’ÒFV×ÆFU&W÷6—F÷'’æÆöB…F‚‚'FV×ÆFW2öÖæ–fW7Bæ§6öâ"’¢&W7VÇBÒ7FFTFWFV7F÷"‡&W÷6—F÷'’ÂF‡&W6†öÆCÓã“"’æFWFV7B†g&ÖRÂÖ–ær¢76W'B&W7VÇBç7FFR—27FFP¢76W'B&W7VÇBæ6öæf–FVæ6RãÒã“ ¢f÷"Ö6²–â&W7VÇBæÖ6·3 ¢76W'BÖ–ærçf–Ww÷'BæÆVgBÃÒÖ6²æÆVgBÂÖ6²ç&–v‡BÃÒÖ–ærçf–Ww÷'Bç&–v‡@¢76W'BÖ–ærçf–Ww÷'BçF÷ÃÒÖ6²çF÷ÂÖ6²æ&÷GFöÒÃÒÖ–ærçf–Ww÷'Bæ&÷GFöÐ  ¦FVbFW7E÷Vç&VÆFVEö7&÷VEöæE÷66ÆVEög&ÖW5ö&U÷&V¦V7FVB‚’ÓâæöæS ¢÷&–v–æÂÒçæ6'&’„–ÖvRæ÷Vâ…F‚‚'FW7G2öf—‡GW&W2ôdtõõD•DÄRçær"’’æ6öçfW'B‚%$t""’¢&W÷6—F÷'’ÒFV×ÆFU&W÷6—F÷'’æÆöB…F‚‚'FV×ÆFW2öÖæ–fW7Bæ§6öâ"’¢f&–çG2Ò°¢çç¦W&÷5öÆ–¶R†÷&–v–æÂ’À¢÷&–v–æÅ³¢Â÷&–v–æÂç6†U³Òòò2¥ÒÀ¢7c"ç&W6—¦R†÷&–v–æÂÂæöæRÂgƒÓãsRÂg“ÓãsRÂ–çFW'öÆF–öãÖ7c"ä”åDU%ô$T’À¢Ð¢f÷"g&ÖR–âf&–çG3 ¢G'“ ¢Ö–ærÒf–Ww÷'DÖW"‚’æÆö6FR†g&ÖR¢W†6WBfÇVTW'&÷# ¢6öçF–çVP¢&W7VÇBÒ7FFTFWFV7F÷"‡&W÷6—F÷'’ÂF‡&W6†öÆCÓã“"’æFWFV7B†g&ÖRÂÖ–ær¢76W'B&W7VÇBç7FFR—2f—7VÅ7FFRåTä´äõtà¢76W'B&W7VÇBæ6öæf–FVæ6RÂã“   ¦FVbFW7Eöö66ÇVFVE÷F—FÆUöæ6†÷%ö—5÷&V¦V7FVB‚’ÓâæöæS ¢g&ÖRÒçæ6'&’„–ÖvRæ÷Vâ…F‚‚'FW7G2öf—‡GW&W2ôdtõõD•DÄRçær"’’æ6öçfW'B‚%$t""’¢ÖW"Òf–Ww÷'DÖW"‚¢Ö–ærÒÖW"æÆö6FR†g&ÖR¢&W÷6—F÷'’ÒFV×ÆFU&W÷6—F÷'’æÆöB…F‚‚'FV×ÆFW2öÖæ–fW7Bæ§6öâ"’¢FWFV7F÷"Ò7FFTFWFV7F÷"‡&W÷6—F÷'’ÂF‡&W6†öÆCÓã“"¢÷&–v–æÂÒFWFV7F÷"æFWFV7B†g&ÖRÂÖ–ær¢76W'B÷&–v–æÂç7FFR—2f—7VÅ7FFRädtõõD•DÄP¢ö66ÇVFVBÒg&ÖRæ6÷’‚¢f÷"æ6†÷"–â÷&–v–æÂææ6†÷'3 ¢ö66ÇVFVE¶æ6†÷"çF÷¦æ6†÷"æ&÷GFöÒÂæ6†÷"æÆVgC¦æ6†÷"ç&–v‡EÒÒ ¢&W7VÇBÒFWFV7F÷"æFWFV7B†ö66ÇVFVBÂÖW"æÆö6FR†ö66ÇVFVB’¢76W'B&W7VÇBç7FFR—2f—7VÅ7FFRåTä´äõtà¢76W'B&W7VÇBæ6öæf–FVæ6RÂã“ ¦  ¥'Vã  ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—FW7BFW7G2÷FW7E÷7FFUöFWFV7F÷"ç’FW7G2÷FW7E÷&VfW&Væ6Uö6GW&Rç’×`¦  ¤W‡V7FVC¢ÆÂFW7G272æBÆÂf—fRÖ6¶VBgVÆÂ×v–æF÷rf—‡GW&W26Æ76–g’B÷"&÷fRã“&à ¢Ò²Ò¢¥7FWƒ¢6öÖÖ—B&Wf–WvVBFV×ÆFW2æB7V—6—F–öâFööÂ¢  ¦÷vW'6†VÆÀ¦v—BFB7&2öfvõöwV&F–â÷FööÇ2FV×ÆFW2FW7G2÷FW7E÷&VfW&Væ6Uö6GW&Rç’FW7G2÷FW7E÷7FFUöFWFV7F÷"ç¦v—B6öÖÖ—BÖÒ&fVC¢FB7WW'f—6VBdtò&VfW&Væ6Ræ6†÷'2 ¦  ¤–bv—B—2Væf–Æ&ÆRÂVæBF6²’ÂF†R7&÷&Wf–Wr&W7VÇBÂæBF†RFW7B6÷VçBFòFö72öW†V7WF–öâÖÆöræÖFà ¢ÒÒÐ ¢222F6²¢gVÆÂfW&–f–6F–öâÂÆ—fRG'’'VâÂ$TDÔRÂæBv–æF÷w2W†V7WF&ÆP ¢¢¤f–ÆW3¢¢ ¢Ò7&VFS¢$TDÔRæÖF ¢Ò7&VFS¢67&—G2ö'V–ÆBç3 ¢Ò7&VFS¢6¶v–æröfvõöwV&F–âç7V6 ¢Ò6öç7VÖS¢7&2öfvõöwV&F–åöVçG'’ç– ¢ÒÖöF–g“¢Fö72öW†V7WF–öâÖÆöræÖF  ¢¢¤–çFW&f6W3¢¢ ¢Ò6öç7VÖW3¢F†R6ö×ÆWFVB6¶vRÂ&Wf–WvVBFV×ÆFW2ÂæB&÷fVBÄEÆ–W"&6VÆ–æRà¢Ò&öGV6W3¢6WGW–ç7G'V7F–öç2ÂfW&–f–VB6fWG’Wf–FVæ6RÂæBF—7BôdtòÕv–æF÷rÔwV&F–âôdtòÕv–æF÷rÔwV&F–âæW†Và ¢Ò²Ò¢¥7FW¢w&—FR6WGWÂ÷W&F–öâÂæB6fWG’–ç7G'V7F–öç2¢  ¤7&VFR$TDÔRæÖFv—F‚F†W6RW†7B6V7F–öç2æB6öÖÖæG3  ¦Ö&¶F÷và¢2dtòv–æF÷rwV&F–à ¥v–æF÷w2ÖöæÇ’G'’×'Vâ6fWG’æB&V6övæ—F–öâ†&æW72f÷"öæR7WW'f—6VBfFRôw&æB÷&FW"–ç7Fæ6R–âÄEÆ–W"à ¢226fWG’&÷VæF' ¥F†—2Ö–ÆW7FöæR6ææ÷B6Æ–6²÷"G—R–çFòÄEÆ–W"â—B6GW&W2öæÇ’&V6†V6¶VBf—6–&ÆRÄEÆ–W"&V7FævÆRÂÖ6·2F†Rdtò66÷VçBÔ”B&VÂæBW6W2öâfö7W2Æ÷72ÂÖ÷fVÖVçBÂ&W6—¦–ærÂE’6†ævW2ÂÖ–æ–Ö—¦F–öâÂ÷fW&ÆÂVæ¶æ÷vâ7FFW2Â6GW&Rf–ÇW&W2ÂæB&WVFVB×7FFRF–ÖV÷WBà ¢22–ç7V7FVB6öæf–wW&F–öà ¢ÒÄEÆ–W"BããRã ¢Òf—6–&ÆRV×VÆF÷"F—FÆRÄEÆ–W&²vÖRF"fFRôtö ¢Òdtò6¶vR6öÒææ—ÆW‚æfFVw&æF÷&FW"æVæÂfW'6–öâ"ã“ã ¢ÒæG&ö–B“#‚ƒÂE’#ƒÂÆæG66P¢Ò&ö÷BW&Ö—76–öâöf`¢ÒD"FV'Vvv–ær6öææV7F–öâF—6&ÆV@¢ÒWFöÖF–2&÷FF–öâ×W7B&Röfb&Vf÷&R–ç7V7F–öà¢Ò¶W–Ö66†VÖR7W7FöÖ—¦VÂv—F‚æòf—6–&ÆRdtò&–æF–æw0¢Ò÷W&F–öâ&V6÷&FW"f–Æ&ÆRÂæò67&—G2&W6VçBÂ&V6÷&F–ær†÷F¶W’c  ¥F†Röff–6–Â&V6÷&FW"—2æ÷BW6VB2F†R&–Ö'’6öçG&öÆÆW"&V6W6R&V6÷&FVB6WVVæ6R6ææ÷B'&æ6‚6fVÇ’öâ6†æv–ær7W÷'G2ÂFVÆ—2Âv&æ–æw2Â÷"VæW‡V7FVB67&VVç2âF†—2Ö–ÆW7FöæRFöW2æ÷B7F'B÷"&WÆ’&V6÷&FW"67&—G2à ¢226WGW  ¦÷vW'6†VÆÀ§—F†öâÖÒfVçbçfVç`¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—–ç7FÆÂÖR"å¶FWeÒ ¦  ¢22'VâFW7G0 ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—FW7BÒÖ6÷cÖfvõöwV&F–âÒÖ6÷b×&W÷'C×FW&ÒÖÖ—76–æp¦  ¢22'VâG'’ÖöFP ¥Æ6RÄEÆ–W"BF†RFW6—&VBf—†VB÷6—F–öâÂF—6&ÆRWFöÖF–2&÷FF–öâÂ¶VW—G2gVÆÂ÷WFW"g&ÖRVæö'7G'V7FVBÂæBÆ6RF†R76—7FçBv–æF÷r÷WG6–FRF†B&V7FævÆRÂF†Vâ'Vã  ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒfvõöwV&F–à¦  ¥W6R¢¤&Ò¢¢ÂF†Vâfö7W2ÄEÆ–W"GW&–ærF†RF‡&VR×6V6öæB†æFöfbÂFò&V6÷&BGvò–FVçF–6Â6fRvVöÖWG'’6×ÆW2âW6R¢¤–ç7V7B¢¢ÂF†Vâfö7W2ÄEÆ–W"GW&–ær—G2F‡&VR×6V6öæB†æFöfbÂFò7F'B67&VVç6†÷B&V6övæ—F–öââ7G&Âµ6†–gB´c&W&f÷&×2âVÖW&vVæ7’7F÷âF†RÆ–6F–öâæWfW"&W7VÖW2WFöÖF–6ÆÇ’gFW"W6Rà ¢22'V–ÆBW†V7WF&ÆP ¦÷vW'6†VÆÀ§÷vW'6†VÆÂÔW†V7WF–öåöÆ–7’'—72Ôf–ÆR67&—G5Æ'V–ÆBç3¦  ¥F†RW†V7WF&ÆR—2w&—GFVâFòF—7EÄdtòÕv–æF÷rÔwV&F–åÄdtòÕv–æF÷rÔwV&F–âæW†Và¦  ¢Ò²Ò¢¥7FW#¢7&VFRF†R”–ç7FÆÆW"'V–ÆBFVf–æ—F–öâ¢  ¦—F†öà¢26¶v–æröfvõöwV&F–âç7V0¦g&öÒF†Æ–"–×÷'BF€ §&ö÷BÒF‚…5T5D‚’ç&VçBç&Vç@ ¦ÒæÇ—6—2€¢·7G"‡&ö÷Bò'7&2"ò&fvõöwV&F–åöVçG'’ç’"•ÒÀ¢F†WƒÕ·7G"‡&ö÷Bò'7&2"•ÒÀ¢&–æ&–W3ÕµÒÀ¢FF3Õ°¢‡7G"‡&ö÷Bò&6öæf–r"’Â&6öæf–r"’À¢‡7G"‡&ö÷Bò'FV×ÆFW2"’Â'FV×ÆFW2"’À¢‡7G"‡&ö÷Bò'FW7G2"ò&f—‡GW&W2"’Â&f—‡GW&W2"’À¢ÒÀ¢†–FFVæ–×÷'G3Õ²&7c""Â&×72"Â%”Âå÷F¶–çFW%öf–æFW""Â'v–ã3&’"Â'v–ã3&6öâ"Â'v–ã3&wV’"Â'v–ã3'&ö6W72%ÒÀ¢†öö·7FƒÕµÒÀ¢'VçF–ÖUö†öö·3ÕµÒÀ¢W†6ÇVFW3ÕµÒÀ¢æö&6†—fSÔfÇ6RÀ¢§—¢Ò•¢†çW&R¦W†RÒU„R€¢—¢À¢ç67&—G2À¢µÒÀ¢W†6ÇVFUö&–æ&–W3ÕG'VRÀ¢æÖSÒ$dtòÕv–æF÷rÔwV&F–â"À¢FV'VsÔfÇ6RÀ¢&ö÷FÆöFW%ö–væ÷&U÷6–væÇ3ÔfÇ6RÀ¢7G&—ÔfÇ6RÀ¢WƒÕG'VRÀ¢6öç6öÆSÔfÇ6RÀ¢¦6öÆÂÒ4ôÄÄT5B€¢W†RÀ¢æ&–æ&–W2À¢æFF2À¢7G&—ÔfÇ6RÀ¢WƒÕG'VRÀ¢æÖSÒ$dtòÕv–æF÷rÔwV&F–â"À¢¦  ¦÷vW'6†VÆÀ¢267&—G2ö'V–ÆBç3¢DW'&÷$7F–öå&VfW&Væ6RÒu7F÷p¢E&ö¦V7E&ö÷BÒ7Æ—BÕF‚Õ&VçBE567&—E&ö÷@¢E—F†öâÒ¦ö–âÕF‚E&ö¦V7E&ö÷BrçfVçeÅ67&—G5Ç—F†öâæW†Rp¦–b‚Öæ÷B…FW7BÕF‚ÔÆ—FW&ÅF‚E—F†öâ’’°¢F‡&÷rt7&VFRçfVçbæB–ç7FÆÂF†RFWbFWVæFVæ6–W2&Vf÷&R'V–ÆF–ærâp§Ð¥W6‚ÔÆö6F–öâE&ö¦V7E&ö÷@§G'’°¢bE—F†öâÖÒ—FW7@¢bE—F†öâÖÒ”–ç7FÆÆW"ÒÖæö6öæf—&ÒÒÖ6ÆVâ6¶v–æuÆfvõöwV&F–âç7V0§Òf–æÆÇ’°¢÷ÔÆö6F–öà§Ð¦  ¢Ò²Ò¢¥7FW3¢'VâF†R6ö×ÆWFRWFöÖFVBfW&–f–6F–öâ¢  ¥'Vã  ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—FW7BÒÖ6÷cÖfvõöwV&F–âÒÖ6÷b×&W÷'C×FW&ÒÖÖ—76–æp¦  ¤W‡V7FVC¢WfW'’FW7B76W3²6÷fW&vR&W÷'G2æòVçFW7FVB'&æ6‚F†B6â7W&W726fWG’W6RÂw&—FRâVæÖ6¶VB67&VVç6†÷BÂ÷"'—72VÖW&vVæ7’7F÷à ¢Ò²Ò¢¥7FWC¢W&f÷&ÒF†RÆ—fRf—fRÖÖ–çWFRG'’'Vâ¢  ¥v—F‚ÄEÆ–W"öâF†R&÷fVBÖöæ—F÷"æBWFöÖF–2&÷FF–öâF—6&ÆVC  £â7F'BF†RT’æB&ÒF†RVæ—VRv–æF÷rà£"âfW&–g’Gvò–FVçF–6Â&6VÆ–æR6×ÆW2&R6†÷vâà£2â–ç7V7Bf÷"f—fRÖ–çWFW2v—F†÷WB–çWBà£BâÖ÷fRÄEÆ–W"'’BÆV7B—†VÇ2æBfW&–g’vVöÖWG'•ö6†ævVFW6W2à£Râ&W7F÷&RæB&RÖ&Ó²&W6—¦RÄEÆ–W"æBfW&–g’vVöÖWG'•ö6†ævVFW6W2à£bâ&W7F÷&RæB&RÖ&Ó²fö7W2æ÷F†W"v–æF÷rv—F†÷WB÷fW&Æ–æræBfW&–g’fö7W5öÆ÷7FW6W2à£râ&W7F÷&RæB&RÖ&Ó²÷fW&ÆÄEÆ–W"v—F‚æ÷F†W"v–æF÷ræBfW&–g’÷fW&ÆW6W2&Vf÷&R67&VVç6†÷B—26fVBà£‚â&W7F÷&RæB&RÖ&Ó²Ö–æ–Ö—¦RÄEÆ–W"æBfW&–g’Ö–æ–Ö—¦VFW6W2à£’â&W7F÷&RæB&RÖ&Ó²&W727G&Âµ6†–gB´c&æBfW&–g’TÔU$tTä5•õ5DõTFV'2–ÖÖVF–FVÇ’à£â6öæf—&ÒF†RÆ–6F–öâæWfW"vVæW&FVB6Æ–6²÷"¶W—7G&ö¶R–âÄEÆ–W"æBæWfW"&W7VÖVBWFöÖF–6ÆÇ’à ¥&V6÷&BV6‚ö'6W'fVB&W7VÇB–âFö72öW†V7WF–öâÖÆöræÖFà ¢Ò²Ò¢¥7FWS¢'V–ÆBæB6Öö¶R×FW7BF†RW†V7WF&ÆR¢  ¥'Vã  ¦÷vW'6†VÆÀ§÷vW'6†VÆÂÔW†V7WF–öåöÆ–7’'—72Ôf–ÆR67&—G5Æ'V–ÆBç3¢bråÆF—7EÄdtòÕv–æF÷rÔwV&F–åÄdtòÕv–æF÷rÔwV&F–âæW†Rp¦  ¤W‡V7FVC¢FW7G272&Vf÷&R6¶v–æs²F†RW†V7WF&ÆR÷Vç2–âD•4$ÔTF7FFRæBW†—G26ÆVæÇ’v—F†÷WBF÷V6†–ærÄEÆ–W"à ¢Ò²Ò¢¥7FWc¢6öÖÖ—BF†RfW&–f–VBÖ–ÆW7FöæR¢  ¦÷vW'6†VÆÀ¦v—BFB$TDÔRæÖB67&—G2ö'V–ÆBç36¶v–æröfvõöwV&F–âç7V27&2öfvõöwV&F–åöVçG'’ç’Fö72öW†V7WF–öâÖÆöræÖ@¦v—B6öÖÖ—BÖÒ&Fö73¢fW&–g’æB6¶vRdtòv–æF÷rwV&F–â ¦  ¤–bv—B—2Væf–Æ&ÆRÂVæBF6²ÂF†RgVÆÂ—FW7B7VÖÖ'’ÂÆ—fR6†V6¶Æ—7B&W7VÇG2ÂæBW†V7WF&ÆRF‚FòFö72öW†V7WF–öâÖÆöræÖFà ¢ÒÒÐ ¢22Æâ6ö×ÆWF–öâ6†V6° ¤&Vf÷&R6Æ–Ö–ær6ö×ÆWF–öâÂfW&–g’ÆÂöbF†RföÆÆ÷v–æs  ¢Ò—F†öâÖÒ—FW7F76W2à¢ÒF†RVæ—VRF&vWB—26VÆV7FVB'’W†7BW†V7WF&ÆRF‚æBF—FÆRà¢ÒF†R&6VÆ–æR6öçF–ç2‡—6–6ÂöÆöv–6ÂvVöÖWG'’ÂÖöæ—F÷"Âv–æF÷w2E’ÂæG&ö–B&W6öÇWF–öâÂæG&ö–BE’ÂæB÷&–VçFF–öâà¢Ò&RÒæB÷7BÖ6GW&R6†V6·2&V¦V7B÷fW&Æ&6W2à¢ÒVæ¶æ÷vâæB&VÆ÷rÖã“&7FFW2W6Rà¢Ò66÷VçBÔ”BæBFævW&÷W2F—FÆR×67&VVâ&Vv–öç2&R&Æ6¶VB÷WB&Vf÷&Rç’g&ÖRw&—FRà¢ÒVÖW&vVæ7’7F÷—2&Vv—7FW&VBvÆö&ÆÇ’æBFW7FVBà¢ÒF†R6¶vR6öçF–ç2æòÖ÷W6R÷"¶W–&ö&B÷WGWBÖöGVÆRà¢ÒF†Rf—fRÖÖ–çWFRÆ—fRG'’'Vâ—2&V6÷&FVB–âFö72öW†V7WF–öâÖÆöræÖFà¢ÒF†RW†V7WF&ÆRÆVæ6†W2–âD•4$ÔTF7FFRà 