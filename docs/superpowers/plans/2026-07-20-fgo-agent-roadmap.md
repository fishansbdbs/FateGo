# Standalone FGO Agent Capability Roadmap

This roadmap implements the already approved standalone, local-first FGO agent design. It does not create a Saint Quartz exception. The current account is stopped at a mandatory tutorial summon costing 30 Saint Quartz, so future live work requires either an account already past that gate or the user independently completing it outside the agent.

## 1. Safety shell and tutorial reconnaissance

Implemented by `2026-07-20-fgo-window-guardian.md` and `2026-07-20-fgo-agent-reconnaissance.md`.

- Exact LDPlayer identity, geometry, focus, resolution, orientation, overlap, and viewport monitoring.
- Persistent fail-closed viewport state, global emergency stop, privacy-aware recording, replay integrity, and semantic one-action authorization.
- A verified completed prefix at `data/recordings/tutorial-fuyuki-run`: 51 observations, 52 action attempts, 49 completed transitions, and one safe-stop tail.
- Story Skip/confirmation, map nodes, forced tutorial prompts, battle phases, target/skill/card interactions, and result chains are represented.
- The tutorial is not complete. The agent stopped before `Saint Quartz Cost 30`, exactly as required.

## 2. Local perception and knowledge snapshot

Build a deterministic perception pipeline before adding reusable input:

1. Versioned templates for stable controls and anchors.
2. Bounded OCR for AP, wave/enemy counters, node labels, result buttons, resource names/costs, and failure text.
3. Local object detection for map markers, support rows, party controls, skill/NP cards, enemies, command cards, Skip, Next, and modal buttons.
4. A small local vision-model fallback only for states rejected by deterministic detectors. Cloud inference is not required.
5. A versioned offline FGO knowledge import with provenance, integrity hash, upstream version, and license metadata. Runtime gameplay does not query remote services.

Evaluation must split by screen family and animation state. UNKNOWN remains non-actionable. Every classifier output includes confidence, anchors, and prohibited regions rather than raw replay coordinates.

## 3. Battle agent

Implement battle decisions behind the existing immutable `Observation`, `ActionProposal`, and `PolicyGate` interfaces:

- Recognize wave, enemy classes/HP, allies, cooldowns, NP state, buffs/debuffs, command cards, critical stars, target state, victory, and defeat.
- Rank supports and party choices from visible state plus the offline knowledge snapshot.
- Score skills, NP use, target selection, and three-card chains with deterministic fallbacks.
- Handle variable wave counts and animation lengths by observing state changes, never by sleeping through a fixed macro.
- Stop only on defeat, account/security screens, unrecognized resource prompts, geometry/focus faults, or repeated perception failure.
- Command Spells and Saint Quartz revival are permanently forbidden.

## 4. Quest planner and discovery graph

Persist a local graph of visible locations, nodes, sections, quest states, and return paths. Do not depend on a `NEXT` label always existing.

Two user modes sit above the same graph:

- **Do All Quests:** discover and clear available Story and Free Quests, handle dialogue with arbitrary safe choices, always Skip cutscenes, and revisit maps until no eligible nodes remain.
- **Farming:** repeatedly select a user-chosen known stage, verify the node and AP cost each run, choose support/party, battle, collect results, and return to the same node.

Node identity combines screen anchors, bounded OCR, relative map structure, and transition history. A new or ambiguous node goes through shadow-mode confirmation before it becomes reusable knowledge.

## 5. AP, defeat, and resource policies

- Automatically use Blue, Bronze, Silver, or Golden Apples when AP is insufficient, according to a configurable priority.
- Never use Saint Quartz for AP, summons, revival, inventory expansion, or any other action.
- Never use Command Spells.
- Never consume Summon Tickets.
- On defeat, save a redacted screenshot and structured battle state, log the likely cause, stop all input, and report the quest, party, wave, and visible failure state so the user can upgrade units or adjust the party.
- Receiving Quartz or tickets as quest rewards is allowed; spending them is not.
- Any unclassified currency/cost prompt is a durable stop, not a best guess.

## 6. Visible-input executor and desktop application

Only after perception, battle, and planner shadow-mode gates pass:

- Add a narrowly scoped visible standard mouse/tap executor that consumes one fresh policy token and one current anchored target.
- Recheck unique LDPlayer identity, focus, overlap, geometry, viewport signature, observation hash, and target anchors immediately before every input.
- Require a fresh observation after every input; no coordinate replay, hidden input, ADB, root, process injection, memory inspection, packet interception, APK modification, or anti-detection behavior.
- Package a local desktop UI with Start, Stop, Shadow Mode, Do All Quests, Farming, Apple priority, confidence thresholds, run history, and a prominent emergency-stop status.

## 7. Acceptance gates

Each phase needs offline replay tests, synthetic adversarial frames, and supervised shadow-mode runs before it may control input. Final live acceptance requires:

- no action on UNKNOWN or stale observations;
- exact-window fail-closed behavior for move/resize/minimize/focus/overlap/resolution/orientation changes;
- always-Skip behavior and harmless arbitrary dialogue choices;
- variable-length Story/Free Quest traversal without per-node reconfiguration;
- variable-wave battle completion and result collection;
- automatic Apple-only AP refill, with every other limited or irreversible resource action requiring explicit user approval;
- defeat-only gameplay stop;
- permanent Saint Quartz, Command Spell, and Summon Ticket rejection;
- a reproducible local installer and no mandatory cloud service or subscription.

Every later implementation plan must consume the immutable `Observation`, `ActionProposal`, `PolicyGate`, `RecordingStore`, and `ReplaySession` interfaces. No later phase may add a Saint Quartz allow path, weaken the emergency stop, or bypass the window guardian.
