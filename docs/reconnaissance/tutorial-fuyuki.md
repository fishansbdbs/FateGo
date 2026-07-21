# Fuyuki Tutorial Reconnaissance

## Environment

- Target: the single window titled `LDPlayer`, executable `C:\LDPlayer\LDPlayer14\dnplayer.exe`, HWND `13831164`, PID `73224`.
- LDPlayer `14.0.15.0`; FGO package `com.aniplex.fategrandorder.en`, version `2.90.2`.
- Physical outer rectangle `(-1930,-1)-(-10,1031)`; client rectangle `(-1926,-1)-(-14,1027)`. Windows DPI is `96`, so physical and logical rectangles are equal.
- Monitor `\\.\DISPLAY1`: `(-1920,0)-(0,1080)`; work area `(-1920,0)-(0,1032)`.
- Android display `1920x1080`, DPI `280`, landscape. Stable mapped game viewport: `(55,40)-(1819,1032)` with titlebar bottom `40` and toolbar left `1819`.
- Session `tutorial-fuyuki-run`: `2026-07-21T07:09:26.307Z` through the last persisted observation at `2026-07-21T09:59:38.147Z`.
- Final live boundary: mandatory tutorial `11x Summon`, visibly labeled `Saint Quartz Cost 30`. It was not clicked or recorded because the sentinel had already changed to `viewport_unobservable:ValueError`; `Ctrl+Shift+F12` then durably wrote `STOPPED=emergency_stop`.

## Ordered transitions

Observation IDs below use their recorder-unique first eight hexadecimal characters. Token values are intentionally eight-character prefixes. Targets are normalized Android-viewport rectangles. `M` is the proposal's mandatory flag.

| # | Before / visible state | Action (resource/cost/mandatory) | Target | Token | After / outcome |
|---:|---|---|---|---|---|
| 1 | `c5a94ed9` TUTORIAL_MAP: NEXT; Touch | `SELECT_QUEST` (`NONE`/0/M=False) | `[0.460,0.430,0.550,0.590]` | `v-MQN4hF` | `d6bb8d17` NEXT NEW |
| 2 | `d6bb8d17` TUTORIAL_MAP: NEXT NEW; Burning City | `SELECT_QUEST` (`NONE`/0/M=False) | `[0.500,0.150,0.960,0.390]` | `S07F2oRF` | `78d82799` SKIP |
| 3 | `78d82799` STORY: SKIP; ??? | `SKIP_STORY` (`NONE`/0/M=False) | `[0.870,0.020,0.990,0.120]` | `RSIuT0Tm` | `62e6ec11` Skip confirmation |
| 4 | `62e6ec11` SKIP_CONFIRM: Skip this Cutscene?; Yes | `CONFIRM_SKIP` (`NONE`/0/M=False) | `[0.540,0.720,0.760,0.840]` | `cgPq1oad` | `5977f31b` forced card tutorial |
| 5 | `5977f31b` BATTLE: Green Card; Red Card | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.730,0.570,0.860,0.830]` | `_krNXZF_` | `91ceac08` Attack prompt |
| 6 | `91ceac08` BATTLE: Touch; Attack | `ATTACK` (`NONE`/0/M=False) | `[0.800,0.700,0.980,0.980]` | `WhPtuW2m` | `81cfb9e0` card phase |
| 7 | `81cfb9e0` BATTLE: Touch; Quick | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.030,0.500,0.180,0.880]` | `_zHiwWgv` | `e58e5f5a` Quick first |
| 8 | `e58e5f5a` BATTLE: Quick first; Buster | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.230,0.500,0.380,0.880]` | `mjKfLO9f` | `0a8497c9` Buster second |
| 9 | `0a8497c9` BATTLE: Buster second; Empty | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.430,0.500,0.570,0.880]` | `WAqBIu5r` | `5151b2bc` skill prompt |
| 10 | `5151b2bc` BATTLE: tap icon; Mash left skill | `USE_SKILL` (`NONE`/0/M=False) | `[0.020,0.720,0.100,0.870]` | `nK4et0Zk` | `5acf2853` left skill prompt |
| 11 | `5acf2853` BATTLE: Mash left skill | `USE_SKILL` (`NONE`/0/M=True) | `[0.020,0.720,0.100,0.870]` | `J02C3Xb8` | `e4697114` right skill prompt |
| 12 | `e4697114` BATTLE: Mash right skill | `USE_SKILL` (`NONE`/0/M=True) | `[0.110,0.720,0.170,0.870]` | `x6vVAMnz` | `034a8753` OK prompt |
| 13 | `034a8753` BATTLE: OK; Cancel | `USE_SKILL` (`NONE`/0/M=True) | `[0.500,0.550,0.760,0.660]` | `CtJidYz3` | `f95f735d` target prompt |
| 14 | `f95f735d` BATTLE: Select Target; Mash | `SELECT_TARGET` (`NONE`/0/M=True) | `[0.380,0.450,0.580,0.790]` | `alx28Vhh` | `db7507ca` Attack prompt |
| 15 | `db7507ca` BATTLE: Attack; skill cooldown tutorial | `ATTACK` (`NONE`/0/M=True) | `[0.740,0.690,0.940,0.990]` | `Yxi-9z4d` | `b8ec0e4c` battle-speed prompt |
| 16 | `cb78a7fd` TUTORIAL_PROMPT: BATTLE SPEED | `ADVANCE_TUTORIAL` (`NONE`/0/M=True) | `[0.750,0.040,0.900,0.190]` | `r61yT-Xz` | `54bd6ceb` forced card phase |
| 17 | `54bd6ceb` BATTLE: Buster; Arts | `SELECT_COMMAND_CARD` (`NONE`/0/M=True) | `[0.030,0.550,0.190,0.900]` | `XmC9E7TX` | `c77bdb47` Buster first |
| 18 | `c77bdb47` BATTLE: Buster first; Arts | `SELECT_COMMAND_CARD` (`NONE`/0/M=True) | `[0.220,0.550,0.390,0.900]` | `2vr723Q-` | `0a4fb4d0` Arts second |
| 19 | `0a4fb4d0` BATTLE: Buster first; Arts second | `SELECT_COMMAND_CARD` (`NONE`/0/M=True) | `[0.390,0.550,0.560,0.900]` | `8aI31gFZ` | `d999dcf2` Servant Bond |
| 20 | `d999dcf2` QUEST_RESULT: Servant Bond | `COLLECT_RESULT` (`NONE`/0/M=True) | `[0.300,0.820,0.700,0.980]` | `O3tUs7hA` | `461eea06` EXP Gained |
| 21 | `461eea06` QUEST_RESULT: EXP Gained | `COLLECT_RESULT` (`NONE`/0/M=True) | `[0.300,0.820,0.700,0.980]` | `Vo40-qH8` | `4d841021` Items Dropped |
| 22 | `4d841021` QUEST_RESULT: Items Dropped; Next | `COLLECT_RESULT` (`NONE`/0/M=True) | `[0.700,0.820,0.940,0.980]` | `FfAL6wgA` | `0a2b8619` post-battle story |
| 23 | `0a2b8619` STORY: SKIP; Mash | `SKIP_STORY` (`NONE`/0/M=True) | `[0.810,0.020,0.940,0.140]` | `BeMW7Pw4` | `e9b71b78` skip confirmation |
| 24 | `e9b71b78` SKIP_CONFIRM: No; Yes | `CONFIRM_SKIP` (`NONE`/0/M=True) | `[0.500,0.700,0.720,0.840]` | `SEHdBGeD` | `4f2bb7bd` quest-clear rewards |
| 25 | `4f2bb7bd` QUEST_RESULT: Quest Clear Rewards | `COLLECT_RESULT` (`NONE`/0/M=True) | `[0.300,0.820,0.700,0.980]` | `WUpwyITV` | `a6373fe6` X-B map node |
| 26 | `a6373fe6` TUTORIAL_MAP: NEXT; X-B | `SELECT_QUEST` (`NONE`/0/M=True) | `[0.440,0.490,0.580,0.680]` | `x90J40ab` | `27058484` Section 2 |
| 27 | `27058484` TUTORIAL_PROMPT: NEXT; NEW | `ADVANCE_TUTORIAL` (`NONE`/0/M=True) | `[0.480,0.130,0.960,0.390]` | `FZgi8pq8` | `aa12d30f` story |
| 28 | `aa12d30f` STORY: Skip; Mash | `SKIP_STORY` (`NONE`/0/M=False) | `[0.870,0.010,0.990,0.110]` | `EzUYYHRl` | `70696757` skip confirmation |
| 29 | `70696757` SKIP_CONFIRM: No; Yes | `CONFIRM_SKIP` (`NONE`/0/M=False) | `[0.540,0.720,0.780,0.850]` | `H7kGqHwy` | `669d6ef7` Battle 1/2 |
| 30 | `669d6ef7` BATTLE: Battle 1/2; one enemy | `ATTACK` (`NONE`/0/M=False) | `[0.800,0.690,0.990,0.990]` | `YbfCqdMj` | `e1984183` card phase |
| 31 | `e1984183` BATTLE: Arts; Quick | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.020,0.530,0.200,0.900]` | `W8X8jRlf` | `b0c9c6f1` Arts first |
| 32 | `b0c9c6f1` BATTLE: Arts first; Quick | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.230,0.520,0.400,0.900]` | `NuwNzrLn` | `0bca0f35` Quick second |
| 33 | `0bca0f35` BATTLE: two cards selected | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.430,0.520,0.580,0.900]` | `DEijB9fk` | `5fc4ce9c` Battle 2/2 |
| 34 | `5fc4ce9c` BATTLE: two enemies; forced target | `SELECT_TARGET` (`NONE`/0/M=True) | `[0.160,0.260,0.320,0.630]` | `-jIOkhbY` | `45555c79` target selected |
| 35 | `45555c79` BATTLE: Battle 2/2; Attack | `ATTACK` (`NONE`/0/M=False) | `[0.800,0.690,0.990,0.990]` | `p-uk1gF2` | `893edb05` critical-star tutorial |
| 36 | `893edb05` BATTLE: Buster; Buster | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.020,0.530,0.200,0.900]` | `Y1Pn8Xyg` | `f63f444f` first Buster |
| 37 | `f63f444f` BATTLE: first Buster; second Buster | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.230,0.520,0.400,0.900]` | `ORK2ST3x` | `6e66ee84` two cards selected |
| 38 | `6e66ee84` BATTLE: highlighted Empty third slot | `SELECT_COMMAND_CARD` (`NONE`/0/M=True) | `[0.430,0.520,0.580,0.900]` | `esvQ7cIN` | `e35c4d09` one enemy remains |
| 39 | `e35c4d09` BATTLE: Turn 3; Attack | `ATTACK` (`NONE`/0/M=False) | `[0.800,0.690,0.990,0.990]` | `2Js91jtl` | `de40da85` final card phase |
| 40 | `de40da85` BATTLE: Quick; Arts; Buster | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.430,0.520,0.580,0.900]` | `x_uZppKw` | `7505c23f` Buster first |
| 41 | `7505c23f` BATTLE: Buster first; Arts | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.230,0.520,0.400,0.900]` | `iw_uAYi5` | `090a5ee6` Arts second |
| 42 | `090a5ee6` BATTLE: Quick third | `SELECT_COMMAND_CARD` (`NONE`/0/M=False) | `[0.020,0.530,0.200,0.900]` | `47SaY_EC` | `30318213` Servant Bond |
| 43 | `30318213` QUEST_RESULT: Servant Bond | `COLLECT_RESULT` (`NONE`/0/M=False) | `[0.440,0.820,0.650,0.980]` | `qhPKprrB` | `2bdf0a94` EXP Gained |
| 44 | `2bdf0a94` QUEST_RESULT: EXP Gained | `COLLECT_RESULT` (`NONE`/0/M=False) | `[0.440,0.820,0.650,0.980]` | `2zLUz0R2` | `5b24a7bf` Items Dropped |
| 45 | `5b24a7bf` QUEST_RESULT: QP +30000; Next | `COLLECT_RESULT` (`NONE`/0/M=False) | `[0.730,0.830,0.990,0.970]` | `7lyTzt5j` | `f293279a` story |
| 46 | `f293279a` STORY: Skip; Mash | `SKIP_STORY` (`NONE`/0/M=False) | `[0.870,0.010,0.990,0.110]` | `8AiBLcwM` | `4b28a60b` skip confirmation |
| 47 | `4b28a60b` SKIP_CONFIRM: No; Yes | `CONFIRM_SKIP` (`NONE`/0/M=False) | `[0.540,0.720,0.780,0.850]` | `Sempxwpi` | `47363189` reward receipt |
| 48 | `47363189` QUEST_RESULT: You got Saint Quartz x1 | `COLLECT_RESULT` (`NONE`/0/M=False) | `[0.440,0.820,0.650,0.980]` | `azfR4bBq` | `98581c14` Main Menu prompt |
| 49 | `98581c14` TUTORIAL_PROMPT: tap MENU | `ADVANCE_TUTORIAL` (`NONE`/0/M=True) | `[0.840,0.840,0.990,0.985]` | `fXQSBc1_` | `251da5bb` proceed to Summon |

The final allowed action token `-IZk5Bh...` opened the forced Summon page from observation `obs-251da5bbbabb491082c063c07ed03c5a`. Its post-action observation was not persisted because the viewport mapper paused before capture. That transition is deliberately incomplete and the dataset is therefore a valid completed prefix plus one safety-blocked tail, not a completed tutorial dataset.

## New reusable UI concepts

- Map: `NEXT`/`NEW` node callouts are useful but not guaranteed; node labels and Section panels are stronger anchors. The map can surface a forced tutorial overlay independently of node progression.
- Story: top-right `Skip` leads to a centered `Skip this Cutscene?` modal with `No` and `Yes`. Always choose Skip, then Yes.
- Support/party: the early forced tutorial path did not expose reusable support or party-selection layouts in this run.
- Battle: Attack phase, command-card phase, enemy target selection, skill icon, skill confirmation, Servant target modal, battle-speed control, forced Empty card slot, wave counter, enemy count, and result chain were all observed.
- Results: Servant Bond, EXP Gained, Items Dropped/Next, and Quest Clear Rewards/Please Tap the Screen are separate states. Reward text can say `You got Saint Quartz`; receiving that reward is distinct from spending Quartz.
- Main menu/tutorial: forced overlays can require `MENU`, `Summon`, and other bottom-menu destinations. A tutorial banner does not imply zero cost.
- Loading/network: black transitions and animated panels can temporarily make the viewport unobservable. The correct behavior is no input and automatic pause/recovery.
- Summon: the observed forced page showed `Saint Quartz Cost 30`; it is not the zero-cost tutorial-summon case supported by policy.

## Stops and anomalies

- Two denied proposals were persisted: a battle-speed prompt initially classified as `BATTLE` (`action_not_valid_for_screen`), then safely recaptured as `TUTORIAL_PROMPT`; and the reward-receipt tap initially denied by a conservative `saint_quartz_forbidden` label rule.
- The reward false positive was corrected test-first with a narrow exception: only `QUEST_RESULT` + `COLLECT_RESULT` + resource `NONE` + cost `0`, with every Quartz-bearing state label exactly matching `You got Saint Quartz x <digits>` after normalization, can pass. Quartz in the action, resource, or added spend wording still fails.
- Several animated/loading frames temporarily produced titlebar/toolbar ambiguity. Mapper changes retained exact signatures while canonicalizing only credible Sobel plateaus and keeping genuinely separate edges ambiguous.
- A focus-loss incident created a fail-closed STOPPED latch before a planned card click. No click occurred; LDPlayer alone was reactivated, the audit latch was preserved, and a new sentinel was started only after the reviewed recovery procedure.
- The session preserves all prior STOPPED/VIEWPORT_PAUSED audit files. No material audit artifact was deleted.
- Final outcome: the forced tutorial demanded `Saint Quartz Cost 30`. No summon click occurred. The mapper pause blocked recorder mutation, and the global emergency hotkey created durable `STOPPED=emergency_stop`; both sentinel processes exited.
- Counts at stop: 51 observations, 52 action attempts (50 allowed, 2 denied), 49 completed transitions, and one allowed transition intentionally incomplete at the prohibited summon boundary.
