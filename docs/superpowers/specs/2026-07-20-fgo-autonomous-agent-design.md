# Standalone FGO Autonomous Quest Agent Design

**Date:** 2026-07-20  
**Status:** Frozen and user-approved for implementation  
**Initial release scope:** Fate/Grand Order English Main Story and Free Quests in LDPlayer  
**Long-term scope:** Additional quest categories through later, separately tested capability packs

## Objective

Build a standalone, Fate/Grand Order-specific vision agent that can progress through supported content without per-node configuration. The agent must discover available quests from the visible UI, always skip story, select supports, play variable-length battles, collect results, and continue according to its selected operating mode.

The agent is not a prerecorded coordinate macro. Every action is chosen from a fresh visible observation and verified by observing the resulting screen. It uses no root access, ADB control, process memory reading, APK changes, packet interception, process injection, emulator tampering, or anti-detection behavior.

The finished runtime is fully local, with no cloud model or paid API dependency. Internet access is permitted during installation or an explicit data-update operation to download local model files and static Fate/Grand Order data. Gameplay-time perception, planning, storage, and action selection remain on the user's PC.

## Current State and Prior Work

LDPlayer currently exposes exactly one window titled `LDPlayer` from `C:\LDPlayer\LDPlayer14\dnplayer.exe`. Fate/Grand Order English is open on the Fuyuki tutorial map. The visible tutorial asks the player to tap the location displaying `NEXT`; the highlighted location is `Unknown Coordinates X-A`.

The earlier `FGO Window Guardian and Recognition Harness` scope is superseded by this design as the product goal. Its reviewed foundation remains reusable:

- Task 1 package, immutable model, and inspected-environment configuration work is complete and reviewed.
- Task 2 Win32 metadata and unique-window guardian work is complete and reviewed. It uses only `PROCESS_QUERY_LIMITED_INFORMATION` and `QueryFullProcessImageNameW`; it performs no process memory reading.
- Task 3 visible-capture work was interrupted after files were partially written. Those files are unreviewed and must not be treated as complete until incorporated and tested under the replacement implementation plan.

## User-Approved Behavior

### Operating mode: Do All Quests

1. Complete mandatory tutorial interactions.
2. Discover every currently available supported quest from the visible map.
3. Clear newly unlocked Free Quests before continuing Main Story.
4. Resume the next available Main Story quest after the current Free Quest queue is empty.
5. Repeat as new maps and quests unlock.
6. In the first release, ignore Events, Interludes, Rank Up Quests, Daily Quests, and other unsupported categories.

### Operating mode: Farming

1. The user selects one farming quest once.
2. The agent repeatedly selects a support, starts the quest, skips story, plays all waves, collects results, and restarts the same quest.
3. No run-count limit is required.
4. The agent may consume Blue, Bronze, Silver, and Golden Apples automatically.
5. It stops when AP cannot be restored with permitted Apples or when a battle is lost.

### Story and tutorial rules

- Always press `Skip` whenever it is available and confirm the skip dialog.
- If a non-irreversible dialogue choice remains, select any visible choice and continue.
- Mandatory zero-cost tutorial summons are authorized.
- Optional summons, ticket summons, Saint Quartz summons, and paid summons are prohibited.
- Tutorial-required party formation and enhancement steps using tutorial-provided resources are authorized.
- Outside forced tutorials, preserve the user's prepared party and Craft Essence configuration.

### Battle and resource rules

- Select supports autonomously using visible enemy-class tendency, class affinity, support level, NP availability, and applicable visible bonuses.
- Choose enemy targets, servant skills, Master skills, Noble Phantasms, and command cards autonomously.
- Detect wave transitions instead of assuming a fixed number of waves or turns.
- Never use Command Spells.
- Never spend Saint Quartz for revival, AP, summoning, inventory expansion, purchases, or any other purpose.
- When restoring AP with Apples, prefer expiring/time-limited items first, then the smallest permitted restore that covers the deficit, then larger restores.
- Apples are the only limited consumables authorized for automatic use. Any other irreversible or limited-resource action requires explicit user approval.
- On defeat, capture and retain a redacted screenshot and structured battle state, log the likely failure cause, stop all input, and return control to the user.

## Non-Negotiable Boundaries

- Control only the single exact LDPlayer target selected by executable path and title.
- Pause if the target is minimized, hidden, moved, resized, unfocused, DPI-changed, orientation-changed, resolution-changed, duplicated, or overlapped by another top-level window.
- Capture only the visible LDPlayer outer frame after pre-capture safety checks; repeat the checks after capture and destroy a frame if the post-check fails.
- Use visible screenshots and standard Windows mouse/tap input only.
- Do not use LDPlayer Synchronizer.
- Do not use root, ADB control or modification, memory inspection, APK modification, packet interception, process injection, emulator tampering, or anti-detection techniques.
- Never automate account login, account transfer, CAPTCHA, data deletion, Clear Cache, purchases, or communication with other players.
- Never OCR, display, or retain the FGO account-ID region.
- Never attempt to conceal automation or promise that the account is safe from enforcement.
- A global emergency stop must remain available while any autonomous mode is armed.

## Architecture

### 1. Window guardian

Owns the exact LDPlayer identity and physical/logical display baseline. It checks target count, process path, title, handle, foreground state, visibility, minimization, outer/client rectangles, monitor/work area, Windows DPI, Android viewport, and z-order overlap before and after each capture.

The guardian has no ignored-window bypass. The assistant UI must be placed outside the protected LDPlayer rectangle before arming.

### 2. Visible capture and viewport mapping

Captures only the current LDPlayer outer rectangle from the visible Windows desktop. A viewport mapper separates LDPlayer chrome, the `Fate/GO` tab, right toolbar, title bar, and Android render surface. All game coordinates are normalized to the current Android viewport and are valid only for the observation that produced them.

### 3. Local perception engine

The perception engine is hierarchical:

- A lightweight local object detector recognizes frequent controls and objects at interactive speed.
- Local OCR reads bounded regions such as quest titles, AP costs, wave counters, HP, NP gauges, skill cooldowns, support levels, and confirmation text.
- A quantized local vision-language model interprets unfamiliar layouts and produces a structured state proposal only when the fast detector is uncertain.
- Screen-specific validators combine multiple anchors and reject classifications below their threshold.

The RTX 3060 12 GB GPU is used for local inference. Known-state detection targets sub-second decisions; the vision-language fallback may take several seconds on an unfamiliar screen. The fallback is invoked at decision boundaries, not on every rendered frame.

### 4. Structured FGO state

Perception returns a typed state rather than a raw click:

```text
screen_type
confidence
viewport_signature
visible_controls
quest_markers
quest_identity
resource_indicators
party_and_support_summary
battle_summary
prohibited_regions
```

Every field retains its evidence and confidence. A planner cannot use a field that failed its minimum confidence requirement.

### 5. Local FGO knowledge base

During installation or an explicit update, import the Atlas Academy NA static exports required for:

- servants, classes, cards, skills, and Noble Phantasms;
- class/attribute affinities and battle constants;
- quests, phases, enemy tendencies, and wars where available;
- Craft Essences and Mystic Codes needed by the current party.

The runtime reads a versioned local snapshot and does not query Atlas Academy during gameplay. Imported data is normalized into the agent's own compact read-only database. Data provenance, upstream version, download time, license metadata, and integrity hash are recorded.

Visible evidence remains authoritative. The knowledge base can improve decisions but cannot authorize a click when the screen does not match the expected state.

### 6. Quest graph planner

The quest planner discovers a graph from visible maps and transitions. It does not require `NEXT` to exist.

Candidate discovery considers:

- `NEXT` markers when present;
- uncleared/completed badges;
- quest icons, highlights, glows, and unlock animations;
- quest names and AP-cost panels;
- map-page controls and terminal navigation;
- the result of returning to a map after a clear.

Each candidate is opened and verified against its quest-detail panel before AP is committed. In Do All Quests mode, supported newly unlocked Free Quests receive priority over the next Main Story candidate. Completed quest identities are persisted locally so navigation survives restarts.

### 7. Battle agent

The battle agent runs once per visible decision phase:

1. Identify enemies, classes, HP, break bars where visible, charge gauges, and current target.
2. Identify the active party, status indicators, NP gauges, skill availability, command cards, card types, effectiveness labels, and critical percentages.
3. Combine visible state with the offline servant/skill/NP database.
4. Generate legal tactical action candidates.
5. Score skills, targets, NPs, chains, survival needs, class advantage, expected damage, NP gain, and wave position.
6. Execute the highest-scoring policy-approved action.
7. Re-observe after every skill, target selection, Attack press, and card selection sequence.

The initial policy favors reliability over optimal speed. It must complete early Story and Free Quests consistently before adding advanced looping, min-turn optimization, event gimmicks, or challenge-quest reasoning.

### 8. Policy gate

The policy gate is deterministic and runs after planning but before input. It receives the current observation, proposed semantic action, and target rectangle.

It rejects:

- any action involving Saint Quartz;
- optional, ticket, Quartz, or paid summons;
- purchases, account transfer/login, deletion, Clear Cache, or CAPTCHA;
- clicks outside the mapped Android viewport or inside permanent blocked regions;
- actions derived from stale screenshots or low-confidence state;
- any action when the window guardian is unsafe;
- inputs to any process other than the selected LDPlayer window.

Mandatory free tutorial summons use a narrowly scoped state/action allowlist that expires after the tutorial state is completed.

### 9. Verified action executor

Every input follows one automatic loop:

```text
observe -> interpret -> plan -> policy-check -> one action -> re-observe -> verify
```

Coordinates, object indexes, and proposed controls expire immediately after an action. The executor never replays a timing-only sequence across state changes. Normal loading screens cause a bounded wait and fresh observation, not repeated clicking.

### 10. Local experience store

Persist compact state-transition records:

- perceptual embedding and redacted screen signature;
- structured state and confidence;
- semantic action;
- resulting structured state;
- timing and success/failure classification.

Do not retain raw account identifiers or unrelated-window content. Confirmed transitions improve recognition and loading-time estimates. Runtime experience does not directly rewrite policy-gate rules or perform unsupervised model-weight updates.

Every previously unrecognized screen is saved after privacy redaction, assigned a provisional classification with its evidence, and placed in a quarantined dataset version. It cannot become actionable during the run that discovered it. Promotion into the active recognition set requires deterministic replay and regression tests proving that existing working classifications and policy decisions do not change. Given the same frame, configuration, and dataset version, perception and planning must return the same result.

Battle experience records visible enemy state, available Servant and Master/Mystic Code skills, NP gauges, command cards, chosen actions, damage, wave transitions, victory, and defeat. Updated scoring data is activated only as a new version after replay tests; live experience never mutates the active policy in place.

### 11. Desktop control panel

The UI exposes:

- exact selected LDPlayer target and baseline;
- current mode: Disarmed, Do All Quests, or Farming;
- farming quest identity;
- current screen, quest, wave, confidence, and proposed action;
- AP and permitted refill summary;
- pause reason and recent redacted transitions;
- Arm, Start, Pause, Disarm, Reset Baseline, and Emergency Stop;
- an offline recorded-session replay mode.

The UI never overlays the protected LDPlayer rectangle.

Start, Pause, and Stop must be immediately available to the user whenever the application is open. Pause stops before the next input and is resumable after a fresh safe observation. Stop disarms automation and cannot resume without a new Start action. Emergency Stop remains a terminal fail-closed latch for the current run.

## Tutorial Reconnaissance

The first implementation task after the reusable safety foundation is validated is a supervised reconnaissance pass through the current live tutorial.

For each step:

1. Capture the safe visible LDPlayer frame.
2. Mask account-ID and permanent dangerous regions before any disk write.
3. Record the structured pre-action state.
4. Choose one user-authorized tutorial action.
5. Run the deterministic policy gate.
6. Perform one standard click/tap.
7. Capture and record the resulting structured state.

Always use Skip. Mandatory zero-cost tutorial summons and forced tutorial party/enhancement steps are allowed. Stop before any Saint Quartz, paid, optional summon, account, deletion, or unsupported destructive action.

The reconnaissance output becomes a recorded FGO simulator so completed tutorial screens can be replayed in tests after the live account advances.

## Error Handling and Recovery

- **Loading/network delay:** wait without clicking, re-observe, and retry within a bounded timeout.
- **Transient network dialog:** use a recognized non-destructive retry action and verify the result.
- **Maintenance/update/login:** pause.
- **Unknown screen:** retry capture, run the fast detector, then the local vision-language fallback. Pause if no policy-approved action reaches its confidence threshold.
- **Battle defeat:** save a redacted screenshot and structured battle state, log the likely failure cause, stop all input, and return control to the user. Never use Command Spells or Saint Quartz.
- **AP shortage:** use permitted Apples according to the resource policy. Stop before any Saint Quartz option.
- **Inventory full:** pause in the initial release; do not burn, sell, expand, or move items automatically.
- **Unexpected summon/shop/account screen:** pause and classify as prohibited.
- **Window change, overlap, or focus loss:** pause before another capture or input.
- **Emergency stop:** transition immediately to a terminal stopped state; never resume automatically.

## Testing Strategy

### Unit tests

- target identity, DPI, geometry, focus, overlap, and capture-race handling;
- viewport mapping at negative monitor coordinates and supported DPI scales;
- state schema validation and confidence propagation;
- quest-priority and graph-persistence rules;
- battle candidate legality and deterministic scoring fixtures;
- Apple automation plus permanent Command Spell and Saint Quartz rejection;
- permanent Saint Quartz rejection for every action category;
- stale-observation and wrong-window input rejection.

### Recorded screenshot and transition tests

- every tutorial state observed during reconnaissance;
- maps with and without `NEXT`;
- Main Story, Free Quest, completed, locked, and newly unlocked markers;
- support selection and party confirmation;
- battle phases, variable wave counts, skills, NPs, cards, victory, and defeat;
- Skip and dialogue choices;
- AP refill variants, all Apple types, Command Spell rejection, and Quartz rejection;
- optional/free/Quartz/paid summon distinctions;
- purchases, account transfer, Clear Cache, inventory full, maintenance, unrelated windows, and altered layouts.

### Simulator tests

Replay recorded transitions and require the same semantic action without using raw coordinates. Insert randomized loading durations, small scaling changes, harmless animation frames, and unavailable action candidates.

### Shadow mode

On live LDPlayer, predict and display actions without input for several representative navigation and battle states. Compare predictions with the user's normal play only as validation; this is not per-node training.

### Live autonomous gates

1. Finish the authorized tutorial reconnaissance without a prohibited action.
2. Autonomously complete one supported Main Story quest.
3. Autonomously complete one newly unlocked Free Quest and return to Main Story.
4. Complete a quest with a different wave/turn length without configuration.
5. Farm a selected quest through at least two complete repetitions.
6. Demonstrate an Apple refill in a controlled permitted state.
7. Demonstrate that every Saint Quartz and Command Spell path is rejected before input.
8. Demonstrate global emergency stop during navigation and battle.

## Acceptance Criteria for the First Autonomous Release

The first release is accepted only when:

1. Gameplay requires no cloud service or paid API.
2. Exactly one LDPlayer target is controlled using visible screenshot and standard input only.
3. The agent advances supported Main Story and Free Quests without per-node configuration.
4. Newly unlocked Free Quests are cleared before Main Story resumes in Do All Quests mode.
5. Farming Mode repeats a single selected quest and uses permitted Apples without spending Quartz.
6. Story Skip is used whenever visible, and harmless required choices do not block progression.
7. Support, targets, skills, NPs, and command cards are selected autonomously across variable wave counts.
8. Command Spell and Saint Quartz revival are always rejected.
9. No action can purchase, transfer/delete account data, Clear Cache, use optional summons, or spend Saint Quartz.
10. Every input is derived from a fresh safe observation and followed by outcome verification.
11. Account-ID areas and unrelated-window content are never retained.
12. The emergency stop is globally available and tested.

## Account-Risk Statement

This project does not modify the game or fabricate resources, but visible UI automation may still be considered inappropriate under Aniplex's broad Terms of Use and could lead to account restriction or suspension. The user explicitly accepts this experimental account risk. The project will not include evasion, anti-detection, or claims of undetectability.

## Later Capability Packs

After the first release meets all gates, later specs may add Events, Interludes, Rank Up Quests, Daily Quests, advanced party building, inventory management, high-difficulty gimmicks, and optimized farming strategies. No later category is implicitly authorized by this specification.

## References

- Fate/Grand Order official How to Play: https://fate-go.us/howto/
- Fate/Grand Order official battle guide PDF: https://fate-go.us/howto/pdf/How_to_Play_Fate_Grand_Order_Official_USA_Website.pdf
- Fate/Grand Order North America Terms of Use: https://fate-go.us/terms_of_use/terms_of_use_n_america.html
- Atlas Academy FGO game data API and static exports: https://api.atlasacademy.io/
