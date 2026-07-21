# FGO Window Guardian and Recognition Harness Design

**Date:** 2026-07-20  
**Status:** Approved design, awaiting written-spec review  
**First milestone:** Observe and classify the visible Fate/Grand Order/LDPlayer state without producing gameplay input.

## Objective

Build the safety and recognition foundation for a supervised Fate/Grand Order farming assistant running in one LDPlayer window on Windows. The first milestone must prove that the application can identify the correct emulator, establish an exact display baseline, recognize known screens, and stop on unsafe changes before any gameplay input is implemented.

The application is not intended to evade platform protections or make third-party automation risk-free. The user remains responsible for deciding whether to use automation with their account.

## Inspected Environment

- Executable: `C:\LDPlayer\LDPlayer14\dnplayer.exe`
- LDPlayer build: `14.0.15.0`
- Visible window title: `LDPlayer`
- Fate/Grand Order tab title: `Fate/GO`
- Android package observed through LDPlayer UI metadata: `com.aniplex.fategrandorder.en`
- Fate/Grand Order version: `2.90.2`
- Emulator profile: Tablet
- Android resolution: `1920 x 1080`
- Android DPI: `280`
- Orientation during inspection: landscape
- CPU allocation: 6 cores
- RAM allocation: 6144 MB
- Frame-rate profile: Standard, up to 60 FPS
- Performance mode: Auto
- Remember window size and position: enabled
- Fix window size: enabled
- Automatically rotate window: enabled during inspection; this must be disabled before live automation
- Root permission: disabled
- ADB debugging: connection disabled
- Keymap scheme: Customize, with no FGO key bindings visibly placed
- Operation Recorder: available, no recorded scripts present, recording hotkey `F10`

The initially stable Windows capture baseline was position `(-1920, 0)` and size `1920 x 1040` logical pixels. Emulator tool panels later changed the captured bounds. The application must therefore establish a new user-approved baseline at runtime and must never assume the inspection measurement is still valid.

## Non-Negotiable Boundaries

- Control only the one user-selected `dnplayer.exe` window.
- Never use root, ADB control, memory inspection, process injection, APK modification, packet interception, emulator tampering, or anti-detection behavior.
- Never automate authentication, CAPTCHA, purchases, Saint Quartz spending, summoning, account transfer, data deletion, Clear Cache, or communication with other players.
- Never use Synchronizer.
- Never capture or retain unrelated application content.
- Never OCR, display, or log the account ID area on the FGO title screen.
- Never continue when the expected state is absent or confidence is below the configured threshold.
- Do not implement story progression, farming clicks, or recorder playback in this milestone.

## Approaches Considered

### 1. LDPlayer Operation Recorder only

This is the smallest implementation, but it replays time- and coordinate-based actions. It cannot reliably branch on support-list changes, network delays, AP warnings, inventory-full dialogs, defeat, or unexpected screens. It does not meet the required uncertainty and stop behavior, so it is rejected as the primary controller.

### 2. Recorder sequence with an external watchdog

A visual watchdog could start a short recorder script only after recognizing a known state. This reduces custom input work, but the recorder can still continue clicking inside a sequence after the screen diverges. It may be considered later for a short, deterministic segment only if the watchdog can interrupt immediately.

### 3. Visible state machine with standard mouse input

The recommended long-term design recognizes the screen before every action and uses standard Windows mouse input only after a state-specific confidence check. It requires more templates and testing but best satisfies supervised operation, stop-on-uncertainty, and recovery requirements.

The first milestone implements only the observation and safety portion of approach 3.

## Architecture

### `window_guardian`

Finds windows owned by `dnplayer.exe`, requires exactly one user-approved target, and records:

- executable path and window handle
- outer and client rectangles
- monitor identity and work area
- Windows DPI returned for the target window
- emulator render dimensions and orientation
- foreground, minimized, and visibility state

The process must use per-monitor DPI awareness so coordinates are not silently virtualized by Windows scaling.

Before every capture, it enumerates visible top-level windows above LDPlayer and checks rectangle intersection. If another window overlaps the LDPlayer game area, it pauses before capture. It rechecks after capture; if overlap appeared during capture, the frame is discarded and never written to disk.

### `screen_capture`

Captures only the visible LDPlayer rectangle from the Windows desktop. It does not capture the full desktop and does not use hidden-window capture as a substitute for visibility. Capture is allowed only after `window_guardian` reports a safe state.

### `viewport_mapper`

Separates LDPlayer chrome from the Android render surface using visible anchors:

- LDPlayer title bar and `Fate/GO` tab
- right-side LDPlayer toolbar boundary
- Android render rectangle
- landscape aspect ratio

All later anchor coordinates are normalized to the detected Android render rectangle. Raw coordinates from the inspection session are diagnostic values, not automation targets.

### `state_detector`

Classifies a captured frame and returns a state name, confidence, matched anchors, and exclusion masks. Initial supported states are:

- `FGO_TITLE`
- `FGO_TUTORIAL_MAP`
- `LDPLAYER_SETTINGS`
- `LDPLAYER_OPERATION_RECORDER`
- `LDPLAYER_KEYMAP_EDITOR`
- `UNKNOWN`

The detector uses template matching first and bounded OCR only when template matching cannot distinguish states. OCR is forbidden inside the title-screen account-ID mask. The default acceptance threshold is `0.92`; lower confidence produces `UNKNOWN` and pauses inspection.

### `safety_controller`

Owns the application state `DISARMED`, `READY`, `INSPECTING`, `PAUSED`, or `EMERGENCY_STOPPED`. It pauses immediately for:

- zero or multiple LDPlayer targets
- minimized or hidden target
- focus loss
- position, size, client rectangle, monitor, or DPI change
- Android resolution or orientation change
- unrelated-window overlap
- repeated unchanged screen beyond the configured timeout
- unknown or low-confidence visual state
- capture failure

The default emergency-stop hotkey is `Ctrl+Shift+F12`, selected to avoid the inspected LDPlayer shortcuts (`Ctrl+Q`, `F11`, `Ctrl+F1`, `F4`, `F5`, and `F10`). The hotkey remains configurable.

### `dry_run_ui`

Provides a small Windows UI with:

- target-window selector restricted to LDPlayer candidates
- inspected baseline and current geometry
- current state and confidence
- pause reason
- start inspection, pause, disarm, and reset-baseline controls
- saved-screenshot test mode
- a preview showing matched anchors and intended exclusion masks

The preview appears inside the assistant UI, not as an overlay on LDPlayer, because an overlay would itself overlap the protected game area.

### `audit_log`

Writes structured JSON Lines events and saves a bounded diagnostic screenshot only for safe LDPlayer-only frames. Events include timestamps, state transitions, confidence, geometry hashes, and pause reasons. Logs must not contain account IDs, unrelated-window content, or raw OCR text from masked regions.

## Data Flow

1. The user launches LDPlayer, places it at the desired fixed position, disables automatic rotation, and leaves it unobstructed.
2. The user launches the assistant and selects the single detected LDPlayer candidate.
3. `window_guardian` establishes a baseline only after two identical geometry samples.
4. `safety_controller` verifies focus, visibility, geometry, DPI, orientation, and overlap.
5. `screen_capture` captures the visible LDPlayer region.
6. `viewport_mapper` extracts the Android render surface.
7. `state_detector` classifies the screen and returns confidence and anchors.
8. `dry_run_ui` displays the result and `audit_log` records non-sensitive metadata.
9. Any failed safety check transitions immediately to `PAUSED`; the application does not guess or automatically resume.

## Dangerous Regions

The title-screen masks for Data Transfer, Clear Cache, the account-ID display area, and any future purchase or summoning controls are permanent exclusion zones. Later milestones must refuse to place an intended click inside these regions even if another detector suggests it.

## Testing Strategy

### Unit tests

- unique-window selection and rejection of zero/multiple candidates
- logical-to-physical coordinate conversion across negative monitor coordinates
- detection of focus, minimized, moved, resized, DPI-changed, and rotated states
- overlap detection and post-capture overlap race handling
- normalized viewport mapping
- confidence threshold behavior
- title-screen privacy masking
- emergency-stop state transition
- audit-log redaction

### Screenshot tests

- classify saved FGO title and tutorial-map frames
- classify LDPlayer Settings, Operation Recorder, and keymap-editor frames
- reject cropped, scaled, partially occluded, and unrelated frames
- verify dangerous-region masks remain inside the detected Android viewport

### Live dry run

- establish the approved LDPlayer baseline
- observe for at least five minutes without input
- deliberately move, resize, unfocus, minimize, overlap, and rotate the window one condition at a time
- verify every condition pauses before another frame is processed
- verify `Ctrl+Shift+F12` stops inspection immediately
- verify the application cannot generate mouse or keyboard input in this milestone

## Acceptance Criteria

The first milestone is complete only when:

1. Exactly one approved LDPlayer window is selected.
2. The recorded baseline includes physical and logical geometry, monitor, Windows DPI, Android resolution, DPI, and orientation.
3. Every listed safety violation deterministically pauses inspection.
4. Known test screenshots classify at or above `0.92` confidence.
5. Unknown, altered, or obstructed screenshots pause rather than falling back to a guess.
6. Emergency stop works while the assistant is inspecting.
7. Logs and saved frames contain no account ID or unrelated application content.
8. The milestone contains no functional gameplay input path.

## Later Approval Gates

After this milestone passes, later work requires separate specifications and approvals:

1. **Supervised observation:** the user manually completes several battles while the assistant records only visible states and user actions.
2. **One-battle controller:** implement standard mouse input for a single supervised battle, with no repeats.
3. **Single-node repetition:** add AP, inventory, victory, defeat, unexpected-dialog, time, and run-count stop conditions.
4. **Optional recorder adapter:** consider a bounded Operation Recorder segment only if it cannot outlive the external safety controller.

No repeat mode may be enabled until screenshot tests, dry-run observation, and one supervised live battle have each passed and the user has approved the next gate.

## Reference

- LDPlayer Operation Recorder guide: https://www.ldplayer.net/blog/how-to-use-operation-recorder.html
- LDPlayer recorder troubleshooting: https://www.ldplayer.net/blog/how-to-fix-recorded-script-stopping-automatically.html
