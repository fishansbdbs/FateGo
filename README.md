# FateGo Hybrid Vision Agent

Standalone, local-first Fate/Grand Order automation for one guarded LDPlayer window. Milestone 1 implements the autonomous Fuyuki Story loop with deterministic screen recognition, support and party navigation, ordinary battle decisions, Servant skill use, reward collection, Story skipping, replayable logs, and immediate Start/Pause/Stop controls.

## Start it

1. Keep exactly one configured LDPlayer window open with Fate/GO visible.
2. Double-click `Start FateGo Agent.cmd`.
3. Press **Start** in the control panel.

The default run is Story mode and repeats until you press **Stop**. **Pause** prevents another action from being authorized; press **Resume** to continue. `Ctrl+Shift+F12` is the terminal emergency stop for the current control-panel session. Add `--max-quests 1` to the command-line launch when you want a bounded one-quest run.

For a command-line launch:

```powershell
.\.venv\Scripts\pythonw.exe -m fgo_guardian.app --mode story
```

Available modes are `story`, `all-quests`, and `farming`. Farming mode also requires `--farming-anchor`; its broader live-screen coverage is a later milestone.

## Permanent safety rules

- Never spend Saint Quartz, Command Spells, or Summon Tickets.
- Apple use is allowed by policy, but a live AP-refill screen must be recognized before any Apple tap. Milestone 1 does not yet include that live template.
- Pause on unknown screens instead of guessing.
- Never continue after defeat. Recognized defeat saves a redacted screenshot, structured state, and diagnostic log before stopping.
- Use visible screenshots and standard Windows input only—no ADB, root, memory inspection, injection, packet interception, APK changes, or evasion.

Collecting Saint Quartz earned as a quest reward is allowed; spending Saint Quartz is not.

The defeat recovery path is implemented and tested offline, but Milestone 1 does not yet contain a sampled live defeat template. An unseen live defeat therefore takes the safer unknown-screen path and pauses/quarantines the frame. Live defeat recognition and live AP-refill recognition are explicit blockers for the next milestone.

## Safety behavior

The agent establishes one immutable LDPlayer baseline before a run. It pauses before input if that window is minimized, moved, resized, unfocused, overlapped, or changes DPI, display, emulator resolution, or orientation. Each action is authorized once against the current screenshot and expires if the state changes.

Unknown screens are written to the local quarantine dataset. A newly classified observation becomes active only after the complete regression suite passes. Runtime journals, screenshots, incidents, and experience data remain under `data/` and are ignored by Git.

## Development

Create the Python 3.14 environment once:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Live OCR also requires a local Tesseract installation. Put `tesseract.exe` on `PATH` or install it at `C:\Program Files\Tesseract-OCR\tesseract.exe`.

Run the test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run a screenshot recording without input:

```powershell
.\.venv\Scripts\python.exe -m fgo_guardian.app --simulation PATH_TO_RECORDING --max-quests 1
```

The frozen architecture is documented in [`docs/superpowers/specs/2026-07-20-fgo-autonomous-agent-design.md`](docs/superpowers/specs/2026-07-20-fgo-autonomous-agent-design.md).
