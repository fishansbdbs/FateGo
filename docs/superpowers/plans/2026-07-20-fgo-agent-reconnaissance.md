# FGO Agent Safety Shell and Tutorial Reconnaissance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a reviewed local safety shell, deterministic action-policy gate, masked observation recorder, replay simulator, and an authorized live recording of the current FGO tutorial that later perception, quest-planning, and battle-agent plans can use without replaying completed account progress.

**Architecture:** Reuse the reviewed Win32 identity/geometry guardian and interrupted-but-passing visible-capture layer. Add a normalized LDPlayer viewport, typed FGO observations/actions, a fail-closed Saint Quartz policy gate, privacy-aware recording, and CLI tools that authorize and record one tutorial action at a time. Codex Computer Use performs the actual supervised reconnaissance clicks only after the CLI policy gate returns an allow token; this phase does not add a reusable gameplay-input module.

**Tech Stack:** Windows 11, Python 3.14.6, pywin32 312, MSS 10.2.0, NumPy 2.5.1, OpenCV 5.0.0.93, Pillow 12.3.0, pytest 9.1.1, JSON/JSONL, SHA-256, Tk-free command-line tooling, bundled Computer Use for the live reconnaissance pass.

## Global Constraints

- Runtime gameplay must remain fully local; no cloud model or paid API is permitted.
- Control only the single exact `C:\LDPlayer\LDPlayer14\dnplayer.exe` window titled `LDPlayer`.
- Pause on target-count, identity, focus, visibility, minimization, geometry, monitor, work-area, Windows DPI, Android viewport, orientation, resolution, or overlap change.
- Capture only the safe visible LDPlayer outer frame, with guard checks before and after every capture.
- Use visible screenshots and standard Windows mouse/tap input only.
- Do not use root, ADB, memory inspection, APK modification, packet interception, process injection, emulator tampering, Synchronizer, or anti-detection techniques.
- Never automate login, account transfer, CAPTCHA, purchases, deletion, Clear Cache, or communication with other players.
- Never retain the title-screen account-ID region or unrelated-window content.
- Never spend Saint Quartz for AP, revival, summoning, inventory, purchases, or any other purpose.
- Mandatory zero-cost tutorial summons and forced tutorial formation/enhancement are allowed.
- Apples and Command Spells are allowed; optional/ticket/Quartz/paid summons are blocked.
- Always use `Skip` when visible; harmless mandatory dialogue choices may select any option.
- Every reconnaissance input uses a fresh observation and one policy-approved semantic action, followed immediately by re-observation.
- Git is unavailable on this machine. Replace every commit checkpoint with an entry in `docs/execution-log.md` containing task, command, result, and `commit: unavailable`.

## Scope Boundary

This is the first of five implementation plans derived from the approved autonomous-agent design:

1. **This plan:** safety shell, policy, recorder, simulator, and live tutorial reconnaissance.
2. Local perception and offline Atlas Academy knowledge snapshot.
3. FGO battle agent and support selection.
4. Quest discovery, graph planning, Do All Quests, and Farming modes.
5. End-to-end desktop UI, packaging, shadow run, and autonomous acceptance gates.

No later phase may weaken this plan's policy or privacy interfaces.

## File Structure

```text
fgo-supervised-assistant/
â”œâ”€â”€ config/
â”‚   â”œâ”€â”€ default.json
â”‚   â””â”€â”€ privacy.json
â”œâ”€â”€ data/recordings/.gitignore
â”œâ”€â”€ docs/
â”‚   â”œâ”€â”€ execution-log.md
â”‚   â”œâ”€â”€ reconnaissance/tutorial-fuyuki.md
â”‚   â””â”€â”€ superpowers/
â”œâ”€â”€ src/fgo_guardian/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ agent_models.py          # Typed screens, actions, observations, decisions
â”‚   â”œâ”€â”€ config.py
â”‚   â”œâ”€â”€ hotkey.py               # Global Ctrl+Shift+F12 stop signal
â”‚   â”œâ”€â”€ models.py
â”‚   â”œâ”€â”€ policy.py               # Deterministic prohibited-action gate
â”‚   â”œâ”€â”€ privacy.py              # Mask-before-write policy
â”‚   â”œâ”€â”€ recording.py            # Session observations/actions/transitions
â”‚   â”œâ”€â”€ replay.py               # Read-only recorded-session simulator
â”‚   â”œâ”€â”€ screen_capture.py
â”‚   â”œâ”€â”€ viewport_mapper.py
â”‚   â”œâ”€â”€ win32_api.py
â”‚   â”œâ”€â”€ window_guardian.py
â”‚   â””â”€â”€ tools/
â”‚       â”œâ”€â”€ __init__.py
â”‚       â”œâ”€â”€ authorize_action.py
â”‚       â”œâ”€â”€ capture_observation.py
â”‚       â”œâ”€â”€ complete_action.py
â”‚       â”œâ”€â”€ recon_sentinel.py
â”‚       â””â”€â”€ validate_recording.py
â””â”€â”€ tests/
    â”œâ”€â”€ test_agent_models_policy.py
    â”œâ”€â”€ test_foundation_contract.py
    â”œâ”€â”€ test_hotkey.py
    â”œâ”€â”€ test_privacy_recording.py
    â”œâ”€â”€ test_replay.py
    â”œâ”€â”€ test_recording_validation.py
    â”œâ”€â”€ test_screen_capture.py
    â””â”€â”€ test_viewport_mapper.py
```

---

### Task 1: Reconcile and freeze the reviewed safety foundation

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/fgo_guardian/__init__.py`
- Create: `.gitignore`
- Create: `tests/test_foundation_contract.py`
- Modify: `docs/execution-log.md`

**Interfaces:**
- Consumes: reviewed `WindowGuardian`, `PyWin32WindowApi`, and interrupted `SafeCapture` currently present in the workspace.
- Produces: a `0.2.0` package baseline with an explicit prohibition against gameplay-input modules and verified 18-test inherited safety behavior.

- [x] **Step 1: Record and verify the inherited baseline**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -v
```

Expected: `18 passed`, including all three `test_screen_capture.py` cases. If this exact baseline fails, stop and diagnose before modifying project metadata.

- [x] **Step 2: Write the failing scope-contract test**

```python
# tests/test_foundation_contract.py
from pathlib import Path
import tomllib


def test_project_identity_and_zero_input_boundary() -> None:
    metadata = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["name"] == "fgo-autonomous-agent"
    assert metadata["project"]["version"] == "0.2.0"
    modules = {path.stem for path in Path("src/fgo_guardian").glob("*.py")}
    assert "input_controller" not in modules
    assert "mouse_controller" not in modules
    assert "gameplay_executor" not in modules


def test_process_access_remains_metadata_only() -> None:
    source = Path("src/fgo_guardian/win32_api.py").read_text(encoding="utf-8")
    assert "PROCESS_QUERY_LIMITED_INFORMATION" in source
    assert "PROCESS_VM_READ" not in source
    assert "GetModuleFileNameEx" not in source
```

- [x] **Step 3: Run the scope test and verify the project-identity assertion fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_foundation_contract.py -v
```

Expected: the metadata-only test passes and the identity test fails because the project is still named `fgo-window-guardian` at `0.1.0`.

- [x] **Step 4: Update project identity and ignore generated artifacts**

Replace the `[project]` identity lines in `pyproject.toml` with:

```toml
name = "fgo-autonomous-agent"
version = "0.2.0"
description = "Standalone visible-screen Fate/Grand Order quest agent for one LDPlayer window"
```

Keep every dependency pin and Python version constraint unchanged. Replace `src/fgo_guardian/__init__.py` with:

```python
__version__ = "0.2.0"
```

Create `.gitignore`:

```gitignore
.venv/
.pytest_cache/
**/__pycache__/
*.egg-info/
build/
dist/
data/recordings/*
!data/recordings/.gitignore
```

Create `data/recordings/.gitignore`:

```gitignore
*
!.gitignore
```

- [x] **Step 5: Run focused and full tests**

Run:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest tests/test_foundation_contract.py -v
.venv\Scripts\python.exe -m pytest -v
.venv\Scripts\python.exe -m compileall -q src
```

Expected: `2 passed` focused, `20 passed` full, and compileall exits `0` without output.

- [x] **Step 6: Checkpoint Task 1**

Append to `docs/execution-log.md`: inherited baseline result, focused/full commands, exact counts, compile result, and `commit: unavailable`.

---

### Task 2: Map the visible LDPlayer Android viewport

**Files:**
- Create: `src/fgo_guardian/viewport_mapper.py`
- Create: `tests/test_viewport_mapper.py`
- Modify: `docs/execution-log.md`

**Interfaces:**
- Consumes: a safe RGB NumPy frame of the complete LDPlayer outer rectangle and `Rect`.
- Produces: `ViewportMapping.crop()`, `ViewportMapping.normalized_rect()`, `ViewportMapping.normalized_target()`, and `ViewportMapper.locate()`.

- [x] **Step 1: Write failing synthetic viewport tests**

```python
# tests/test_viewport_mapper.py
import cv2
import numpy as np
import pytest

from fgo_guardian.models import Rect
from fgo_guardian.viewport_mapper import ViewportMapper


def synthetic_ldplayer(titlebar_bottom: int = 40, toolbar_left: int = 1825, chrome_level: int = 230) -> np.ndarray:
    image = np.full((1040, 1920, 3), 28, dtype=np.uint8)
    image[titlebar_bottom:1040, 55:toolbar_left] = (70, 45, 25)
    image[titlebar_bottom:1040, toolbar_left:1920] = (36, 36, 40)
    chrome = (chrome_level, chrome_level, chrome_level)
    cv2.line(image, (0, titlebar_bottom - 1), (1919, titlebar_bottom - 1), chrome, 2)
    cv2.line(image, (toolbar_left - 1, titlebar_bottom), (toolbar_left - 1, 1039), chrome, 2)
    return image


def test_locate_returns_landscape_16_by_9_viewport() -> None:
    mapping = ViewportMapper().locate(synthetic_ldplayer())
    assert abs(mapping.viewport.width / mapping.viewport.height - 16 / 9) < 0.01
    assert mapping.titlebar_bottom in range(35, 46)
    assert mapping.toolbar_left in range(1818, 1832)
    assert mapping.viewport.left >= 0
    assert mapping.viewport.right <= mapping.toolbar_left


def test_normalized_geometry_is_bounded_by_viewport() -> None:
    mapping = ViewportMapper().locate(synthetic_ldplayer())
    rect = mapping.normalized_rect((0.25, 0.25, 0.75, 0.75))
    assert mapping.viewport.left <= rect.left < rect.right <= mapping.viewport.right
    assert mapping.viewport.top <= rect.top < rect.bottom <= mapping.viewport.bottom
    assert mapping.normalized_target(rect) == pytest.approx(
        (0.25, 0.25, 0.75, 0.75),
        abs=1 / min(mapping.viewport.width, mapping.viewport.height),
    )


def test_locate_rejects_frame_too_small_for_fgo() -> None:
    tiny = np.zeros((200, 300, 3), dtype=np.uint8)
    try:
        ViewportMapper().locate(tiny)
    except ValueError as error:
        assert "too small" in str(error)
    else:
        raise AssertionError("tiny frame was accepted")


def test_locate_rejects_large_frame_without_credible_chrome_edges() -> None:
    uniform = np.zeros((1040, 1920, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="too weak"):
        ViewportMapper().locate(uniform)


def test_locate_validates_in_game_distractor_structure() -> None:
    image = synthetic_ldplayer(chrome_level=120)
    cv2.line(image, (0, 110), (1919, 110), (255, 255, 255), 2)
    mapping = ViewportMapper().locate(image)
    assert mapping.titlebar_bottom in range(35, 46)

    ambiguous = synthetic_ldplayer()
    ambiguous[114:1040] = np.clip(ambiguous[114:1040].astype(int) + 24, 0, 255).astype(np.uint8)
    cv2.line(ambiguous, (0, 110), (1919, 110), (230, 230, 230), 2)
    with pytest.raises(ValueError, match="ambiguous"):
        ViewportMapper().locate(ambiguous)


def test_locate_accepts_shifted_but_unambiguous_chrome() -> None:
    mapping = ViewportMapper().locate(synthetic_ldplayer(titlebar_bottom=100, toolbar_left=1700))
    assert mapping.titlebar_bottom in range(95, 106)
    assert mapping.toolbar_left in range(1693, 1707)
```

- [x] **Step 2: Run the tests and verify import failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_viewport_mapper.py -v
```

Expected: collection fails because `fgo_guardian.viewport_mapper` does not exist.

- [x] **Step 3: Implement the viewport mapper**

```python
# src/fgo_guardian/viewport_mapper.py
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .models import Rect


@dataclass(frozen=True, slots=True)
class ViewportMapping:
    viewport: Rect
    titlebar_bottom: int
    toolbar_left: int

    @property
    def signature(self) -> tuple[Rect, int, int]:
        return self.viewport, self.titlebar_bottom, self.toolbar_left

    def crop(self, image: np.ndarray) -> np.ndarray:
        return image[self.viewport.top:self.viewport.bottom, self.viewport.left:self.viewport.right]

    def normalized_rect(self, values: tuple[float, float, float, float]) -> Rect:
        left, top, right, bottom = values
        if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
            raise ValueError("normalized rectangle must satisfy 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
        return Rect(
            self.viewport.left + round(left * self.viewport.width),
            self.viewport.top + round(top * self.viewport.height),
            self.viewport.left + round(right * self.viewport.width),
            self.viewport.top + round(bottom * self.viewport.height),
        )

    def normalized_target(self, rect: Rect) -> tuple[float, float, float, float]:
        if not (
            self.viewport.left <= rect.left < rect.right <= self.viewport.right
            and self.viewport.top <= rect.top < rect.bottom <= self.viewport.bottom
        ):
            raise ValueError("target rectangle must be inside the Android viewport")
        return (
            (rect.left - self.viewport.left) / self.viewport.width,
            (rect.top - self.viewport.top) / self.viewport.height,
            (rect.right - self.viewport.left) / self.viewport.width,
            (rect.bottom - self.viewport.top) / self.viewport.height,
        )


class ViewportMapper:
    TARGET_ASPECT = 16 / 9
    MIN_WIDTH = 640
    MIN_HEIGHT = 360
    MIN_EDGE_STRENGTH = 20.0
    MIN_SUSTAINED_CONTRAST = 5.0
    EDGE_EXCLUSION_RADIUS = 6

    @staticmethod
    def _sustained_contrast(image: np.ndarray, index: int, axis: int) -> float:
        gap = 4
        width = 8
        if axis == 0:
            before = image[max(0, index - gap - width):max(0, index - gap)]
            after = image[min(image.shape[0], index + gap):min(image.shape[0], index + gap + width)]
        else:
            before = image[:, max(0, index - gap - width):max(0, index - gap)]
            after = image[:, min(image.shape[1], index + gap):min(image.shape[1], index + gap + width)]
        if before.size == 0 or after.size == 0:
            return 0.0
        return float(np.linalg.norm(before.mean(axis=(0, 1)) - after.mean(axis=(0, 1))))

    def _credible_edge(
        self,
        profile: np.ndÛŽøÚÚ$z{-®éÜj×FR6–væGW&W2v—F†÷WBg&ÖRFFæB–æFWVæFVçFÇ’&Wf–Wr&Vf÷&R&W7VÖ–ærà¢Ò–×ÆVÖVçBæB–æFWVæFVçFÇ’&Wf–Wr&÷F‚Æ—fR×7F'GWf—†W2ÇW2F†R7G&VæwF†VæVBW6R&VÖVF–F–öâ&Vf÷&R&6†—f–ærÂ6ÆV&–ærÂ÷"&WÆ6–ærç’W†—7F–ær5DõTBÆF6‚âF†Vâ&W'VâF†RÆ—fRöæR×6†÷B&6VÆ–æRõ6fT6GW&Rõf–Ww÷'DÖ–ærF–væ÷7F–2&Vf÷&R&W7VÖ–ærF†R6ÖRVF—FVB6W76–öâà ¢¢¤f–ÆW3¢¢ ¢Ò7&VFRF‡&÷Vv‚F†R&V6÷&FW#¢FF÷&V6÷&F–æw2÷GWF÷&–ÂÖgW—V¶’öö'6W'fF–öç2æ§6öæÆ ¢Ò7&VFRF‡&÷Vv‚F†R&V6÷&FW#¢FF÷&V6÷&F–æw2÷GWF÷&–ÂÖgW—V¶’ö7F–öç2æ§6öæÆ ¢Ò7&VFRF‡&÷Vv‚F†R&V6÷&FW#¢FF÷&V6÷&F–æw2÷GWF÷&–ÂÖgW—V¶’÷G&ç6—F–öç2æ§6öæÆ ¢Ò7&VFRÖ6¶VBg&ÖW2VæFW#¢FF÷&V6÷&F–æw2÷GWF÷&–ÂÖgW—V¶’ög&ÖW2ö ¢Ò7&VFS¢Fö72÷&V6öææ—76æ6R÷GWF÷&–ÂÖgW—V¶’æÖF ¢ÒÖöF–g“¢Fö72öW†V7WF–öâÖÆöræÖF  ¢¢¤–çFW&f6W3¢¢ ¢Ò6öç7VÖW3¢ÆÂ&Wf–WvVBF6·2ÓbæBF†R'VæFÆVB6ö×WFW"W6RF&vWB×v–æF÷rv÷&¶fÆ÷rà¢Ò&öGV6W3¢öæR&WÆ–&ÆRÂöÆ–7’ÖVF—FVBGWF÷&–Â&V6÷&F–ær6öçF–æ–æröæÇ’Ö6¶VBÄEÆ–W"g&ÖW2æB6VÖçF–2G&ç6—F–öç2à ¢Ò²Ò¢¥7FW¢fW&–g’F†RÆ—fR&V6öæF—F–öç2v—F†÷WB–çWB¢  ¥W6R6ö×WFW"W6RFòÆ—7BÆ–6F–öç2â&WV—&RW†7FÇ’öæR&WGW&æVBv–æF÷rv†÷6R—23¥ÄÄEÆ–W%ÄÄEÆ–W#EÆFçÆ–W"æW†VæBF—FÆR—2ÄEÆ–W&â7F—fFRF†B&WGW&æVBv–æF÷rÂ6GW&Rg&W6‚67&VVç6†÷BÂæBfW&–g’F†Rf—6–&ÆRvÖR—27F–ÆÂöâF†RgW—V¶’GWF÷&–Â÷"æ÷F†W"6ÆV&Ç’6Æ76–f–&ÆRWF†÷&—¦VBGWF÷&–Â67&VVâà ¥7F÷–b6V6öæBÄEÆ–W"v–æF÷rW†—7G2ÂF†RFW6·F÷—2Æö6¶VBÂF†Rv–æF÷r—2ö'7G'V7FVBÂF†R66÷VçBF—FÆR67&VVâ—2f—6–&ÆRv—F†÷WBfW&–f–VBÖ6²Â÷"ç’WF†VçF–6F–öâ÷6V7W&—G’&ö×BV'2à ¢Ò²Ò¢¥7FW#¢7F'BF†RVÖW&vVæ7’6VçF–æVÂ–â†–FFVâ&ö6W72¢  ¥'Vã  ¦÷vW'6†VÆÀ¢G&ö¦V7E&ö÷BÒt3¥ÅW6W'5ÅW6W%ÄFö7VÖVçG5ÄæWr&ö¦V7EÆfvò×7WW'f—6VBÖ76—7FçBp¢G—F†öäW†RÒ¦ö–âÕF‚G&ö¦V7E&ö÷BrçfVçeÅ67&—G5Ç—F†öâæW†Rp¥7F'BÕ&ö6W72Ôf–ÆUF‚G—F†öäW†RÔ&wVÖVçDÆ—7BrÖÒrÂvfvõöwV&F–âçFööÇ2ç&V6öå÷6VçF–æVÂrÂrÒ×6W76–öârÂwGWF÷&–ÂÖgW—V¶’rÕv÷&¶–ætF—&V7F÷'’G&ö¦V7E&ö÷BÕv–æF÷u7G–ÆR†–FFVà¦  ¤W‡V7FVC¢F†R&ö6W72W7F&Æ—6†W2F†RVæ—VRGvò×6×ÆRÄEÆ–W"&6VÆ–æRæBæG&ö–Bf–Ww÷'DÖ–ærç6–væGW&VÂöÆÇ2vVöÖWG'’öfö7W2ö÷fW&ÆÇW2f—6–&ÆRf–Ww÷'B×6–væGW&R6fWG’WfW'’#S×2Â&Vv—7FW'27G&Âµ6†–gB´c&ÂæB7&VFW2æò5DõTBÆF6‚VçF–ÂF†R†÷F¶W’÷"wV&F–â÷f–Ww÷'Bf–öÆF–öâG&–vvW'2à ¢Ò²Ò¢¥7FW3¢W†V7WFRF†R6–ævÆRÖ7F–öâ&V6öææ—76æ6RÆö÷¢  ¤f÷"WfW'’GWF÷&–ÂFV6—6–öâÂW&f÷&ÒF†—2W†7B6WVVæ6Rv—F†÷WB&F6†–ær6Æ–6·3  £âö'6W'fRF†R7W'&VçBÄEÆ–W"67&VVç6†÷BF‡&÷Vv‚6ö×WFW"W6Rà£"â76–vâöæRW†7B67&VVä¶–æF÷F†W"F†âTä´äõtæâ–bæòW†7B¶–æBÆ–W2Â7F÷²Fòæ÷BW'6—7B÷"6Æ–6²à£2â'Vâ6GW&Uöö'6W'fF–öæv—F‚F†R67&VVâÂ6öæf–FVæ6RãÓã“&ÂæBWfW'’f—6–&ÆRFV6—6–öâÆ&VÂà£Bâ6öçfW'BF†R–çFVæFVBF&vWB&V7FævÆRg&öÒF†R7W'&VçBæG&ö–Bf–Ww÷'BFòf÷W"æ÷&ÖÆ—¦VBfÇVW2à£Râ'VâWF†÷&—¦Uö7F–öæv—F‚F†RW†7B6VÖçF–27F–öä¶–æFÂ&W6÷W&6RÂ&W6÷W&6R6÷7BÂÖæFF÷'’fÆrÂÆ&VÇ2ÂæBæ÷&ÖÆ—¦VBF&vWBà£bâ7F÷–bF†R6öÖÖæBFöW2æ÷B&WGW&âöæRÆÆ÷rFö¶Vâà£râ&RÖö'6W'fR6ö×WFW"W6RFòVç7W&RF†R67&VVç6†÷BæBF&vWBF–Bæ÷B6†ævRà£‚âW&f÷&ÒW†7FÇ’öæR6Æ–6²–âF†R6VÆV7FVBÄEÆ–W"v–æF÷rW6–ærF†R7W'&VçB67&VVç6†÷B”Bà£’â&Vg&W6‚6ö×WFW"W6R–ÖÖVF–FVÇ’à£â&WGW&âFò7FW"Â6GW&RF†R&W7VÇF–ærö'6W'fF–öâÂæB'Vâ6ö×ÆWFUö7F–öæv—F‚F†R&–÷"Fö¶VâæBæWrö'6W'fF–öâ”Bà ¥W6RF†RföÆÆ÷v–ærÖæFF÷'’6Æ76–f–6F–öç3  §Âf—6–&ÆR6—GVF–öâÂ67&VVä¶–æBÂ7F–öä¶–æBÂ&W6÷W&6RòÖæFF÷'’'VÆRÀ§ÂÒÒ×ÂÒÒ×ÂÒÒ×ÂÒÒ×À§ÂgW—V¶’†–v†Æ–v‡FVBæöFRÂEUDõ$”ÅôÔÂ4TÄT5EõTU5FÂäôäVÂæ÷BÖæFF÷'’À§Âf÷&6VBGWF÷&–Â&ö×Bö6öçF–çVF–öâÂEUDõ$”Åõ$ôÕFÂEdä4UõEUDõ$”ÆÂäôäVÂÖæFF÷'’À§Â7F÷'’v—F‚6¶—Â5Dõ%–Â4´•õ5Dõ%–ÂäôäVÀ§Â6¶—6öæf—&ÖF–öâÂ4´•ô4ôäd•$ÖÂ4ôäd•$Õõ4´•ÂäôäVÀ§Â&WV—&VBF–ÆöwVR6†ö–6RÂD”ÄôuTUô4„ô”4VÂ4TÄT5EôD”ÄôuTVÂäôäVÂÖæFF÷'’À§Â7W÷'BÆ—7BÂ5Uõ%Eõ4TÄT5FÂ4TÄT5Eõ5Uõ%FÂäôäVÀ§Â'G’6öæf—&ÖF–öâÂ%E•ô4ôäd•$ÖÂ4ôäd•$Õõ%E–÷"5D%EõTU5FÂäôäVÀ§Â&GFÆRF7F–6Â†6RÂ$EDÄVÂU4Uõ4´”ÄÆÂ4TÄT5EõD$tUFÂ÷"ED4¶ÂäôäVÀ§Â&GFÆR6&B†6RÂ$EDÄVÂ4TÄT5Eô4ôÔÔäEô4$FÂäôäVÀ§Âf÷&6VB÷"6†÷6Vâå6&BÂ$EDÄVÂ4TÄT5Eôäô$ÄUõ„åD4ÖÂäôäVÀ§ÂVW7B6ÆV"÷&W7VÇBÂTU5Eõ$U5TÅFÂ4ôÄÄT5Eõ$U5TÅFÂäôäVÀ§ÂÖæFF÷'’g&VR7VÖÖöâÂEUDõ$”Åõ5TÔÔôæÂEUDõ$”Åôe$TUõ5TÔÔôæÂäôäVÂ6÷7BÂÖæFF÷'’À§ÂÖæFF÷'’7VÖÖöâ×&W7VÇB6öçF–çVF–öâÂEUDõ$”Åõ5TÔÔôæÂEdä4UõEUDõ$”ÆÂäôäVÂÖæFF÷'’À§Âf÷&6VBf÷&ÖF–öâöVæ†æ6VÖVçBÂEUDõ$”Åôdõ$ÔD”ôæÂEUDõ$”Åôdõ$ÔD”ôæ÷"Edä4UõEUDõ$”ÆÂäôäVÂÖæFF÷'’À ¤Çv—26†ö÷6R6¶—v†Vâf—6–&ÆRâöâÖæFF÷'’g&VR7VÖÖöâÂf—7VÆÇ’fW&–g’6÷7BæBGWF÷&–Â6ö×VÇ6–öâ&Vf÷&RWF†÷&—¦F–öââ–bç’6–çBV'G¢Ö÷VçBÂ÷F–öæÂ7VÖÖöâÂW&6†6RÂ66÷VçBÂFVÆWF–öâÂ6ÆV"66†RÂ–çfVçF÷'’ÖF—7÷6ÂÂ4D4„Â÷"Vç&VÆFVBv–æF÷rV'2Â&W727G&Âµ6†–gB´c&æB7F÷à ¢Ò²Ò¢¥7FWC¢7F÷BF†RGWF÷&–Â6ö×ÆWF–öâ&÷VæF'’¢  ¥F†R&V6öææ—76æ6R72—26ö×ÆWFRv†VâF†RvÖR&WGW&ç2Fò7F&ÆRFW&Ö–æÂôgW—V¶’ÖgFW"F†RÖæFF÷'’GWF÷&–Â6WVVæ6RæBæòf÷&6VBGWF÷&–Â÷fW&Æ’&VÖ–ç2âFòæ÷B&Vv–âWFöæöÖ÷W2Ö–â7F÷'’÷"g&VRVW7B&öw&W76–öâ–âF†—2Æâà ¥&W727G&Âµ6†–gB´c&ÂfW&–g’FF÷&V6÷&F–æw2÷GWF÷&–ÂÖgW—V¶’õ5DõTF6öçF–ç2VÖW&vVæ7•÷7F÷ÂæBFòæ÷BFVÆWFRF†RÆF6‚à ¢Ò²Ò¢¥7FWS¢w&—FRF†R&V6öææ—76æ6R¦÷W&æÂ¢  ¤7&VFRFö72÷&V6öææ—76æ6R÷GWF÷&–ÂÖgW—V¶’æÖFv—Fƒ  ¦Ö&¶F÷và¢2gW—V¶’GWF÷&–Â&V6öææ—76æ6P ¢22Vçf—&öæÖVç@ ¢ÒW†7BÄEÆ–W"W†V7WF&ÆR÷F—FÆP¢Ò‡—6–6ÂöÆöv–6Â&V7FævÆW2ÂÖöæ—F÷"÷v÷&²&VÂv–æF÷w2E¢ÒæG&ö–Bf–Ww÷'BæB÷&–VçFF–öà¢ÒvÖRfW'6–öâæB6W76–öâUD27F'BöVæ@ ¢22÷&FW&VBG&ç6—F–öç0 ¤f÷"WfW'’&V6÷&FVBG&ç6—F–öã¢&Vf÷&Rö'6W'fF–öâ”BÂ67&VVä¶–æBÂf—6–&ÆRÆ&VÇ2Â6VÖçF–27F–öä¶–æBÂ&W6÷W&6Rö6÷7BöÖæFF÷'’f–VÆG2ÂF&vWBæ÷&ÖÆ—¦VB&V7FævÆRÂöÆ–7’Fö¶Vâ&Vf—‚ÂgFW"ö'6W'fF–öâ”BÂæB÷WF6öÖRà ¢22æWr&WW6&ÆRT’6öæ6WG0 ¤Æ—7BV6‚F—7F–æ7BÖÖ&¶W"Â6¶—6öçG&öÂÂ6öæf—&ÖF–öâÂ7W÷'BÆ–÷WBÂ'G’Æ–÷WBÂ&GFÆR†6RÂ&W7VÇB6öçG&öÂÂ7VÖÖöâ÷GWF÷&–Â6öçG&öÂÂæBÆöF–æröæWGv÷&²GFW&âö'6W'fVBà ¢227F÷2æBæöÖÆ–W0 ¥&V6÷&BWfW'’FVæ–VB&÷÷6ÂÂ&WG'’Â6öæf–FVæ6RF÷væw&FRÂ÷"VæW‡V7FVB7FFRâw&—FRæöæVv†Vâæò—FVÒö67W'&VBà¦  ¥÷VÆFRWfW'’6V7F–öâg&öÒF†R7GVÂ&V6÷&F–æs²Fòæ÷B–æ6ÇVFR66÷VçB–FVçF–f–W'2÷"&rVç&VÆFVB×v–æF÷r6öçFVçBà ¢Ò²Ò¢¥7FWc¢6†V6·ö–çBF6²r¢  ¤VæBF†R6W76–öâF‚Âö'6W'fF–öâö7F–öâ÷G&ç6—F–öâ6÷VçG2Â5DõTBÆF6‚&W7VÇBÂæB6öÖÖ—C¢Væf–Æ&ÆVFòFö72öW†V7WF–öâÖÆöræÖFà ¢ÒÒÐ ¢222F6²ƒ¢fÆ–FFRF†RGWF÷&–ÂFF6WBæB7&VFRF†RæW‡B×Æâ†æFöf` ¢¢¤f–ÆW3¢¢ ¢Ò7&VFS¢7&2öfvõöwV&F–â÷FööÇ2÷fÆ–FFU÷&V6÷&F–ærç– ¢Ò7&VFS¢FW7G2÷FW7E÷&V6÷&F–æu÷fÆ–FF–öâç– ¢Ò7&VFS¢Fö72÷7WW'÷vW'2÷Æç2ó##bÓrÓ#ÖfvòÖvVçB×&öFÖæÖF ¢ÒÖöF–g“¢Fö72öW†V7WF–öâÖÆöræÖF  ¢¢¤–çFW&f6W3¢¢ ¢Ò6öç7VÖW3¢&WÆ•6W76–öææBF†RÆ—fRGWF÷&–ÂÖgW—V¶–&V6÷&F–ærà¢Ò&öGV6W3¢fÆ–FFU÷&V6÷&F–ær‡&ö÷C¢F‚Â&WV—&VE÷67&VVç3¢6WEµ67&VVä¶–æEÒ–Â¦W&òÖW'&÷"Æ—fRfÆ–FF–öâ&W÷'BÂæBW†7B–çWG2f÷"F†RæW‡BÆö6Â×W&6WF–öâÆâà ¢Ò²Ò¢¥7FW¢w&—FRf–Æ–ærFF6WB×fÆ–FF–öâFW7G2¢  ¦—F†öà¢2FW7G2÷FW7E÷&V6÷&F–æu÷fÆ–FF–öâç¦g&öÒF†Æ–"–×÷'BF€ ¦–×÷'B—FW7@ ¦g&öÒfvõöwV&F–âævVçEöÖöFVÇ2–×÷'B67&VVä¶–æ@¦g&öÒfvõöwV&F–âçFööÇ2çfÆ–FFU÷&V6÷&F–ær–×÷'BfÆ–FFU÷&V6÷&F–æp  ¦FVbFW7E÷fÆ–FF–öå÷&V¦V7G5öÖ—76–æu÷&WV—&VE÷67&VVâ‡F×÷Fƒ¢F‚’ÓâæöæS ¢‡F×÷F‚ò&ö'6W'fF–öç2æ§6öæÂ"’çw&—FU÷FW‡B‚""ÂVæ6öF–æsÒ'WFbÓ‚"¢‡F×÷F‚ò&7F–öç2æ§6öæÂ"’çw&—FU÷FW‡B‚""ÂVæ6öF–æsÒ'WFbÓ‚"¢‡F×÷F‚ò'G&ç6—F–öç2æ§6öæÂ"’çw&—FU÷FW‡B‚""ÂVæ6öF–æsÒ'WFbÓ‚"¢v—F‚—FW7Bç&—6W2…fÇVTW'&÷"ÂÖF6ƒÒ&Ö—76–ær&WV—&VB67&VVç2"“ ¢fÆ–FFU÷&V6÷&F–ær‡F×÷F‚Âµ67&VVä¶–æBåEUDõ$”ÅôÔÒ  ¦FVbFW7E÷fÆ–FF–öå÷&V¦V7G5÷V'G¥öÆ&VÅöWfVå÷v—F†÷WE÷V'G¥÷&W6÷W&6R‡F×÷Fƒ¢F‚’ÓâæöæS ¢‡F×÷F‚ò&ö'6W'fF–öç2æ§6öæÂ"’çw&—FU÷FW‡B‚""ÂVæ6öF–æsÒ'WFbÓ‚"¢‡F×÷F‚ò'G&ç6—F–öç2æ§6öæÂ"’çw&—FU÷FW‡B‚""ÂVæ6öF–æsÒ'WFbÓ‚"¢‡F×÷F‚ò&7F–öç2æ§6öæÂ"’çw&—FU÷FW‡B€¢w²'Fö¶Vâ#¢'‚"Â'&÷÷6Â#§²&Æ&VÇ2#¥²%6–çBV'G¢%ÒÂ'&W6÷W&6R#¢$äôäR'ÒÂ&FV6—6–öâ#§²&ÆÆ÷vVB#§G'VRÂ'&V6öâ#¢&ÆÆ÷vVB'×ÕÆârÀ¢Væ6öF–æsÒ'WFbÓ‚"À¢¢v—F‚—FW7Bç&—6W2…fÇVTW'&÷"ÂÖF6ƒÒ%V'G¢"“ ¢fÆ–FFU÷&V6÷&F–ær‡F×÷F‚Â6WB‚’  ¦FVbFW7E÷fÆ–FF–öå÷&V¦V7G5÷VæÖ6¶VE÷F—FÆUöö'6W'fF–öâ‡F×÷Fƒ¢F‚’ÓâæöæS ¢‡F×÷F‚ò&7F–öç2æ§6öæÂ"’çw&—FU÷FW‡B‚""ÂVæ6öF–æsÒ'WFbÓ‚"¢‡F×÷F‚ò'G&ç6—F–öç2æ§6öæÂ"’çw&—FU÷FW‡B‚""ÂVæ6öF–æsÒ'WFbÓ‚"¢‡F×÷F‚ò&ö'6W'fF–öç2æ§6öæÂ"’çw&—FU÷FW‡B€¢w²&ö'6W'fF–öåö–B#¢&ö'2×F—FÆR"Â'67&VVâ#¢%D•DÄR"Â&Ö6·5öÆ–VB#£ÕÆârÀ¢Væ6öF–æsÒ'WFbÓ‚"À¢¢v—F‚—FW7Bç&—6W2…fÇVTW'&÷"ÂÖF6ƒÒ'&—f7’Ö6²"“ ¢fÆ–FFU÷&V6÷&F–ær‡F×÷F‚Â6WB‚’¦  ¢Ò²Ò¢¥7FW#¢'VâæBfW&–g’–×÷'Bf–ÇW&R¢  ¥'Vã  ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—FW7BFW7G2÷FW7E÷&V6÷&F–æu÷fÆ–FF–öâç’×`¦  ¤W‡V7FVC¢6öÆÆV7F–öâf–Ç2&V6W6RfÆ–FFU÷&V6÷&F–ævFöW2æ÷BW†—7Bà ¢Ò²Ò¢¥7FW3¢–×ÆVÖVçBF†RfÆ–FF÷"æB4Ä’¢  ¦—F†öà¢27&2öfvõöwV&F–â÷FööÇ2÷fÆ–FFU÷&V6÷&F–ærç¦g&öÒõögWGW&Uõò–×÷'Bææ÷FF–öç0 ¦–×÷'B&w'6P¦g&öÒF†Æ–"–×÷'BF€ ¦g&öÒfvõöwV&F–âævVçEöÖöFVÇ2–×÷'B7F–öä¶–æBÂ67&VVä¶–æ@¦g&öÒfvõöwV&F–âç&WÆ’–×÷'B&WÆ•6W76–öà  ¤dõ$$”DDTåô´”äE2Ò°¢7F–öä¶–æBäõD”ôäÅõ5TÔÔôâçfÇVRÀ¢7F–öä¶–æBåU$4„4RçfÇVRÀ¢7F–öä¶–æBä44õTåEô5D”ôâçfÇVRÀ¢7F–öä¶–æBäDTÄUDUôDDçfÇVRÀ¢7F–öä¶–æBä4ÄT%ô44„RçfÇVRÀ§Ð  ¦FVbfÆ–FFU÷&V6÷&F–ær‡&ö÷C¢F‚Â&WV—&VE÷67&VVç3¢6WEµ67&VVä¶–æEÒ’ÓâF–7E·7G"Â–çEÓ ¢&WÆ’Ò&WÆ•6W76–öâ‡&ö÷B¢ö'6W'fF–öç2Ò&WÆ’æö'6W'fF–öç2‚¢7F–öç2Ò&WÆ’æ7F–öç2‚¢G&ç6—F–öç2Ò&WÆ’çG&ç6—F–öç2‚¢67&VVç3¢6WEµ67&VVä¶–æEÒÒ6WB‚¢f÷"ö'6W'fF–öâ–âö'6W'fF–öç3 ¢67&VVâÒ67&VVä¶–æB†ö'6W'fF–öå²'67&VVâ%Ò¢–b67&VVâ—267&VVä¶–æBåTä´äõtã ¢&—6RfÇVTW'&÷"‚'&V6÷&F–ær6öçF–ç2âTä´äõtâö'6W'fF–öâ"¢–b67&VVâ—267&VVä¶–æBåD•DÄRæB–çB†ö'6W'fF–öâævWB‚&Ö6·5öÆ–VB"Â’’Â ¢&—6RfÇVTW'&÷"‚%D•DÄRö'6W'fF–öâ—2Ö—76–ær—G2&—f7’Ö6²"¢67&VVç2æFB‡67&VVâ¢f÷"7F–öâ–â7F–öç3 ¢&÷÷6ÂÒ7F–öå²'&÷÷6Â%Ð¢æ÷&ÖÆ—¦VEöÆ&VÇ2Ò·7G"†Æ&VÂ’ç7G&—‚’æ66VföÆB‚’f÷"Æ&VÂ–â&÷÷6ÂævWB‚&Æ&VÇ2"Â‚’—Ð¢Æ&VÇ2Ò""æ¦ö–â†æ÷&ÖÆ—¦VEöÆ&VÇ2¢–b'V'G¢"–âÆ&VÇ2÷"'7"–âæ÷&ÖÆ—¦VEöÆ&VÇ2÷"&÷÷6ÂævWB‚'&W6÷W&6R"’ÓÒ%4”åEõT%E¢# ¢&—6RfÇVTW'&÷"‚'&V6÷&F–ær6öçF–ç26–çBV'G¢&÷÷6Â"¢–b&÷÷6ÂævWB‚&¶–æB"’–âdõ$$”DDTåô´”äE3 ¢&—6RfÇVTW'&÷"‚'&V6÷&F–ær6öçF–ç2W&ÖæVçFÇ’f÷&&–FFVâ7F–öâ&÷÷6Â"¢&WÆ’çfÆ–FFR‚¢Ö—76–ærÒ&WV—&VE÷67&VVç2Ò67&VVç0¢–bÖ—76–æs ¢&—6RfÇVTW'&÷"‚&Ö—76–ær&WV—&VB67&VVç3¢"²"Â"æ¦ö–â‡6÷'FVB†—FVÒçfÇVRf÷"—FVÒ–âÖ—76–ær’’¢&WGW&â²&ö'6W'fF–öç2#¢ÆVâ†ö'6W'fF–öç2’Â&7F–öç2#¢ÆVâ†7F–öç2’Â'G&ç6—F–öç2#¢ÆVâ‡G&ç6—F–öç2—Ð  ¦FVbÖ–â‚’ÓâæöæS ¢'6W"Ò&w'6Rä&wVÖVçE'6W"‚¢'6W"æFEö&wVÖVçB‚'&ö÷B"ÂG—SÕF‚¢&w2Ò'6W"ç'6Uö&w2‚¢&WV—&VBÒ°¢67&VVä¶–æBåEUDõ$”ÅôÔÀ¢67&VVä¶–æBå5Dõ%’À¢67&VVä¶–æBå5Uõ%Eõ4TÄT5BÀ¢67&VVä¶–æBå%E•ô4ôäd•$ÒÀ¢67&VVä¶–æBä$EDÄRÀ¢67&VVä¶–æBåTU5Eõ$U5TÅBÀ¢Ð¢6÷VçG2ÒfÆ–FFU÷&V6÷&F–ær†&w2ç&ö÷BÂ&WV—&VB¢&–çB†b&ö'6W'fF–öç3×¶6÷VçG5²vö'6W'fF–öç2u×Ò7F–öç3×¶6÷VçG5²v7F–öç2u×ÒG&ç6—F–öç3×¶6÷VçG5²wG&ç6—F–öç2u×Ò"  ¦–bõöæÖUõòÓÒ%õöÖ–åõò# ¢Ö–â‚¦  ¢Ò²Ò¢¥7FWC¢'Vâfö7W6VBÂgVÆÂÂæBÆ—fR×&V6÷&F–ærfÆ–FF–öâ¢  ¥'Vã  ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—FW7BFW7G2÷FW7E÷&V6÷&F–æu÷fÆ–FF–öâç’×`¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—FW7BÒÖ6÷cÖfvõöwV&F–âÒÖ6÷b×&W÷'C×FW&ÒÖÖ—76–æp¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒfvõöwV&F–âçFööÇ2çfÆ–FFU÷&V6÷&F–ærFFÇ&V6÷&F–æw5ÇGWF÷&–ÂÖgW—V¶¦  ¤W‡V7FVC¢276VFfö7W6VC²F†RgVÆÂ7V—FR6öçF–ç2S76VF²F†RÆ—fRfÆ–FF÷"W†—G2Â&W÷'G2æöç¦W&òö'6W'fF–öç2ö7F–öç2÷G&ç6—F–öç2ÂæB&W÷'G2æò6–çBV'G¢÷"W&ÖæVçFÇ’f÷&&–FFVâ&÷÷6Âà ¢Ò²Ò¢¥7FWS¢w&—FRF†R6&–Æ—G’&öFÖ¢  ¤7&VFRFö72÷7WW'÷vW'2÷Æç2ó##bÓrÓ#ÖfvòÖvVçB×&öFÖæÖF  ¦Ö&¶F÷và¢27FæFÆöæRdtòvVçB6&–Æ—G’&öFÖ  £â6fWG’6†VÆÂæBGWF÷&–Â&V6öææ—76æ6R(	B–×ÆVÖVçFVB'’##bÓrÓ#ÖfvòÖvVçB×&V6öææ—76æ6RæÖFà£"âÆö6ÂW&6WF–öâæBFÆ26æ6†÷B(	BG&–âöWfÇVFRdtòö&¦V7BFWFV7F–öâÂ&÷VæFVBô5"ÂÆö6ÂdÄÒfÆÆ&6²ÂæBfW'6–öæVBöffÆ–æR¶æ÷vÆVFvR–×÷'Bv–ç7BFF÷&V6÷&F–æw2÷GWF÷&–ÂÖgW—V¶–à£2â&GFÆRvVçB(	B7W÷'B&æ¶–ærÂ'G’&V6övæ—F–öâÂ6¶–ÆÂôå¶æ÷vÆVFvRÂF&vWB66÷&–ærÂ6öÖÖæBÖ6&B66÷&–ærÂvfR÷&W7VÇB†æFÆ–ærÂÆRæB6öÖÖæB7VÆÂöÆ–6–W2à£BâVW7BÆææW"(	BÖF—66÷fW'’v—F†÷WB&WV—&–æräU…BÂVW7Bw&‚W'6—7FVæ6RÂg&VRÖ&Vf÷&RÕ7F÷'’&–÷&—G’ÂFòÆÂVW7G2æBf&Ö–ærÖöFW2à£Râ–çFVw&F–öâ(	BFW6·F÷T’Â6†F÷rÖöFRÂf—6–&ÆR7FæF&BÖ–çWBW†V7WF÷"Â6¶v–ærÂæBÆ—fR66WFæ6RvFW2à ¤WfW'’ÆFW"Æâ×W7B6öç7VÖRF†R–Ö×WF&ÆRö'6W'fF–öæÂ7F–öå&÷÷6ÆÂöÆ–7”vFVÂ&V6÷&F–æu7F÷&VÂæB&WÆ•6W76–öæ–çFW&f6W2âæòÆFW"†6RÖ’FB6–çBV'G¢ÆÆ÷rF‚÷"'—72F†Rv–æF÷rwV&F–âà¦  ¢Ò²Ò¢¥7FWc¢f–æÂfW&–f–6F–öâæB6†V6·ö–çB¢  ¥'Vã  ¦÷vW'6†VÆÀ¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ—FW7BÒÖ6÷cÖfvõöwV&F–âÒÖ6÷b×&W÷'C×FW&ÒÖÖ—76–æp¢çfVçeÅ67&—G5Ç—F†öâæW†RÖÒ6ö×–ÆVÆÂ×7&0¦  ¤W‡V7FVC¢C’76VFÂæòVçFW7FVB'&æ6‚6&ÆRöbWF†÷&—¦–ærf÷&&–FFVâ7F–öâ÷"w&—F–ærâVç&VF7FVBVæ¶æ÷vâ÷F—FÆRg&ÖRÂæB6ö×–ÆVÆÂW†—G2à ¤VæBgVÆÂ&W7VÇG2ÂÆ—fR×&V6÷&F–ær6÷VçG2Â&öFÖF‚ÂæB6öÖÖ—C¢Væf–Æ&ÆVFòFö72öW†V7WF–öâÖÆöræÖFà ¢ÒÒÐ ¢22Æâ6ö×ÆWF–öâ6†V6° ¤&Vf÷&R6Æ–Ö–ærF†—27V'&ö¦V7B6ö×ÆWFRÂfW&–g’ÆÂöbF†RföÆÆ÷v–æs  ¢ÒF†R–æ†W&—FVB‚×FW7BwV&F–âö6GW&R&6VÆ–æRv2&W6W'fVBà¢ÒÆÂæWvÇ’FFVBFW7G272æBF†RF÷FÂ—2W†7FÇ’C’à¢ÒF†R6¶vR6öçF–ç2æò&WW6&ÆRvÖWÆ’Ö–çWB÷"6ö÷&F–æFR×&WÆ’ÖöGVÆRà¢ÒW†7FÇ’öæR&WGW&æVBÄEÆ–W"v–æF÷rv2W6VBGW&–ær&V6öææ—76æ6Rà¢ÒWfW'’6fVBg&ÖRv2&öGV6VBöæÇ’gFW"6fR&R÷÷7B6GW&R6†V6·2à¢ÒVæ¶æ÷vâ67&VVç2vW&Ræ÷Bw&—GFVâFòF—6²à¢ÒF—FÆR×67&VVâg&ÖW2†fRWfW'’6öæf–wW&VB66÷VçBÔ”BÖ6²Æ–VB&Vf÷&Rw&—FRà¢ÒWfW'’Æ—fR6Æ–6²†2öæR&–÷"ÆÆ÷vVBöÆ–7’Fö¶VâæBöæRföÆÆ÷v–ærö'6W'fF–öâà¢Òæò7F–öâ÷"Æ&VÂ–çföÇf–ær6–çBV'G¢v2WF†÷&—¦VBà¢ÒÖæFF÷'’GWF÷&–Â7VÖÖöç2Â–bVæ6÷VçFW&VBÂvW&R¦W&ò6÷7BæBÖ&¶VBÖæFF÷'’à¢ÒF†RvÆö&Â7G&Âµ6†–gB´c&7F÷7&VFVBGW&&ÆR5DõTBÆF6‚à¢Ò&WÆ•6W76–öâçfÆ–FFR‚–æBF†RÆ—fRfÆ–FF÷"72öâGWF÷&–ÂÖgW—V¶–à¢ÒF†RGWF÷&–Â¦÷W&æÂ6öçF–ç2æò66÷VçB–FVçF–f–W"÷"Vç&VÆFVB×v–æF÷r6öçFVçBà¢ÒF†R6&–Æ—G’&öFÖ–FVçF–f–W2F†RGWF÷&–ÂFF6WB2F†R–çWBFòF†RæW‡BW&6WF–öâÆâà 