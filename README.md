# FateGo Hybrid Vision Agent

Standalone, local-first Fate/Grand Order automation for one guarded LDPlayer window.

The project is being built incrementally. The current foundation provides exact-window safety checks, visible capture, viewport mapping, deterministic policy enforcement, privacy-aware recordings, replay validation, and an emergency stop. Milestone 1 adds the autonomous Fuyuki Story loop and always-available Start, Pause, and Stop controls.

## Permanent safety rules

- Never spend Saint Quartz, Command Spells, or Summon Tickets.
- Apples may be used automatically for AP recovery.
- Pause on unknown screens instead of guessing.
- Stop on defeat after saving a redacted screenshot, structured state, and diagnostic log.
- Use visible screenshots and standard Windows input only—no ADB, root, memory inspection, injection, packet interception, APK changes, or evasion.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The frozen architecture is documented in [`docs/superpowers/specs/2026-07-20-fgo-autonomous-agent-design.md`](docs/superpowers/specs/2026-07-20-fgo-autonomous-agent-design.md).
