# WP3 - Combat rules of Watchmen: The End Is Nigh (Part 2 build, `KapowMultiDEDRM.exe`)

Companion data: `findings/wp3_combat_tables.json` (attack states, combos, damage-pose rules, reaction tables, health/damage constants, weapons, pair triggers).

Evidence labels used throughout:

- **[code]** read from the lifted script handler named (address = handler entry in the exe). Numeric constants were re-read from exe bytes with `rd`; the address is given.
- **[data]** read from the binary `.fragment` files on the PC (parsed with `kapow_fragment`), not from the stale `*.fragment.json`.
- **[default]** property default from the script-class registry (`tk160/wlib/reg_dump.json`); a fragment may override it.
- **[inferred]** follows from code + data but the connecting step was not read.
- **[not established]** listed again in section 8.

Abbreviations: CRL = `CharacterRootLogic`, CR = `CharacterRoot`, PC = `PlayerCtrl`, CO = `CombatOrchestrator`. "dz" = `_nissuedattackdeadzonetime`. Times are game seconds unless "real time" is stated.

## 0. Coverage

Lifted classes read for this report (lines of lifted text): CharacterRootLogic 12675 (every handler; of the animation-event dispatcher the cases BRANCH, CLEAR_DEADZONE, IMPACT, PRE_IMPACT, EXTEND_COMBO_TIME, KILL_ANIMATION_PARTNER, DIE, BULLMOVE_IMPACT were read, the rest skimmed), CharacterRoot 15441 (combat commands, give_damage, DecreaseHealth, UpdateHealth, StateActive combat parts, weapon commands; StateDead at call level only), PlayerCtrl 4907, ProjectAnimationLib 519 (all), CharacterComboDatabase 577, CharacterComboString (partly), CharacterAIComboManager 568, EnemyDef (DRS build, damage modifier), Enemy (react_to_attack, hit_by, is_attack_successful), BehaviorHandler (combat interface), CombatOrchestrator (attack_animation_stated, repel, force_lock_target), WeaponBase / WeaponLib (pickup, durability), CharacterSweepAttack (begin only), CharacterVisual.command_update_animation (TARGET_MODE part), AchievementCtrl / AchievementPart2Ctrl (handler list only).

Binary fragments parsed: `GameEssentials/CharacterDef.fragment` (12 combo databases, 77 combo strings, CharacterSpecialDef), 14 CharacterDefs and 31 AI definitions under `Enemy/*.fragment`, the 45 `GameEssentials/CharacterAnimation/*.fragment` files (1290 states over the five animation classes, all matched one-to-one to `anim_meta_v2.json`), `GameEssentials/WeaponDB/WeaponDB.fragment` (21 weapons), `GameEssentials/PlayerCtrl.fragment`, `GameEssentials/Debug.fragment`.

Corrections to the earlier Dominatrix audit (`dominatrix_audit.md`):

1. The defender's reaction table (DRS) is evaluated when the attacker **enters** an attack state (`CombatOrchestrator.command_attack_animation_stated` 0x6e6495, called from `CRL.start_animation_state` 0x688961), not at PRE_IMPACT. [code]
2. Tactical flag 0x400 is `PLACEMENT_REAR` (no reaction when the attacker is behind), 0x200 is `PLACEMENT_FRONT`. [code + enum]
3. The finisher prompt rolls one of 3 buttons on PC/editor (DEFEND, ATTACK_0, ATTACK_1) and one of 4 on consoles (adds ATTACK_2). [code, CR.DecreaseHealth 0x695632]
4. A counter needs no special "fourth attack": it needs the target to be attacking you (or to have just been dodged) and at least 0.13 s left before its IMPACT (section 2.3).

## 1. Player input to action

### 1.1 Buttons [code: `PlayerCtrl.StateActiveDefault` 0x7f5365]

Runs each frame only while the hero is alive, the time multiplier is > 0 and input is active.

| Logical button | Rorschach | Nite Owl | Gate |
|---|---|---|---|
| 21 ATTACK_0 | fast attack (`CRL.command_attack_fast` 0x686495) | same | - |
| 22 ATTACK_1 | heavy attack (`command_attack_slow` 0x68658d) | same | - |
| 23 ATTACK_2 | throw (`command_attack_throw` 0x686619); if a weapon is held also fires DROP_WEAPON (27) | same (no weapons) | ability 1 THROW; thrown only if there is a next target or no weapon |
| 24 USE | pick up nearest weapon | - | Rorschach only (`_icharactertype == 0`) |
| 25 SPECIAL_ATTACK_1 | bull rush (`command_attack_charge` 0x687789) | stun grenade (action 17) | ability 5 (RUSH / GRENADE) |
| 26 COUNTER_ATTACK | `command_counter_attack` 0x68664c | same | (combo route needs ability 3) |
| 27 SPECIAL_ATTACK_2 | uber rage (action 28 START_UBER_RAGE) | electrify armour (action 18) | ability 6 (RAGE / ELECTRIC_BLAST) |
| 28 DEFEND | dodge / step-around (press) | block (hold) | ability 2 (DODGE / BLOCK) |

Every press first runs `PlayerCtrl.CheckFinishMove(button)` 0x7eff13 (section 3.2); only if that does not consume the press does the normal action run. The pressed button is remembered in `m_ilastbuttonpressed`. Before an attack the hero's `m_enextattacktarget` is set to the current soft target (if there is a target, or if he is not already attacking).

Targeting [code, same handler; values **[default]** or **[data]** `PlayerCtrl.fragment`]: the soft target is `brain.get_target_empty_ignore(heading, m_ntargetconeangle = 180 deg, m_ntargetrangemax = 6.0 m)`; the heading is the stick direction when stick deflection > `m_ntargetfaceheading` 0.25, otherwise the facing direction. A target lock is taken automatically (`_tusetargetlocking` = true) on a target within `_ntargetlockdistance` 5.0 m while in combat mode and the current state does not set `m_tignoretargetlock`; it is dropped beyond 5.0 m. `PlayerCtrl.command_hit_by` 0x7f900e locks onto whoever hits the hero.

Dodge (Rorschach) [code]: on DEFEND, if the hero was hit less than 0.5 s ago the dodge dead-zone timer is reset. If the stick is pushed (> 0.7) towards the locked/soft target (dot > 0.7) the action is a **step-around** (`command_attack_step_around`, 0.7 s cooldown, 0xa3aff8; stuns the target for `m_nsteparoundstunduration` 1.51 s [data]); otherwise `CRL.command_dodge` 0x686a17. A dodge with nobody to dodge starts a dead zone `_ndodgedeadzone` 0.4 s [data]. A dodge is refused while `now < m_nextraclearzonetime`, and while already in a DODGE state before 50% of it has played.

Block (Nite Owl) [code]: while DEFEND is down and `_tdisallowblock` is clear, `CR.command_block` is sent every frame (`CRL.command_block` 0x686e56). Blocking needs electrify power > 0; each blocked hit costs `m_nelectrifyblockenergycost` 0.04 [data]. Releasing the button clears the block lock. A block breaker sets `_tdisallowblock` until release.

### 1.2 Control actions

Animation states are selected by firing `CONTROL_ACTION_TYPES` actions into the animation controller. The ones combat uses: 0 PUNCH (light), 7 HEAVY_PUNCH, 1 NORMAL_ATTACK (always fired with 0/7), 21 INITIAL_ATTACK (first attack of a string), 25 AFTER_DASH_ATTACK, 4 THROW, 5 THROW_GRAB_FAILED, 3 FINISHING_MOVE, 29 KILL_PRONE_TARGET, 12 COUNTER_ATTACK, 6 BULLMOVE, 11 DODGE, 19 STEP_AROUND_ATTACK, 20 BLOCK, 22 INITIALIZE_BLOCK, 2 HITTAKEN, 30 ATTACK_BLOCKED, 14 ONE_FRAME_ACTION (fired before every one-shot), 16 IDLE_ALLOWED, 17 THROW_GRENADE, 18 ELECTRIFY_ARMOR, 26 STEP + 13 STICK_FLICK, 27 DROP_WEAPON, 28 START_UBER_RAGE.

### 1.3 Attack queue and buffer [code: `CRL.ExecuteAttack` 0x68b351, `StateCharacterRootLogic` 0x68abab, `IsInterruptAttack` 0x677567]

- An attack press is **dropped** when the current state disallows attacks (`m_tdisallowattack`) unless it is buffered: it is stored as the single *pending attack* when dz is older than 2.0 s (0xc3cc78) or the current state is a dodge/step-around (special handling 5 / 11).
- While an attack is playing, further presses are appended to the combo list; at most 3 entries are queued (`count > 2` returns). With the shipped `CharacterDebug` settings `m_tuselatestpunches = true`, `m_tenablecombos = true` [data, `Debug.fragment`] the queue holds one attack beyond the current one and the **latest press replaces it**.
- A press within 1.0 s (0xc3cc48) of dz that is not an "interrupt attack" is dropped. An interrupt attack is a player press within 0.3 s (f64 0xa00178) of the last attack and within 1.0 s of dz with at least one attack already in the string; it cuts the current attack short.
- The pending attack / pending special is executed by the per-frame state as soon as the state allows attacks and no partner is stored; the target is re-resolved at that moment. A pending special is also started at the end of a state if it was pressed within the last 0.5 s (`end_animation_state` 0x68a371).
- The queued next attack is actually launched by the **BRANCH** animation event of the current attack (`command_animation_event_received` 0x6a525e): re-target (dead targets are dropped), `FireAttackBasedOnAttackID` + `InitializeNextAttack`. With nothing queued, BRANCH starts a 0.2 s (f64 0x9e97e8) countdown after which the attack data (target, combo list, unblockable flag) is cleared.

### 1.4 Combo timing windows [code: `CRL.update_combo_timing` 0x68810a, `DoComboTimingTrim` 0x68b1ad, event cases]

- Each attack state carries CLEAR_DEADZONE, PRE_IMPACT, IMPACT, BRANCH and CAN_GO_TO_MOVEMENT events (times per state in the JSON, `attack_states.*.times_from_state_entry_s`). Rorschach unarmed light attacks: IMPACT 0.18-0.41 s after entry for a first attack, 0.39-0.54 s for later ones, BRANCH 0.10 s after IMPACT, free movement about 0.3 s after BRANCH.
- CLEAR_DEADZONE re-opens input: dz is set to -2 if there is a target (so the next press is accepted immediately), else to now - 0.8. It also starts the weapon trail and re-evaluates the longest valid combo string.
- A string stays alive while `now < _nnextvalidcombotime`. That time is pushed to now + 0.7 s (f64 0xa3aff8) by every landed hit, to at least now + 0.15 s (f64 0x9eb188) while an attack or a `m_tkeepcomboalive` state plays, to now + 1.0 s by a paired-move impact, to now + 0.5 s by a dodge/block that breaks out of a grab, and to now + value by an EXTEND_COMBO_TIME event (1.01 s on counters, finishers, throw). When it expires the combo list is cleared.
- The window for the next press is `[IMPACT - _ncleardeadzoneoverride (0.3 s [default]), IMPACT)` for the whoosh/timing feedback; a mistimed player press clears the combo list (unless the last item was a KICK).
- Combo speed-up: when an attack is entered as a continuation, the state is started at the playpos of its CLEAR_DEADZONE event minus 0.15 s (light) or 0.2 s (heavy) (`start_animation_state`; states flagged `m_timmunetocombospeedup` are exempt). This is why later hits of a string come out faster than the first.

### 1.5 Combo strings [code: `CharacterComboDatabase.get_longest_valid_combo` 0x66cd98, `trim_combo_list` 0x665792, `CRL.AddAttackToCombo` 0x68bca8, `InitializeNextAttack` 0x68bf6f; data: `CharacterDef.fragment`]

Each press appends a combo item: fast -> item 1/2/3 and heavy -> item 4/5/6 by held weapon class (unarmed / 1H / 2H); throw -> 14; **any attack against a prone target -> 16 KICK**. Specials map as: dodge/step-around -> 11 (only if someone is in the dodge list), block -> 12, counter -> 13, bull rush -> 7, grenade -> 9, electrify/rage -> 10, finisher -> 15.

The database is searched for the longest string that equals the **tail** of the pressed list (item equal and target-status mask matching; strings sorted longest first). Player strings whose node is disabled (locked ability) are skipped unless all abilities are unlocked. When the pressed list is no longer a prefix of any string, the oldest presses are dropped.

A string does not have animations of its own. Its effect when it completes:

- `m_iforcespecialanimation` is written to animation enum 8 `OVERRIDE_ATTACK_COMBO`, which makes the **last attack of the string** choose its state from the KnockDowns / Stuns / AreaDamage / SuperDamage group instead of the general group (group criteria in section 1.6).
- At the hit: bonus damage `m_ndamage`, stun `m_nstunduration`, push-back `m_npushbackvel` for `m_npushbacktime`, and the damage pose is converted (override STUN -> stun poses, HEAVY_DAM -> heavy poses). `m_tterminatecombo` clears the list.
- Special overrides: 4 FINISHING_MOVE -> finisher/stomp; 7 KILL_PRONE_TARGET -> action 29; 6 COUNTER_ATTACK -> counter (target chosen from the dodge list by stick direction and distance; if the target's health <= counter damage it becomes a finisher - section 3.2).
- A multi-item string, uber rage, electrified charges or a held weapon (except throws) make the attack **unblockable** (`start_animation_state`).

Rage / electricity gained per hit of a string that has a combo set up: `m_nragebonuscombohit` 0.021 (Rorschach) or `m_nelectrifybonuscombohit` 0.03 (Nite Owl); on the completing hit `m_nragebonuscombocomplete` 0.038 / `m_nelectrifybonuscombocomplete` 0.04 [data; which of the two bonus fields is applied on the completing hit was read as special+0x40 / +0x60 in `SetCloseCombatDamageToTarget`].

**Rorschach Combos** - base damage fast unarmed/1H/2H 5/15/25, heavy 12/25/35, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| DODGE | - | 0 | 0 | - | no | 2 |
| THROW | - | 0 | 0 | - | no | 1 |
| H (target KNEE) | KNOCKDOWN | 0 | 0 | - | yes | 0 |
| DODGE , F | COUNTER_ATTACK | 0 | 1 | - | yes | 3 |
| DODGE , F1h | COUNTER_ATTACK | 0 | 1 | - | yes | 3 |
| DODGE , F2h | COUNTER_ATTACK | 0 | 1 | - | yes | 3 |
| BULL_RUSH | - | 0 | 0 | - | no | 5 |
| ELECTRIFY/RAGE | - | 0 | 0 | - | no | 6 |
| H , H , H | KNOCKDOWN | 0 | 1 | 4 for 0.3 | yes | 8 |
| H , F , H | KNOCKDOWN | 0 | 1 | 4 for 0.3 | no | 9 |
| F , F , F , F | STUN | 0 | 6 | - | yes | 10 |
| F , H , F | STUN | 0 | 6 | - | no | 11 |
| H , F , F , H | AREA_DAMAGE | 0 | 0 | - | no | 12 |
| F , H , H | AREA_DAMAGE | 0 | 0 | - | no | 13 |
| H , H , F , F , H | SUPER_DAMAGE | 20 | 3 | - | yes | 14 |
| H , H , F , F , F , H | SUPER_DAMAGE | 50 | 6 | 4 for 0.25 | yes | 15 |
| KICK , KICK , KICK | KILL_PRONE_TARGET | 0 | 0 | - | yes | 4 |

**Nite Owl Combos** - base damage fast unarmed/1H/2H 5/15/25, heavy 12/25/35, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| BLOCK | - | 0 | 0 | - | no | 2 |
| THROW | - | 0 | 0 | - | no | 1 |
| H (target KNEE) | KNOCKDOWN | 0 | 0 | - | yes | 0 |
| BLOCK , F | COUNTER_ATTACK | 0 | 1 | - | yes | 3 |
| GRENADE | - | 0 | 0 | - | no | 5 |
| ELECTRIFY/RAGE | - | 0 | 0 | - | no | 6 |
| ELECTRIFY/RAGE | - | 0 | 0 | - | no | 7 |
| H , H , H | KNOCKDOWN | 0 | 1 | 4 for 0.3 | yes | 8 |
| H , F , H | KNOCKDOWN | 0 | 1 | 4 for 0.3 | yes | 9 |
| F , H , F | STUN | 0 | 6 | - | yes | 10 |
| F , F , F | STUN | 0 | 6 | - | yes | 11 |
| F , H , H | AREA_DAMAGE | 0 | 0 | - | no | 12 |
| F , H | AREA_DAMAGE | 0 | 0 | - | no | 13 |
| H , F , F , H | SUPER_DAMAGE | 30 | 3 | - | yes | 14 |
| H , H , F , F , H | SUPER_DAMAGE | 60 | 6 | 4 for 0.25 | yes | 15 |
| KICK , KICK , KICK | KILL_PRONE_TARGET | 0 | 0 | - | yes | 4 |

**Enemy Combos** - base damage fast unarmed/1H/2H 5/12/15, heavy 10/20/25, counter 10, throw 10

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| F , DODGE , H | - | 0 | 0 | - | yes | - |
| F1h , F1h , H1h | - | 0 | 0 | 0 for 0.4 | yes | - |
| F , F , H | - | 0 | 0 | 0 for 0.4 | yes | - |
| F , F , F , F | - | 0 | 0 | - | yes | - |

**Big Enemy Combos** - base damage fast unarmed/1H/2H 10/15/20, heavy 15/20/25, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| F , H | - | 0 | 0 | - | yes | - |
| F1h , H1h | - | 0 | 0 | - | yes | - |

**Twilight Lady Combos** - base damage fast unarmed/1H/2H 3/15/20, heavy 9/20/25, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| H | SUPER_DAMAGE | 10 | 0 | - | yes | - |
| H | AREA_DAMAGE | -4 | 0 | - | yes | - |
| F , F , F , F , H | KNOCKDOWN | 5 | 0 | - | yes | - |
| F , H | STUN | 0 | 0 | 8 for 0.5 | yes | - |

**Rorschach AI Combos1** - base damage fast unarmed/1H/2H 5/15/25, heavy 12/25/35, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| F , H | - | 0 | 0 | - | no | 0 |
| F , F | - | 0 | 0 | - | no | 0 |
| H , F , H | - | 0 | 0 | - | no | 0 |
| H , F , F , H | AREA_DAMAGE | 0 | 0 | - | no | 0 |
| F , F , F , F | STUN | 0 | 0 | - | no | 0 |

**Rorschach AI Combos3** - base damage fast unarmed/1H/2H 3.06/15/25, heavy 8.89/25/35, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| H , F , F , H | SUPER_DAMAGE | 20 | 0 | - | yes | 0 |

**Rorschach AI Combos5** - base damage fast unarmed/1H/2H 3.06/15/25, heavy 8.33/25/35, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| H , F , F , H | SUPER_DAMAGE | 15 | 0 | - | yes | 0 |
| H , F , H , H , H | SUPER_DAMAGE | 25 | 0 | - | yes | 0 |
| F , F , F , H | AREA_DAMAGE | 10 | 0 | - | yes | 0 |

**Nite Owl AI Combos1** - base damage fast unarmed/1H/2H 5/15/25, heavy 12/25/35, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| F , H | - | 0 | 0 | - | no | 0 |
| F , F | - | 0 | 0 | - | no | 0 |
| H , F | - | 0 | 0 | - | no | 0 |
| F , F , H | AREA_DAMAGE | 0 | 0 | - | no | 0 |
| F , F , F , F | STUN | 0 | 0 | - | no | 0 |

**Nite Owl AI Combos3** - base damage fast unarmed/1H/2H 3/15/25, heavy 9/25/35, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| F , F , H | KNOCKDOWN | 0 | 0 | - | no | 0 |
| H , F , H | KNOCKDOWN | 0 | 0 | - | no | 0 |

**Nite Owl AI Combos6** - base damage fast unarmed/1H/2H 4/15/25, heavy 10/25/35, counter 20, throw 15

| Inputs | Result animation group | Bonus dmg | Stun s | Push m/s for s | Terminates string | Ability id |
|---|---|---|---|---|---|---|
| F , H | - | 0 | 0 | - | no | 0 |
| F , F , H | KNOCKDOWN | 0 | 0 | - | no | 0 |
| F , F , F , H | SUPER_DAMAGE | 0 | 0 | - | no | 0 |

**Underboss Combos** - base damage fast unarmed/1H/2H 10/15/20, heavy 15/25/25, counter 20, throw 15


Ability ids: 1 THROW, 2 DODGE/BLOCK, 3 COUNTER, 4 STOMP/TASER, 5 RUSH/GRENADE, 6 RAGE/ELECTRIC_BLAST, 7 (Nite Owl) electric discharge, 8-15 the eight learnable combos, 16-25 meter upgrades (+0.1 max each). The disabled strings with ability 16-21 are the empty "Pickup" placeholders. AI partner databases ("... AI Combos1/3/5/6") are selected by the partner definitions.

### 1.6 Which animation plays for a step [data: group criteria in the `*AttackFragment.fragment` files; selection code is the generic animation controller]

Attack states are grouped; a state can be entered only if all criteria of its groups and its own criteria hold, and inside a group flagged `_trandomizetransitiontostate` the state is picked at random among those that pass. So a "combo step" is: *button class* (PUNCH / HEAVY_PUNCH) x *weapon class* (UNARMED / BASH_1H / BASH_2H) x *first or later attack* (INITIAL_ATTACK / AFTER_DASH_ATTACK groups vs general groups) x *combo override* (KNOCKDOWN / STUN / AREA_DAMAGE / SUPER_DAMAGE groups) x *target mode* (PRONE -> Kicks group; enum 7 TARGET_MODE is written every frame by `CharacterVisual.command_update_animation` 0x69b988: -1 none, 0/1 target in combat, 2 dead, 3 stunned or on knee, 4 prone [code]) x *geometry* (ATTACK_MOVE_DIST, ANGLE_TO_TARGET for the turn-left/right/back groups, VERTICAL_HEIGHT_TO_TARGET per state). If the target is out of range the `RushToAttack` state (special handling RESEND_PUNCH_WHEN_IN_RANGE) runs towards it and re-issues the attack after 0.4 s (f64 0x9eb790) as AFTER_DASH_ATTACK (`CRL.do_special_state_handling` 0x687bc5).

**Rorschach** (94 attack states)

| Group | States | Group criteria (all must hold; [entry] = only tested on entry) | IMPACT s from entry (min-max) | Reach m (min-max) |
|---|---|---|---|---|
| OneFrameActionGroup | 1 |  | 0.63-0.63 | 1.26-1.26 |
| RushToCounterAttack | 1 | ANY OF(ACTION COUNTER_ATTACK [entry]|ALL OF(NITE_OWL [entry]|ACTION FINISHING_MOVE [entry]|NOT PLAYER_VS_PLAYER [entry]) [entry]) [entry] | - | 2.25-2.25 |
| Rorshack/HeavyAttack/Kicks | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; PRONE [entry] | 0.28-0.47 | 0.89-2.57 |
| Rorshack/HeavyAttack/KnockDowns/Heavy Knockdowns | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; KNOCKDOWN ; NOT PRONE [entry] | 0.44-0.44 | 1.22-1.22 |
| Rorshack/HeavyAttack/SuperDamage | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; SUPER_DAMAGE ; NOT KNOCKDOWN ; NOT PRONE [entry] | 1.48-1.50 | 1.50-1.70 |
| Rorshack/HeavyAttack/AreaDamage | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; AREA_DAMAGE ; NOT KNOCKDOWN ; NOT PRONE [entry] | 0.95-0.95 | 1.75-1.75 |
| Rorshack/HeavyAttack/Stuns | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; STUN ; NOT PRONE [entry] ; NOT KNOCKDOWN | 0.68-0.82 | 1.22-1.45 |
| Rorshack/HeavyAttack/Armed_1H | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; BASH_1H ; NOT PRONE [entry] | 0.97-1.03 | 1.31-2.19 |
| Rorshack/HeavyAttack/Armed_2H | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; BASH_2H ; NOT PRONE [entry] | 0.75-0.83 | 1.54-2.34 |
| Rorshack/HeavyAttack/Unarmed/InitialAttacks | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; UNARMED ; NOT PRONE [entry] ; NOT KNOCKDOWN ; ANY OF(ACTION INITIAL_ATTACK [entry]|ACTION AFTER_DASH_ATTACK [entry]) [entry] | 0.45-0.74 | 1.86-3.15 |
| Rorshack/HeavyAttack/Unarmed/GeneralAttacks | 12 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] ; UNARMED ; NOT PRONE [entry] ; NOT KNOCKDOWN | 0.67-1.23 | 1.86-3.15 |
| Rorshack/LightAttacks/Kicks | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; PRONE [entry] | 0.37-0.37 | 0.89-0.89 |
| Rorshack/LightAttacks/Stuns | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; STUN | 0.68-0.82 | 1.22-1.45 |
| Rorshack/LightAttacks/Turn Back | 3 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; ANY OF(ANGLE_TO_TARGET >= 2|ANGLE_TO_TARGET < -2) [entry] ; ATTACK_MOVE_DIST < 1.6 [entry] ; UNARMED | 0.48-0.62 | 0.91-1.50 |
| Rorshack/LightAttacks/Turn Left | 3 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; ANGLE_TO_TARGET < -1 ; ATTACK_MOVE_DIST < 1.6 [entry] ; UNARMED | 0.45-0.68 | 0.90-1.12 |
| Rorshack/LightAttacks/Turn Right | 3 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; ANGLE_TO_TARGET >= 1 ; ATTACK_MOVE_DIST < 1.6 [entry] ; UNARMED | 0.48-0.58 | 0.98-1.16 |
| Rorshack/LightAttacks/Armed_1H | 5 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; BASH_1H | 0.39-0.54 | 1.16-1.53 |
| Rorshack/LightAttacks/Armed_2H | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; BASH_2H | 0.50-0.56 | 1.14-1.43 |
| Rorshack/LightAttacks/Unarmed/InitialAttacks | 14 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; UNARMED ; ANY OF(ACTION INITIAL_ATTACK [entry]|ACTION AFTER_DASH_ATTACK [entry]) [entry] | 0.18-0.41 | 0.94-1.63 |
| Rorshack/LightAttacks/Unarmed/GeneralAttacks | 25 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 1.7 [entry] ; UNARMED | 0.30-0.56 | 0.99-1.63 |

**NiteOwl** (83 attack states)

| Group | States | Group criteria (all must hold; [entry] = only tested on entry) | IMPACT s from entry (min-max) | Reach m (min-max) |
|---|---|---|---|---|
| OneFrameActionGroup | 1 |  | 0.75-0.75 | 0.31-0.31 |
| RushToCounterAttack | 1 | ANY OF(ACTION COUNTER_ATTACK [entry]|ALL OF(RORSCHACH [entry]|ACTION FINISHING_MOVE [entry]|NOT PLAYER_VS_PLAYER [entry]) [entry]) [entry] | - | 2.25-2.25 |
| NiteOwl/HeavyAttack | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] | 0.64-0.64 | 0.98-0.98 |
| NiteOwl/HeavyAttack/KnockDowns | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; KNOCKDOWN [entry] ; NOT PRONE [entry] | 0.68-0.68 | 2.76-3.15 |
| NiteOwl/HeavyAttack/Stuns | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; STUN [entry] ; NOT PRONE [entry] ; NOT KNOCKDOWN [entry] | 0.65-0.65 | 1.72-1.72 |
| NiteOwl/HeavyAttack/AreaDamage | 4 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; AREA_DAMAGE [entry] ; NOT KNOCKDOWN [entry] ; NOT PRONE [entry] | 0.46-0.63 | 1.43-1.98 |
| NiteOwl/HeavyAttack/SuperDamage | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; SUPER_DAMAGE [entry] ; NOT KNOCKDOWN [entry] ; NOT PRONE [entry] | 1.62-1.71 | 1.83-1.97 |
| NiteOwl/HeavyAttack/Unarmed/InitialAttacks | 5 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; NOT AREA_DAMAGE [entry] ; NOT KNOCKDOWN [entry] ; NOT PRONE [entry] ; ANY OF(ACTION INITIAL_ATTACK [entry]|ACTION AFTER_DASH_ATTACK [entry]) [entry] | 0.42-0.71 | 1.42-2.72 |
| NiteOwl/HeavyAttack/Unarmed/GeneralAttacks | 9 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; NOT AREA_DAMAGE [entry] ; NOT KNOCKDOWN [entry] ; NOT PRONE [entry] | 0.60-1.15 | 1.43-3.20 |
| NiteOwl/LightAttacks | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 2 [entry] | 0.47-0.47 | 0.98-0.98 |
| NiteOwl/LightAttacks/Stuns | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 2 [entry] ; STUN | 0.60-0.60 | 1.72-1.72 |
| NiteOwl/LightAttacks/AreaAttacks | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 2 [entry] ; AREA_DAMAGE | 0.53-0.66 | 1.51-1.91 |
| NiteOwl/LightAttacks/Turn Back | 3 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 2 [entry] ; ANY OF(ANGLE_TO_TARGET >= 2|ANGLE_TO_TARGET < -2) [entry] ; ATTACK_MOVE_DIST < 1.6 [entry] | 0.65-1.04 | 1.00-1.02 |
| NiteOwl/LightAttacks/Turn Left | 3 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 2 [entry] ; ANGLE_TO_TARGET < -1 ; ATTACK_MOVE_DIST < 1.6 [entry] | 0.51-0.58 | 1.19-1.28 |
| NiteOwl/LightAttacks/Turn Right | 3 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 2 [entry] ; ANGLE_TO_TARGET >= 1 ; ATTACK_MOVE_DIST < 1.6 [entry] | 0.62-0.71 | 0.98-1.74 |
| NiteOwl/LightAttacks/InitialAttacks | 18 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 2 [entry] | 0.25-0.40 | 1.07-1.75 |
| NiteOwl/LightAttacks/GeneralAttacks | 26 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; ATTACK_MOVE_DIST < 2 [entry] | 0.46-0.61 | 1.04-1.79 |

**Enemy01** (52 attack states)

| Group | States | Group criteria (all must hold; [entry] = only tested on entry) | IMPACT s from entry (min-max) | Reach m (min-max) |
|---|---|---|---|---|
| Enemy/HeavyAttack/Armed 1H | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; BASH_1H | 1.49-1.67 | 1.37-1.99 |
| Enemy/HeavyAttack/Armed 2H | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; BASH_2H | 1.54-2.08 | 2.04-2.14 |
| Enemy/HeavyAttack/Unarmed/InitialAttacks | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED ; ACTION INITIAL_ATTACK [entry] | 1.37-2.35 | 2.27-2.58 |
| Enemy/HeavyAttack/Unarmed/DashAttacks | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED ; ACTION AFTER_DASH_ATTACK [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] | 0.34-0.47 | 2.38-2.61 |
| Enemy/HeavyAttack/Unarmed/GeneralAttacks | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED | 0.73-1.19 | 2.31-2.61 |
| Enemy/LightAttacks/Armed 1H | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; BASH_1H ; ATTACK_MOVE_DIST < 1.8 [entry] | 0.60-1.32 | 1.13-1.49 |
| Enemy/LightAttacks/Armed 2H | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; BASH_2H ; ATTACK_MOVE_DIST < 2.3 [entry] | 0.80-1.49 | 0.94-1.59 |
| Enemy/LightAttacks/Unarmed/InitialAttacks | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; ACTION INITIAL_ATTACK [entry] ; ATTACK_MOVE_DIST < 1.8 [entry] | 1.18-1.94 | 1.23-1.50 |
| Enemy/LightAttacks/Unarmed/DashAttacks | 4 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; ACTION AFTER_DASH_ATTACK [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] | 0.20-0.27 | 1.19-1.70 |
| Enemy/LightAttacks/Unarmed/GeneralAttacks | 12 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; ATTACK_MOVE_DIST < 1.8 [entry] | 0.55-0.85 | 1.15-1.65 |

**Enemy04** (49 attack states)

| Group | States | Group criteria (all must hold; [entry] = only tested on entry) | IMPACT s from entry (min-max) | Reach m (min-max) |
|---|---|---|---|---|
| Enemy/HeavyAttack/Armed 1H | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; BASH_1H | 1.40-1.45 | 1.82-1.95 |
| Enemy/HeavyAttack/KnockDowns/Heavy Knockdowns | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; KNOCKDOWN ; NOT PRONE [entry] | 0.73-0.73 | 1.82-1.82 |
| Enemy/HeavyAttack/SuperDamage | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; SUPER_DAMAGE ; NOT KNOCKDOWN [entry] ; NOT PRONE [entry] | 2.29-2.29 | 2.45-2.45 |
| Enemy/HeavyAttack/AreaDamage | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; AREA_DAMAGE [entry] ; NOT KNOCKDOWN [entry] ; NOT SUPER_DAMAGE ; NOT PRONE [entry] | 1.22-1.22 | 1.64-1.64 |
| Enemy/HeavyAttack/Stuns | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; STUN [entry] ; NOT PRONE [entry] ; NOT KNOCKDOWN [entry] ; NOT SUPER_DAMAGE | 1.06-1.06 | 1.77-1.77 |
| Enemy/HeavyAttack/Unarmed/InitialAttacks | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED ; NOT STUN [entry] ; NOT AREA_DAMAGE [entry] ; NOT KNOCKDOWN [entry] ; NOT SUPER_DAMAGE ; ACTION INITIAL_ATTACK [entry] ; NOT TWILIGHT_LADY [entry] | 1.15-2.16 | 1.64-2.10 |
| Enemy/HeavyAttack/Unarmed/DashAttacks | 3 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED ; NOT STUN [entry] ; NOT AREA_DAMAGE [entry] ; NOT KNOCKDOWN [entry] ; NOT SUPER_DAMAGE ; ACTION AFTER_DASH_ATTACK [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] | 0.18-0.36 | 1.64-2.04 |
| Enemy/HeavyAttack/Unarmed/GeneralAttacks | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED ; NOT STUN [entry] ; NOT AREA_DAMAGE [entry] ; NOT KNOCKDOWN [entry] ; NOT SUPER_DAMAGE | 0.80-1.18 | 1.64-2.10 |
| Enemy/LightAttacks/Armed 1H | 4 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; BASH_1H ; ATTACK_MOVE_DIST < 1.8 [entry] | 0.59-1.33 | 1.32-1.79 |
| Enemy/LightAttacks/KnockDowns | 1 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; KNOCKDOWN ; NOT PRONE [entry] | 0.60-0.60 | 1.35-1.35 |
| Enemy/LightAttacks/Unarmed/InitialAttacks | 8 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; NOT KNOCKDOWN [entry] ; ACTION INITIAL_ATTACK [entry] ; ATTACK_MOVE_DIST < 1.8 [entry] ; NOT TWILIGHT_LADY | 1.28-1.76 | 0.98-1.58 |
| Enemy/LightAttacks/Unarmed/DashAttacks | 7 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; NOT KNOCKDOWN [entry] ; ATTACK_MOVE_DIST < 2 [entry] ; ANY OF(ACTION AFTER_DASH_ATTACK [entry]|ALL OF(TWILIGHT_LADY|ACTION INITIAL_ATTACK [entry]) [entry]) [entry] | 0.29-0.46 | 0.98-1.58 |
| Enemy/LightAttacks/Unarmed/GeneralAttacks | 8 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; NOT KNOCKDOWN [entry] ; ATTACK_MOVE_DIST < 1.8 [entry] | 0.59-0.97 | 0.98-1.58 |

**EnemyBig** (58 attack states)

| Group | States | Group criteria (all must hold; [entry] = only tested on entry) | IMPACT s from entry (min-max) | Reach m (min-max) |
|---|---|---|---|---|
| Enemy/HeavyAttack/Armed 1H | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; BASH_1H ; ATTACK_MOVE_DIST < 2.3 [entry] | 1.37-1.52 | 2.04-2.13 |
| Enemy/HeavyAttack/Armed 2H | 2 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; BASH_2H ; ATTACK_MOVE_DIST < 2.6 [entry] | 1.81-1.85 | 1.67-2.37 |
| Enemy/HeavyAttack/Unarmed/InitialAttacks | 4 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED ; ACTION INITIAL_ATTACK [entry] | 1.26-1.76 | 1.50-2.96 |
| Enemy/HeavyAttack/Unarmed/DashAttacks | 4 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED ; ACTION AFTER_DASH_ATTACK [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] | 0.51-0.69 | 1.50-2.93 |
| Enemy/HeavyAttack/Unarmed/GeneralAttacks | 4 | ACTION NORMAL_ATTACK [entry] ; ACTION HEAVY_PUNCH [entry] ; ATTACK_MOVE_DIST < 2.5 [entry] ; UNARMED ; ATTACK_MOVE_DIST < 1.9 [entry] | 0.83-1.16 | 1.54-2.94 |
| Enemy/LightAttacks/Armed 1H | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; BASH_1H ; ATTACK_MOVE_DIST < 2 [entry] | 0.70-1.31 | 1.41-1.89 |
| Enemy/LightAttacks/Armed 2H | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; BASH_2H ; ATTACK_MOVE_DIST < 2.3 [entry] | 0.85-1.54 | 1.69-1.89 |
| Enemy/LightAttacks/Unarmed/InitialAttacks | 6 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; ACTION INITIAL_ATTACK [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] | 1.29-1.67 | 1.42-1.73 |
| Enemy/LightAttacks/Unarmed/DashAttacks | 12 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; ACTION AFTER_DASH_ATTACK [entry] ; ATTACK_MOVE_DIST < 2.2 [entry] | 0.12-0.35 | 1.20-1.61 |
| Enemy/LightAttacks/Unarmed/GeneralAttacks | 12 | ACTION NORMAL_ATTACK [entry] ; ACTION PUNCH [entry] ; UNARMED ; ATTACK_MOVE_DIST < 1.8 [entry] | 0.45-0.98 | 1.20-1.61 |

Notes on the table: Enemy01 and EnemyBig attack states have animation type NOTSET (only Enemy04, Rorschach and Nite Owl tag LIGHTATTACK / HEAVYATTACK); "reach" is `m_nimpactdistance + m_nimpactdistancemodification`, which `start_animation_state` copies to `CR.m_nimpactdist`. Per-state rows (clip, every event time, impact position/direction, damage pose, flags, sweep parameters) are in the JSON.

### 1.7 Meters, specials, slow motion

All numbers [data] `CharacterSpecialDef` in `CharacterDef.fragment`; logic [code] `CR.command_add_rage` 0x691139, `CR.give_damage` 0x691b10, `CR.StateActive` 0x6b367a.

Rorschach rage: range 0 .. max, max = 1.4 (0xa5ed34) + 0.1 per upgrade. Gains: damage taken x 0.007, damage given x 0.0033, combo hit 0.021, combo complete 0.038, finishing move 0.056, plus a flat 0.2 (0x9ebc18) after every KILL_ANIMATION_PARTNER. Any positive gain restarts the hang time (15 s); after it rage cools down at 0.03 per second. Bull rush costs 0.33. Uber rage (SPECIAL_ATTACK_2): outgoing damage x 2.25, own animation speed x 1.15 (also in co-op), rage drains 0.08 per second and each hit drains damage x 0.003 (clamped to 0.05 per hit, 0xa5ed3c); it ends when rage reaches 0. During uber rage all attacks are unblockable, and damage dealt to another *playable* character is multiplied by max(1/2.25, 0.7) instead (`DecreaseHealth` 0x695632).

Bull rush [code: BULLMOVE_IMPACT event case]: damage = 40 x global factor x uber factor (x 0.4, f64 0x9eb790, if the victim is a playable character), stun 3 s; if this kills, the pose is KNOCKDOWN_MIDDLE_STRAIGHT and the camera recoils 1.4. Secondary victims 10 damage / 2 s stun [data; the secondary-hit handler was not read].

Nite Owl electricity: same 0 .. 1.4 (+0.1 per upgrade) scale. Recharges fully in 100 s when not blocking; block costs 0.04 per blocked hit; grenade costs 0.33; armour costs 1.0 and gives 16 charges that discharge over 15 s. While charges are up: each of his hits adds 9 damage and 2 s stun and is unblockable; anyone who hits him takes 10 damage and 2 s stun and that attack's damage is multiplied by 0.2 (f64 0x9e97e8). Electric blast: range 4 m, 40 / 20 damage and 2 s stun close / far, push-back inside 3 m, knock-down inside 2 m [data; blast handler (events 29-31) not read].

Slow motion [code: `give_damage`, `StateActive`]: time multiplier `_nslomotimemultiplier` 0.25 [default] for 0.4 s of real time (f64 0x9eb790). Triggered on a surviving victim by knock-down poses (13-18, 27, 28) and on a kill by a player by poses 7-22 and 25-28. A kill also gives FOV x 0.85 for 0.4 s and a camera shake (0.5, 0.04, 30).

### 1.8 Co-op and versus specifics [code]

- A playable character whose AI brain has faction 1 (ENEMY) is a PvP opponent. In PvP a hit sets `m_nextraclearzonetime = now + _thitinvsmodedefenddeadzonetime` (0.2 s [default]) during which the victim cannot dodge or block; stun on a player is capped at 2.5 s (0x9e72b8) instead of 1.0 s; no health regeneration.
- Paired-move damage against a playable victim is x 0.75 (f64 0x9e70e8); bull rush x 0.4; uber-rage damage against a playable victim is capped as above; ragdoll collision damage to players x 0.3.
- An AI partner can never drop below 1 health (`DecreaseHealth`), and its stun is capped at 2.5 s.
- Death of a hero: in game mode 3 (co-op), or when the dead hero is not the one the single-player mode is about, health is set to 1 and game event 104 / 105 is broadcast instead of dying; otherwise health 0 and event 201 CHARACTER_DEAD. In PvP scene 40 a lethal hit from an attack state on a victim with more than 0.5 health leaves 0.5 health and forces a finishing move.
- The hero counter groups also accept `ACTION FINISHING_MOVE` against the other hero when not in PvP (group criteria), i.e. a "finisher" on the partner plays a counter pair.
- Friendly fire: there is no faction test in `SetCloseCombatDamageToTarget` or `give_damage`; whoever is the attack target or is touched by a sweep takes the hit. What protects allies is target selection (`get_target_empty_ignore`), which was not read [not established whether it filters by faction].

## 2. Attack resolution

### 2.1 Entering an attack state [code: `CRL.command_start_animation_state` 0x688961]

For every state with `m_tisattackstate` (and counter masters): the unblockable flag is computed (uber factor > 1, or combo list longer than 1, or electrified charges > 0, or a weapon held and the state is not a THROW); `m_tisupper` is cleared when the target is a big enemy and the impact height (visual y + impact pos y) is below 1.5 m; `m_tverylow` = impact pos y < -0.1; `CR.m_nimpactdist` = impact distance + modification; then `CombatOrchestrator.command_attack_animation_stated(attacker, state)` 0x6e6495 is sent, which (a) for a player locks the target onto the attacker (`force_lock_target`), (b) stamps the attacker's cooldown `now + def.get_time_between_attacks()`, (c) promotes a waiting attacker to current, and (d) sends the **target's** root behaviour `command_react_to_attack(attacker)` - the block/dodge/counter decision of section 4.2. Rush states (special handling 4) do not trigger it.

An AI fast attack is additionally gated by `target.command_may_be_attacked(self)` = the target's state is not immune (`m_timmunetoattacks`, placeholder, or prone under low-violence).

### 2.2 PRE_IMPACT [code: event case 16]

- No target -> nothing ("sweet spot" off).
- Target is AI and its behaviour's `command_is_attack_successful(attacker)` returns 0 -> the target is told `block_timed(1.0)`. For plain enemies (`Enemy` 0x7f09ac) this always returns true; only the Underboss and partner behaviours can refuse.
- AI attacker range check: if the target is farther than **1.8 m** (0x9e5fa0), or 2.2 m (0xa46b90) for a big attacker, the attack loses its target, partner and unblockable flag - it whiffs. Players have no such check; their reach is the animation's own motion plus the state criteria.
- Otherwise the damage pose is computed (section 2.5) and `target.command_hit_soon(attacker, pose, dir)` 0x6903ea is sent. `hit_soon` is what makes the victim react **before** the damage: it writes DAMAGE_POSE (enum 4) and OPPONENT_MODEL_TYPE (enum 11); if the victim is in a BLOCK state it locks onto the attacker and fires action BLOCK (the block-impact state) and stops; otherwise it fires HITTAKEN (2) on the head controller and ONE_FRAME_ACTION + HITTAKEN on the body, notifies the AI (`when_attacked`, `force_update`) or the player controller (`hit_by`), and force-locks the victim onto the attacker. Skipped when the victim is a placeholder, invulnerable (`damagestate 1`) or in an IMMUNE_TO_BREAK_ATTACK state.

So the hit reaction animation starts at PRE_IMPACT (0.07-0.09 s before IMPACT in the shipped data) and health is removed at IMPACT.

### 2.3 Dodge and counter windows

- **Being in the dodge list.** `CR.command_i_will_hit_you` 0x693ebf adds the attacker to the victim's `m_eenemytododgelist` for 1.5 s (f64 0x9e8320). A dodge only counts as a combo item when that list is non-empty. `CR.command_i_will_dodge_you` 0x693fa1 makes the attacker lose its attack target, records `m_ehasjustdodgedme = dodger` and kills its combo. [code; the caller that sends `i_will_hit_you` at attack start was not pinned to an address - inferred to be the AI attack behaviour.]
- **Counter button** [`CRL.TestForCounterAttack` 0x68d36a]: refused in a slave state or while already master of pair 10. Target = the player's soft target, else the nearest character in the facing cone within 5.0 m; for AI the next target. The target must be attacking me (`m_eattacktarget == me`) or must have just been dodged by me. Unless the target is still in its rush state, the timing test is, with p = the target state's current playpos, p0 / p1 = previous / next IMPACT event playpos and D = clip duration:
  `(p1 - p) * D > 0.13 s` (0xa5ecc8) and `(p - p0) * D > 0.03 s` for a player (0x9e60e0) or `> -0.03 s` for AI (0xa5eccc).
  A 0.26 s variant (0xa5ecc4) exists for argument value 0, but both callers pass 1, so the window is always 0.13 s. On success: attack data cleared, target/lock/partner set, combo item 13 requested, actions 14 + 12 fired -> a counter pair (section 3.3).
- `CRL.command_counter_attack` 0x68664c only tests when the current state allows attacks, or for a player when dz is at most 2.0 s old.
- **Combo counter**: [DODGE or BLOCK] followed by a fast attack is a combo string with override COUNTER_ATTACK (ability 3) - no timing test, the target is taken from the list of characters just dodged/blocked.
- **AI delayed counter**: `_ndelaycountertime`; on expiry, if not on a slope and at the same height (|dy| <= 0.1), the AI goes idle and sends `CRL.command_force_counter_attack` 0x6867b7 (no timing test).
- **Breaking out of a pair**: while a slave state has FORCE_ALLOW_BREAKOUT active, a dodge or block (or force counter) by the slave ends the pair: partner forced idle + ATTACK_BLOCKED, rumble, combo list becomes [DODGE] or [BLOCK] with 0.5 s validity so that a following fast attack is the combo counter.

### 2.4 IMPACT: who gets hit [code: event case 4, `CRL.SetCloseCombatDamageToTarget` 0x6ae57f, `command_sweep_target_detected` 0x6879ed]

Normal attacks are **single-target and unconditional**: if the attacker still has its attack target at IMPACT, that target takes the hit - there is no cone, range or collision test at impact (the range test for AI was at PRE_IMPACT; players have none). Area attacks are the states flagged `m_tallowsweepatt` (Rorschach Area_A and the 2H heavies, eight Nite Owl area/super states, Enemy04 Area_A): a `CharacterSweepAttack` volume is stepped at `m_nchecksprsec` 10 checks per second [default] between begin/impact/end playpos with an angle and length per phase (JSON `sweep`), and every character it detects other than the main target and not blocking gets `SetCloseCombatDamageToTarget` too. The stepping loop itself was not read.

Players additionally run `TestImpactOnDynamicObjects` (hitting props) at IMPACT.

### 2.5 The hit [code: `SetCloseCombatDamageToTarget` 0x6ae57f]

1. Pose chain (`ProjectAnimationLib`, table in JSON `damage_pose_rules`): state `m_idamagepose` -> combo conversion (`ComboManipulateDamage` 0x675ce6: STUN override -> STUN_UPPER / STUN_MIDDLE / *_BACK, HEAVY_DAM -> heavy) -> direction (`DirectionManipulateDamage` 0x802ae8: attacker behind the target, local z < -0.2 m, -> the *_BACK pose of the same strength) -> size (`SizeManipulateDamagePose` 0x7fca72: big target and attack not upper -> upper poses become MIDDLE_STRAIGHT) -> height (`HeightManipulateDamagePose` 0x7fcaee: target more than 0.1 m higher and hit height - dy < 0.4 -> low; more than 0.1 m lower and hit height - dy > 0.4 -> high).
2. Hit direction = attacker visual orientation x state `m_vimpactdirection`; hit position from `m_vimpactpos` relative to the hit bone.
3. Target wears electric armour -> the **attacker** receives {damage 10 x global x uber, stun 2 s, pose NO_POSE} and the outgoing damage is x 0.2.
4. Underboss target hit from behind -> blocked (sound only).
5. **Block test**: target state has special handling BLOCK (8) or IMMUNE_TO_BREAK_ATTACK (13), and the attacker's RELATIVE_HEAD_HEIGHT value > 0 -> blocked: attacker fires ONE_FRAME_ACTION + ATTACK_BLOCKED (its "AttackBlocked" recoil state), `target.give_block_damage(attacker, pos, dir)` 0x692c3f; no damage unless the attacker has electrified charges. Note this test does not look at the unblockable flag; unblockable is enforced earlier, by the defender refusing to react (section 4.2). [code]
6. Damage:

   `damage = base x damage_modifier(attacker) x g_nglobaldamagefactor x m_ninrageuberdamagefactor`
   `       + [string completed] combo.m_ndamage x modifier x global x uber`
   `       + [attacker electrified] 9 x global x uber`

   - `base` = `_nnextdefaultdamage`, set per press by `AddAttackToCombo` from the attacker's combo database: fast unarmed / 1H / 2H, heavy unarmed / 1H / 2H (section 1.5 headers). The registry default 5.0 (0x9e97fc) applies only without a combo database.
   - `damage_modifier` = `EnemyDef._ndamagemodifier` if set, else `CharacterDef` default (`EnemyDef.command_get_damage_modifier` 0x71f0cf): 1.0 for heroes and most enemies, 1.5 Dominatrix and Twilight Lady, 1.3-2.0 for phase/leader definitions (section 4.1).
   - `g_nglobaldamagefactor` = 1.0 [default]; nothing in the script corpus writes it. `m_ninrageuberdamagefactor` = 1.0, or 2.25 in uber rage.
   - stun = combo stun (+2 s if attacker electrified); push-back = hit direction x `m_npushbackvel` for `m_npushbacktime`.
7. `target.command_give_damage(characterdamagestruct)`; a 0.3 light flash; `weapon.take_durability_damage` unless the state sets `m_tignoreweaponsound`.

`characterdamagestruct` fields as used: inflictor, pose, damage, stun, position (vector), +0x1c "is rage damage" flag, direction/push vector, unique attack id (+0x38), ignore-weapon flag (+0x3c). `takeahitstruct` did not appear in any handler read [not established].

### 2.6 `CR.command_give_damage` 0x691b10 and `DecreaseHealth` 0x695632 [code]

- Every hit carries a unique attack id (`characterlib.GetUniqueAttackId`); its use to reject a second hit from the same swing is inferred, the check was not located.
- Pose is reset to NO_POSE if the victim is in a reaction that is reversing its heading (playpos 0.5-0.8).
- Underboss takes x 0.2 from AI inflictors and is immune to stun.
- Applied damage = `m_nincomingdamagefactor` x damage. That factor is 1.0 [default] and is only changed by level scripting (`TriggerActionCharacter` -> `command_set_incoming_damage_factor` 0x691a62). No reader of a difficulty setting was found in the damage path.
- No damage if invulnerable / `damagestate 1`. `m_nminhealth` clamps the result (scripted survivors).
- Rage: inflictor += 0.0033 x damage (uber: -0.003 x damage, clamped), victim += 0.007 x damage.
- Survivor: camera recoil by pose class (light 0.5, heavy 1.0, knock-down 2.1 (0xa5ed38), stun 1.4, else 0.2); slow motion for knock-down poses; stun timer set if longer than the current one (`set_stun_time` 0x691389: AI full, player max 1.0 s, 2.5 s in PvP); push-back if time > 0 (`set_push_back_data` 0x691325: velocity decays linearly to 0 over T, so displacement = v x T / 2: 4 m/s for 0.3 s = 0.6 m; 8 m/s for 0.5 s = 2 m).
- Game event 203 DAMAGE_RECEIVED for survivors, 201 CHARACTER_DEAD on death; achievement hooks `damage_by_signed_in_player`, `player_received_damage`, `enemy_killed_by_signed_in_player`, `combo_string_ended` are sent from here.

### 2.7 Reaction thresholds

There is **no damage threshold** for stagger, knock-down or launch. The reaction is purely the DAMAGE_POSE the attack state carries (after the conversions of 2.5) matched against the victim's `HitTakenGroup` criteria:

| Pose class | Victim result (all classes) |
|---|---|
| LIGHT_* (1-6, 23, 24) | short flinch state, attacks disallowed until its ALLOW_ATTACKS event (Dominatrix: 0.64-0.97 s), stun-lock state |
| HEAVY_* (7-12, 25, 26) | longer flinch (Dominatrix: 0.82-1.12 s to ALLOW_ATTACKS) |
| KNOCKDOWN_* (13-18, 27, 28) | knock-down state, immune, goes to ragdoll (RAGDOLL_MODE event); Twilight Lady plays a heavy flinch instead |
| STUN_* (19-22) | stun state with KNEE events (target counts as "on knee": heavy attack on it = KNOCKDOWN string; TARGET_MODE 3) |

Stunned (`_nstuntimeleft > 0`) is separate: it is the timer set from combo stun / specials and keeps the victim in the Stunned movement states. Prone = RELATIVE_HEAD_HEIGHT < 0 or ragdoll physics state (`CR.command_is_prone` 0x6936ff; never for Underboss / Twilight Lady). A pending dodge can interrupt a stun-lock state after 0.1 s (`StateCharacterRootLogic`).

Hit-stop: none found. The only time effects are the slow motion of section 1.7.

### 2.8 Throws [code: `CRL.FireAttackBasedOnAttackID` 0x68d870, `do_special_state_handling` 0x687bc5; control flow read from lifted text only]

Fails (action THROW_GRAB_FAILED) when the target's RELATIVE_HEAD_HEIGHT < -0.35 (0xa5ec78), it is ragdolled, animation-immune or in an absolute animation; when the attacker is on a slope or not at the same height the target blocks. An electrified or unblockable attacker always succeeds. Otherwise, if the target is neither stunned nor prone and has the attacker in front (0x200): `rand <= m_nprobblockthrow` -> target blocks; else `rand2 <= m_nprobdodgethrow` -> target dodges; else success. Underboss and Twilight Lady cannot be thrown (she dodges). The throw master state (THROWN_BY_RORSCHACH, pair id 1, both heroes use Rorschach's clip) requires ATTACK_MOVE_DIST in [0.1, 2). The thrown body damages others through ragdoll collision (`give_ragdoll_damage_increment` 0x6914f2). Where the combo database's throw damage (15) is applied was not read.

## 3. Health and death

### 3.1 Pools and regeneration [data: CharacterDefs; code: `CR.UpdateHealth` 0x678288, `AiDef.GetHealthProperties`]

| CharacterDef | Max health | Critical health (finisher prompt below) | Prompt time s | Regen /s (above low point) | Low point | Regen /s below low point | Regen delay after hit s | Damage modifier | Combo DB | 1H / 2H weapon models | Head / body hit offset m |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BIKER_HEAD | 60.0 | 0.0 | 2.5 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | Enemy Combos | True / True | 0.04 / 0.1 |
| DOMINATRICE | 100.0 | 44.0 | 3.0 | 0.0 | 45.0 | 0.0 | 2.0 | 1.5 | Enemy Combos | True / False | 0.04 / 0.1 |
| GIMP | 200.0 | 49.0 | 2.5 | 0.0 | 50.0 | 0.0 | 4.0 | 1.0 | Big Enemy Combos | True / True | 0.15 / 0.27 |
| GIMP_NO_GAGBALL | 200.0 | 49.0 | 2.5 | 0.0 | 50.0 | 0.0 | 4.0 | 1.0 | Big Enemy Combos | True / True | 0.15 / 0.27 |
| HEAVIES | 60.0 | 19.0 | 2.5 | 0.0 | 20.0 | 0.0 | 2.0 | 1.0 | Enemy Combos | True / True | 0.04 / 0.1 |
| NITE_OWL | 90.0 | 0.0 | 2.5 | 1.5 | 40.0 | 1.5 | 6.0 | 1.0 | Nite Owl Combos | False / False | 0.04 / 0.1 |
| RORSCHACH | 65.0 | 0.0 | 2.5 | 2.0 | 32.0 | 2.0 | 6.0 | 1.0 | Rorschach Combos | True / True | 0.04 / 0.1 |
| THUG | 60.0 | 9.0 | 3.5 | 0.0 | 10.0 | 0.0 | 0.0 | 1.0 | Enemy Combos | True / True | 0.04 / 0.1 |
| THUG_BIG | 200.0 | 49.0 | 3.5 | 0.0 | 50.0 | 0.0 | 2.0 | 1.0 | Big Enemy Combos | True / True | 0.1 / 0.2 |
| THUG_FAST | 40.0 | 0.0 | 2.5 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 | Enemy Combos | True / True | 0.04 / 0.1 |
| TWILIGHT_LADY | 1000.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 2.0 | 1.5 | Enemy Combos | False / False | 0.04 / 0.1 |

Regeneration runs when `now - last hit > regen delay` and (the character is playable, or is an enemy currently hanging back, or its health is below critical), and its AI definition does not disable it; never for the Underboss or in PvP. Above the low point health rises by "regen" per second up to max; below it by "regen below low point" up to the low point. So Rorschach (65 hp) regenerates 2.0/s after 6 s without being hit, Nite Owl (90 hp) 1.5/s; enemies have 0 regeneration in the shipped data, so the rule has no effect for them.

### 3.2 Finisher prompt [code: `CR.DecreaseHealth` 0x695632, `CR.UpdateHealth`, `PlayerCtrl.CheckFinishMove` 0x7eff13, `CRL.command_force_finishing_move` 0x6866f9, `CRL.FinishOrStompEnemy` 0x677c93]

1. **Trigger**: the first time a hit *by a player* takes an enemy's health from at-or-above `m_ncriticalhealth` to below it (and it survives), `m_nstartcriticaltime = now` and a button is rolled into `m_ifinishoffbutton`: `rand_integer(3)` on PC/editor, `rand_integer(4)` on consoles -> 0: DEFEND (28), 1: ATTACK_0 (21), 2: ATTACK_1 (22), 3: ATTACK_2 (23). The roll is repeated up to 10 times while it equals the last button the player pressed, so the prompt is rarely the button being mashed. For the Dominatrix critical health is 44 of 100; Thug 9/60, Heavies 19/60, big enemies 49/200; Thug Fast, Twilight Lady and the heroes have 0 = never.
2. **Display**: the icon is shown while `health < critical && now < start + m_nfinishicontime` (3.0 s Dominatrix, 2.5 s Gimp/Heavies, 3.5 s Thugs) and the enemy is alive; hidden in a slave state, or when prone under low violence. When the condition fails the button is reset to -1.
3. **Completion**: every button press goes through `CheckFinishMove(button)` first. If the current target is alive, not in a slave state and `target.m_ifinishoffbutton == button`: the hero's next target is set and `command_force_finishing_move` runs -> `FinishOrStompEnemy`: target ragdolled or its head bone below -0.18 m (0xa5e7b0) -> action 29 KILL_PRONE_TARGET (stomp), else action 3 FINISHING_MOVE (a finisher pair, section 3.3). Pressing a **wrong** button more than 0.7 s after the prompt started cancels the prompt (start = -1, button = -1); within the first 0.7 s wrong presses are forgiven.
4. **Kill**: the finisher master's KILL_ANIMATION_PARTNER event gives the partner 100000 damage (0x9eba80) with NO_POSE, adds the finishing-move meter bonus (0.056 rage / 0.05 electricity) plus 0.2 rage. The DIE event (85) does the same to the character itself.
5. The prompt can re-arm only after health has gone back above critical (regeneration) - inferred from the "first drop below" condition.

### 3.3 What triggers each paired move

413 pairs in `anim_meta_v2.json` (240 primary). Every pair's master state sits in one of five groups; the rule for the group is the trigger. Per-pair rows (master, partner, pair id, rule, state/group criteria, weapon requirements) are in JSON `pair_triggers`; the rule texts in `pair_trigger_rules`.

| Rule | Pairs (primary) | Master groups | Game condition |
|---|---|---|---|
| COUNTER | 257 (148) | hero `CounterAttackStates*`, `FailedCountersUnderboss` | Hero fires ACTION COUNTER_ATTACK: (a) combo [DODGE]+fast (Rorschach) / [BLOCK]+fast (Nite Owl), ability 3; (b) counter button passing the 0.13 s test of 2.3; (c) forced counter (AI partner). The group is chosen by the opponent's model type (ENEMY_01/03/other hero, ENEMY_02 big, ENEMY_04, UNDERBOSS) and ATTACK_MOVE_DIST 0.1-1.5 m (1.8 or 2.0 for big / Underboss); the state by the hero's weapon class (UNARMED / BASH_1H / BASH_2H) and, for the Disarm states, the **opponent's** weapon. Beyond that distance `RushToCounterAttack` closes in first (up to 5 m). If the counter would kill - player only, `target health <= 20 x modifier x global x uber x target incoming factor` and target not Twilight Lady - a finisher is fired instead. |
| FINISH | 118 (61) | hero `FinishingMovesEnemy01and03`, `...Enemy02`, `...Enemy04` | ACTION FINISHING_MOVE from: the finisher prompt (3.2); a counter that would kill; combo override FINISHING_MOVE (no shipped string uses it); the PvP forced finisher. Requires ATTACK_MOVE_DIST 0.1-1.6 m (2.0 big), group by opponent model, state by own weapon class; random among the states that pass. |
| THROW | 10 (10) | `Throw`, `Throw Big Guy` | Throw button and the success branch of 2.8. |
| BULL | 6 (3) | `BullMoveImpactGroup` | Rorschach's bull rush reaching its target (CHARGE event of the Bullmove state puts physics in charge mode; contact handler not read). Damage at the BULLMOVE_IMPACT event. |
| ENEMY_COUNTER | 22 (18) | enemy `CounterAttackGroup`, Enemy04 `NormalEn4Counters`, `TwilightLadyCounters` | The enemy's reaction table returns COUNTERATTACK when the hero enters an attack state (4.2), or a Twilight Lady combo with override COUNTER_ATTACK. State by the hero's model (RORSCHACH / NITE_OWL), the enemy's weapon (BASH_1H -> `Counter_*_WPN`) and SPECIFIC_MODEL (Twilight Lady -> cattle-prod counters). |

Damage of a pair [code: IMPACT event in a non-attack state]: when the partner's behaviour `is_attack_successful(master)`: `damage = (combo database counter damage, else 20 (0x9e66ac)) x 0.75 if the partner is playable, + completed-combo bonus, x modifier x global x uber`; pose NO_POSE; position 0.5 m in front and 0.3 m up; combo validity +1.0 s; meter bonus as for a completing hit. Finishers have no IMPACT; they kill by KILL_ANIMATION_PARTNER. If a pair is interrupted (`CRL.DualAnimBroken` 0x675f4f): a thrown partner gets safe ragdoll collision groups for 0.5 s; a partner before 75% of its state is forced idle; after 30% the master plays ATTACK_BLOCKED.

### 3.4 Death [code: `DecreaseHealth`, `give_damage`; `CR.StateDead` 0x6bb12a at call level]

- Health <= 0 -> game event 201 CHARACTER_DEAD (inflictor attached), state change to StateDead; the victim is ragdolled with speed 3.5 (0xa554f0) and pushed along the hit direction at 2.5 m/s for 2.0 s; killer's camera: FOV x 0.85, shake, slow motion for heavy/knock-down/stun poses.
- StateDead: speech event; unregister from the LOD controller and from the combat orchestrator; root behaviour reset; `command_force_drop_weapon`; collision group reset; then a settle loop - once the ragdoll's mean velocity is below 0.1 (f64 0x9e9628) a 3.0 s countdown (0x9e6910) runs, with a hard 30 s limit (0xa07d84); after that non-playable bodies have their add-on physics deleted and a game event is broadcast; playable characters wait indefinitely (revive by `command_revive` 0x694f3b). Ragdoll details belong to WP2.
- Kill credit: `AchievementPart2Ctrl.command_enemy_killed_by_signed_in_player(victim)` is sent from `give_damage` (direct kills) and from `give_ragdoll_damage_increment` (thrown-body kills); other hooks: `command_finishing_move...`, `command_counter_attack...`, `command_enemy_thrown`, `command_stomp...`, `command_combo_by_signed_in_player`, `command_rage_started/ended`, `command_enemies_electrified`. The achievement conditions themselves were not read.

## 4. Enemy side

`Enemy.Evaluate` and the behaviour tree (who attacks when, positioning, hang-back) are WP4's subject and are treated as given. What follows is the combat interface.

### 4.1 Attack definitions per enemy type [data: `Enemy/*.fragment`; meaning of the fields from `EnemyDef`, `CharacterAIComboManager.StatePerformCombo` 0x64a400, CO 0x6e6495]

| Def | Attack dist / min m | Time between attacks s | P fast / slow / combo | Throw: P block / P dodge | DRS decay s | Dmg mod | Reaction rows (newest first -> result) | AI combos (freq) |
|---|---|---|---|---|---|---|---|---|
| DOMINATRICE BASE_DEF | 4.0 / 2.0 | 1.8-3.0 | 0.8 / 0.2 / 0.5 | 0.0 / 0.4 | 4.0 | 1.5 | LLL* -> COUNTERATTACK (clear); HHH* -> COUNTERATTACK (clear); HHH -> DODGE; LLL -> DODGE | [F] [dodge] [H] x1; [F] [F] [H] x3 |
| DOMINATRICE PHASE_1 | 4.5 / 2.0 | 1.8-3.0 | 0.8 / 0.2 / 0.5 | 0.0 / 0.8 | 4.0 | 1.5 | LLL* -> COUNTERATTACK (clear); HHH* -> COUNTERATTACK (clear); HHH -> DODGE; LLL -> DODGE | [F] [dodge] [H] x1; [F] [F] [H] x3 |
| GIMP BASE_DEF | 4.5 / 1.5 | 3.0-6.0 | 0.3 / 0.7 / 0.5 | 1.0 / 0.0 | 6.0 | 1.5 | ****** -> COUNTERATTACK (clear); **** -> BLOCK | [F] [H] x1; [F1h] [H1h] x1 |
| GIMP PHASE_1 | 4.5 / 1.5 | 1.0-4.0 | 0.3 / 0.7 / 0.5 | 1.0 / 0.0 | 6.0 | 2.0 | ****** -> COUNTERATTACK (clear); **** -> BLOCK | [F] [H] x1; [F1h] [H1h] x1 |
| GIMP_WITH_GAGBALL BASE_DEF | 4.5 / 1.5 | 3.0-6.0 | 0.3 / 0.7 / 0.5 | 1.0 / 0.0 | 6.0 | 1.5 | ****** -> COUNTERATTACK (clear); **** -> BLOCK | [F] [H] x1; [F1h] [H1h] x1 |
| GIMP_WITH_GAGBALL PHASE_1 | 4.5 / 1.5 | 1.0-4.0 | 0.3 / 0.7 / 0.5 | 1.0 / 0.0 | 6.0 | 2.0 | ****** -> COUNTERATTACK (clear); **** -> BLOCK | [F] [H] x1; [F1h] [H1h] x1 |
| HEAVIES BASE_DEF | 3.5 / 2.0 | 3.5-5.0 | 0.8 / 0.2 / 0.4 | 0.0 / 0.0 | 2.0 | 1.0 | ****** -> COUNTERATTACK (clear); ***** -> BLOCK | [F1h] [F1h] [H1h] x1; [F] [F] [H] x1 |
| HEAVIES PHASE_1 | 4.0 / 2.0 | 2.0-4.0 | 0.5 / 0.5 / 0.4 | 0.5 / 0.5 | 2.0 | 1.3 | ****** -> COUNTERATTACK (clear); ***** -> BLOCK | [F1h] [F1h] [H1h] x1; [F] [F] [H] x1 |
| NITE_OWL PHASE_1 | 3.0 / 1.0 | 2.15-4.29 | 0.8 / 0.2 / 0.0 | None / None | None | 1.0 | - | - |
| NITE_OWL PHASE_2 | 3.0 / 1.0 | 11.04-11.349999 | 0.0 / 1.0 / 0.0 | None / None | None | 1.0 | - | - |
| NITE_OWL PHASE_3 | 3.0 / 1.0 | 1.53-3.68 | 0.3 / 0.7 / 0.0 | None / None | None | 1.0 | - | - |
| NITE_OWL PHASE_4 | 3.0 / 1.0 | 11.04-11.349999 | 0.0 / 1.0 / 0.0 | None / None | None | 1.0 | - | - |
| NITE_OWL PHASE_5 | 3.0 / 1.0 | 2.45-3.07 | 1.0 / 0.0 / 0.0 | None / None | None | 1.0 | - | - |
| NITE_OWL PHASE_6 | 3.0 / 1.0 | 0.92-0.92 | 1.0 / 0.0 / 0.0 | None / None | None | 1.0 | - | - |
| NITE_OWL BASE_DEF | 3.0 / 1.0 | 0.2-3.0 | 0.5 / 0.5 / 0.0 | None / None | None | 1.0 | - | - |
| RORSCHACH PHASE_1 | 3.0 / 1.0 | 2.15-2.76 | 0.6 / 0.4 / 0.0 | None / None | None | 1.0 | - | - |
| RORSCHACH PHASE_2 | 3.0 / 1.0 | 8.28-8.59 | 1.0 / 0.0 / 0.0 | None / None | None | 1.0 | - | - |
| RORSCHACH PHASE_3 | 3.0 / 1.0 | 1.53-2.15 | 0.8 / 0.2 / 0.0 | None / None | None | 1.0 | - | - |
| RORSCHACH PHASE_4 | 3.0 / 1.0 | 0.5-1.23 | 0.9 / 0.1 / 0.0 | None / None | None | 1.0 | - | - |
| RORSCHACH PHASE_5 | 3.0 / 1.0 | 1.23-1.53 | 0.96 / 0.04 / 0.0 | None / None | None | 1.0 | - | - |
| RORSCHACH BASE_DEF | 3.0 / 1.0 | 0.5-3.0 | 0.8 / 0.2 / 0.0 | None / None | None | 1.0 | - | - |
| THUG BASE_DEF | 3.5 / 2.0 | 3.5-4.5 | 0.5 / 0.5 / 0.1 | 0.0 / 0.0 | 3.0 | 1.0 | LLLLLL -> COUNTERATTACK (clear); LLLL -> BLOCK | [F] [dodge] [H] x1; [F1h] [F1h] [H1h] x1; [F] [F] [H] x1; [F] [F] [F] [F] x1 |
| THUG LEADER_DEF | 3.0 / 1.0 | 3.5-6.0 | 0.8 / 0.2 / 0.1 | 1.0 / 0.0 | 4.0 | 1.5 | LLLLLL -> COUNTERATTACK (clear); LLLL -> BLOCK | [F] [dodge] [H] x1; [F1h] [F1h] [H1h] x1; [F] [F] [H] x1; [F] [F] [F] [F] x1 |
| THUG_BIG BASE_DEF | 3.5 / 1.5 | 5.0-7.0 | 0.3 / 0.7 / 0.1 | 1.0 / 0.0 | 5.0 | 1.0 | ****** -> COUNTERATTACK (clear); **** -> BLOCK | [F] [H] x1; [F1h] [H1h] x1 |
| THUG_BIG LEADER_DEF | 3.0 / 1.0 | 5.0-7.0 | 0.3 / 0.7 / 0.1 | 1.0 / 0.0 | 8.0 | 1.5 | ****** -> COUNTERATTACK (clear); **** -> BLOCK | [F] [H] x1; [F1h] [H1h] x1 |
| THUG_FAST BASE_DEF | 4.0 / 2.0 | 2.0-3.5 | 1.0 / 0.0 / 0.2 | 0.0 / 1.0 | 3.0 | 1.0 | H* -> COUNTERATTACK (clear); H -> DODGE | [F] [dodge] [H] x1; [F1h] [F1h] [H1h] x1; [F] [F] [H] x2; [F] [F] [F] [F] x2 |
| THUG_FAST LEADER_DEF | 3.0 / 1.0 | 0.0-0.0 | 0.9 / 0.1 / 0.2 | 0.0 / 1.0 | 4.0 | 1.5 | H* -> COUNTERATTACK (clear); H -> DODGE | [F] [dodge] [H] x1; [F1h] [F1h] [H1h] x1; [F] [F] [H] x2; [F] [F] [F] [F] x2 |
| TWILIGHT_LADY BASE_DEF | 3.0 / 1.0 | 1.8-3.0 | 0.7 / 0.3 / 0.0 | 0.0 / 1.0 | 4.0 | 1.5 | LLL* -> COUNTERATTACK (clear); HHH* -> COUNTERATTACK (clear); HHH -> DODGE; LLL -> DODGE | - |
| TWILIGHT_LADY PHASE_1 | 3.0 / 1.0 | 1.8-3.0 | 0.6 / 0.4 / 0.3 | 0.0 / 1.0 | 4.0 | 1.5 | LLL* -> COUNTERATTACK (clear); HHH* -> COUNTERATTACK (clear); HHH -> DODGE; LLL -> DODGE | [F] [F] [F] [F] [H] x3; [F] x0; [F] [H] x3; [H] x1; [F] [F] x2 |
| TWILIGHT_LADY PHASE_2 | 3.0 / 1.0 | 4.29-6.13 | 0.8 / 0.2 / 0.9 | 0.0 / 1.0 | 4.0 | 1.5 | LLL* -> COUNTERATTACK (clear); HHH* -> COUNTERATTACK (clear); HHH -> DODGE; LLL -> DODGE | [H] x1; [F] [H] x1; [H] x1 |
| TWILIGHT_LADY PHASE_3 | 3.0 / 1.0 | 0.31-1.23 | 0.8 / 0.2 / 0.3 | 0.0 / 1.0 | 4.0 | 1.5 | LLL* -> COUNTERATTACK (clear); HHH* -> COUNTERATTACK (clear); HHH -> DODGE; LLL -> DODGE | [H] x1; [F] [H] x1; [H] x1; [H] x3; [F] [F] [F] [F] [H] x1; [F] x1; [F] [F] x4 |

- An enemy attack is the same machinery as a player attack: the behaviour sends `CRL.command_attack_fast` / `attack_slow` (probabilities "P fast / P slow") and the animation controller picks a state from the enemy's attack groups (section 1.6 table). With probability "P combo" a whole string is performed instead: `StatePerformCombo` breaks off the current attack, kills the combo list and issues the string's items one at a time with a 0.4 s wait after each, aborting if stunned, with a time-out of 5.0 s x string length. The strings come from the definition's list (weights = "freq"), drawn from the enemy combo database; their only effect in the shipped data is the hit sequence itself (no bonus, no override) except the 0.4 s push-back time field on two of them (velocity 0, so no push).
- "Attack dist" is the distance at which the enemy may start an attack run (the rush state covers the gap, up to 5 m by its criterion); "min" is the spacing it keeps. Damage is only delivered if the target is within 1.8 m (2.2 m for big attackers) at PRE_IMPACT (2.2).
- "Time between attacks" is the cooldown stamped by the orchestrator when the enemy's attack state starts.
- Base damage per enemy hit = database default x damage modifier:

| Database | Fast unarmed / 1H / 2H | Heavy unarmed / 1H / 2H | Counter (pair) | Used by |
|---|---|---|---|---|
| Enemy Combos | 5 / 12 / 15 | 10 / 20 / 25 | 10 | Thug, Thug Fast, Heavies, Dominatrix |
| Big Enemy Combos | 10 / 15 / 20 | 15 / 20 / 25 | 20 | Thug Big, Gimp |
| Twilight Lady Combos | 3 / 15 / 20 | 9 / 20 / 25 | 20 | Twilight Lady (EnemyDef override) |
| Underboss Combos | 10 / 15 / 20 | 15 / 25 / 25 | 20 | Underboss |

### 4.2 Reaction to being attacked (the DRS) [code: `Enemy.command_react_to_attack` 0x721958, `EnemyDef.command_initialize_DRS` 0x71f146, `Enemy.command_hit_by` 0x722bbb]

Called on the target when its attacker enters an attack state (2.1). Deterministic - **no random number is involved**.

1. Gates (no reaction if any fails): the orchestrator could force-lock the defender onto the attacker; the attacker is **not** performing an unblockable attack; the attacker is not behind the defender (tactical flag 0x400 PLACEMENT_REAR).
2. If the defender is stunned or prone the history is wiped and nothing else happens. Otherwise the animation type of the attacker's current state (LIGHTATTACK 4 / HEAVYATTACK 5 / ...) is written into a 9-entry ring of remembered attacks. A state whose animation type is NOTSET (0) is not recorded and the table is not evaluated for it.
3. Rows are tried in order. A row lists attack types newest-first; entry value 17 (`AI_SYSTEM_ONLY__ANY_ATTACK`) matches anything; a row of length n needs n remembered attacks. Rows are built only from definition slots whose first attack and result are both set.
4. Result of the first matching row (the defender's next attack target becomes the attacker): BLOCK (6) -> `CR.command_block`; DODGE (7) -> `AILib.SetGoodDodgeDir` then `CR.command_dodge` (the dodger blocks its own movement for 1.0 s) and a forced behaviour update; COUNTERATTACK (8) -> `CR.command_block` plus `CR.command_delayed_counter_attack(0.15 s, attacker)` (0xa11984; 2.3). Rows marked "(clear)" wipe the history afterwards. The very first call also switches the enemy to the aggressive state of mind.
5. The history is also wiped: after `m_nreactiontoattackdecaytime` seconds without a new attack; when the enemy becomes stunned or prone; and, when `m_tclearifblockdodgeisbroken` is set by a block/dodge reaction, when the enemy is hit anyway.

Reading the rows (L = light, H = heavy, * = any; newest first) as rules a player would recognise:

| Enemy | Rule |
|---|---|
| Thug | blocks from the 4th consecutive light attack; counters the 6th. Heavy attacks are never answered. |
| Thug Fast | dodges the first heavy attack; counters a heavy attack that follows any other attack. Light attacks are never answered. Always dodges throws. |
| Thug Big, Gimp | blocks from the 4th attack of any kind; counters the 6th. Always blocks throws. |
| Heavies | blocks from the 5th attack of any kind; counters the 6th. History fades after 2 s. |
| Dominatrix | on the 3rd consecutive attack of one kind (three lights or three heavies): if those three are all she remembers she dodges it; if she remembers any earlier attack before them she counters it and forgets everything. So after a dodge, a 4th attack of the same kind is countered. A light/heavy mix inside the last three never completes a row. Memory fades 4 s after the last attack. |
| Twilight Lady | same rows, but handled by her own reaction routine (not read). |

Because unblockable attacks skip the table altogether (gate 1), any attack made with a weapon, in uber rage, with electrified charges, or as the 2nd+ hit of a recognised combo list is neither blocked, dodged nor countered by the table - it also is not recorded.

Throw reactions are separate and probabilistic (2.8): `m_nprobblockthrow`, `m_nprobdodgethrow` per definition.

### 4.3 Grabs and group tokens (combat side) [code]

- Enemy grabs are the ENEMY_COUNTER pairs; there is no other enemy-initiated pair in the data. While a hero is the slave of such a pair and the pair has signalled FORCE_ALLOW_BREAKOUT, dodge/block/counter breaks out (2.3).
- `CombatOrchestrator.command_attack_animation_stated` promotes the attacker from "waiting" to "current" attacker of its target and stamps the cooldown; `command_character_in_repel_attacters_animation` 0x6e6cd9 makes every registered attacker of a character within its attack distance step back (used by states flagged `m_tgetawayfromme`, e.g. finishers and counters, so bystanders clear the area). The grant/queue loop that decides *who* may attack is WP4 material and was not read here.
- `CRL.command_is_immune` 0x687a91 / `CR.command_may_be_attacked` 0x68f64d: an enemy will not start a fast attack on a hero whose state is `m_timmunetoattacks` (all paired moves, getting up, specials).

### 4.4 Weapons [code: `PlayerCtrl` 0x7f5365, `WeaponBase.command_do_actual_pickup` 0x8b320d, `command_take_durability_damage` 0x8b33e0, `CR.command_set_weapon` 0x694378, `CR.UpdateAnimationValues` 0x69620b, `command_force_drop_weapon` 0x68fb16; data: `WeaponDB.fragment`]

- Only Rorschach picks weapons up: USE button, nearest unowned weapon with durability > 0 within the pick-up range (1.0 m [data]); if armed he drops the current one first; state GRAB_1H_WEAPON (id 12) plays and its PICK_UP_WEAPON event attaches the weapon. Nite Owl never holds one (no weapon models in his CharacterDef).
- Enemies receive weapons from their spawner via `command_set_weapon`, cloned from the CharacterDef's weapon model collection.
- Holding a weapon sets animation enum 5 WEAPON_ANIMATION_TYPE (0 unarmed, 1 BASH_1H, 2 BASH_2H), which selects the Armed groups and the 1H/2H base damage, and makes every non-throw attack unblockable.
- Durability starts at 1.0 [default] and drops by the weapon's loss-per-hit on every landed hit (not for states flagged `m_tignoreweaponsound`). At <= 0: break effect, then the weapon is detached and dropped, or merely disabled when `m_tdisableatbreak`. A broken or dropped weapon returns the holder to UNARMED.
- Weapons are lost: on death; on the throw button; on the DROP_WEAPON events; when disarmed by a hero's Disarm counter (event COUNTER_ATTACK_WEAPON_STEAL - the hero takes it; handler not read).
- There is **no per-weapon damage**: damage depends only on the class (1H / 2H).

| Collection | Class | Rorschach uses as 1H | Durability loss / hit | Hits to break | Disabled (not dropped) at break | Priority |
|---|---|---|---|---|---|---|
| ThugsWeaponsBIG_1H | 1H | False | 0.5 | 2 | True | 1 |
| ThugsWeaponsBIG_1H | 1H | False | 0.13 | 8 | False | 2 |
| ThugsWeaponsBIG_1H | 1H | False | 0.2 | 5 | False | 3 |
| ThugsWeapons_2H | 2H | False | 0.5 | 2 | False | 1 |
| ThugsWeapons_2H | 2H | False | 0.33 | 4 | False | 2 |
| ThugsWeapons_2H | 2H | False | 0.25 | 4 | False | 3 |
| ThugsWeapons_2H | 2H | False | 0.2 | 5 | False | 4 |
| ThugsWeapons_2H | 2H | False | 0.16 | 7 | False | 5 |
| DominitrixWeapons_1H | 1H | True | 0.16 | 7 | False | 1 |
| DominitrixWeapons_1H | 1H | True | 0.2 | 5 | False | 2 |
| GimpWeapons_1H | 1H | False | 0.16 | 7 | False | 1 |
| GimpWeapons_1H | 1H | True | 0.2 | 5 | False | 2 |
| GimpWeapons_1H | 1H | False | 0.25 | 4 | False | 3 |
| GimpWeapons_2H | 2H | False | 0.1 | 10 | False | 1 |
| GimpWeapons_2H | 2H | False | 0.25 | 4 | False | 2 |
| HeaviesWeapons_1H | 1H | False | 0.5 | 2 | True | 0 |
| HeaviesWeapons_2H | 2H | False | 0.16 | 7 | False | 1 |
| HeaviesWeapons_2H | 2H | False | 0.12 | 9 | False | 2 |
| ThugsWeapons_1H | 1H | False | 0.5 | 2 | True | 1 |
| ThugsWeapons_1H | 1H | False | 0.2 | 5 | False | 2 |
| ThugsWeapons_1H | 1H | False | 0.33 | 4 | False | 3 |
## 5. Worked example: the Dominatrix

Identity [data]: CharacterDef `DOMINATRICE`, animation class Enemy04 (model type ENEMY_04), definitions `base_def_dominatrice_enemy_def` and `phase_1_dominatrice_enemy_def` in `Enemy/Dominatrices.fragment`, combo database "Enemy Combos", weapon collection `DominitrixWeapons_1H` (two one-handed weapons, 7 and 5 hits to break; no 2H models).

| Property | Base | Phase 1 |
|---|---|---|
| Health / critical (finisher prompt) / prompt time | 100 / 44 / 3.0 s | same |
| Regeneration | none (0 per second) | same |
| Damage modifier | 1.5 | 1.5 |
| Starts attack run from / keeps distance | 4.0 m / 2.0 m | 4.5 m / 2.0 m |
| Time between attacks | 1.8-3.0 s | same |
| P fast / P slow / P combo | 0.8 / 0.2 / 0.5 | same |
| Combos (weight) | fast, dodge, heavy (1); fast, fast, heavy (3) | same |
| Throw: P block / P dodge | 0 / 0.4 | 0 / 0.8 |
| Reaction memory decay | 4.0 s; cleared if hit after a dodge | same |
| Hang-back | enabled: below 30% health, for 2-10 s at 6-10 m (`m_ihangbackwhenalliespresent` = 2, not when alone) | disabled |
| Turn rates | 10 rad/s move heading, 8 rad/s face heading | same |

### 5.1 Attacks (49 attack states) [data: `Enemy04AttackFragment.fragment`; damage = Enemy Combos base x 1.5]

How to read: "Btn" is which AI attack command selects the group (fast -> light groups, slow -> heavy groups). The state inside a group is picked at random among those whose criteria pass. Times are seconds after the state is entered (the states start mid-clip, so they are shorter than the clip). The hero is hit only if still her target and within 1.8 m at PRE_IMPACT. "Counter window" is the span after state entry in which the counter button passes the 0.13 s test (it also needs her to be targeting the hero). Initial = first attack of a string (ACTION INITIAL_ATTACK); Dash = after her rush state (AFTER_DASH_ATTACK); General = follow-ups. Damage to the hero: fast unarmed 7.5, heavy unarmed 15, fast 1H 18, heavy 1H 30 (Rorschach has 65 health, Nite Owl 90).

| Group | State | Clip | Btn | Wpn | Enter-to-PRE_IMPACT s | Enter-to-IMPACT s | BRANCH s | Free to move s | Reach m (dist+mod) | Pose sent | Dmg (base x1.5) | Counter window s | Extra criteria |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HeavyAttack/Armed 1H | 1H_Heavy_A | EN4_COM_WPN_1H_heavy_A | heavy | 1h | 1.37 | 1.45 | 1.55 | 1.85 | 1.82 (1.82+0.00) | HEAVY_UPPER_LEFT | 30 (20) | 0..1.32 |  |
| HeavyAttack/Armed 1H | 1H_Heavy_B | EN4_COM_WPN_1H_heavy_B | heavy | 1h | 1.32 | 1.40 | 1.50 | 1.80 | 1.95 (1.95+0.00) | HEAVY_UPPER_RIGHT | 30 (20) | 0..1.27 |  |
| HeavyAttack/KnockDowns/Heavy Knockdowns | BS2_KnockDown | BS2_COM_ATT_knockdown | heavy | unarmed | 0.66 | 0.73 | 0.82 | 1.07 | 1.82 (1.69+0.13) | KNOCKDOWN_UPPER_STRAIGHT | 15 (10) | 0..0.60 | ATTACK_MOVE_DIST less than 1.6; cannot be broken off; no speed-up; Twilight Lady combo only (KNOCKDOWN) |
| HeavyAttack/SuperDamage | Super_A | BS2_COM_ATT_kick_pummelling | heavy | unarmed | 2.21 | 2.29 | 2.39 | 2.69 | 2.45 (2.45+0.00) | KNOCKDOWN_UPPER_STRAIGHT | 15 (10) | 0..2.16 | no speed-up; Twilight Lady combo only (SUPER_DAMAGE) |
| HeavyAttack/AreaDamage | Area_A | BS2_COM_WPN_1H_area | heavy | unarmed | 1.15 | 1.22 | 1.30 | 1.56 | 1.64 (1.52+0.12) | HEAVY_UPPER_RIGHT | 15 (10) | 0..1.09 | sweep; cannot be broken off; no speed-up; Twilight Lady combo only (AREA_DAMAGE) |
| HeavyAttack/Stuns | Sidekick | BS2_COM_ATT_heavy_straight_sidekick | heavy | unarmed | 0.98 | 1.06 | 1.16 | 1.46 | 1.77 (1.77+0.00) | HEAVY_MIDDLE_STRAIGHT | 15 (10) | 0..0.93 | ATTACK_MOVE_DIST less than 1.8; cannot be broken off; no speed-up; Twilight Lady combo only (STUN) |
| HeavyAttack/Unarmed/InitialAttacks | Initial_Heavy_A | EN4_COM_ATT_heavy_A | heavy | unarmed | 1.07 | 1.15 | 1.25 | 1.55 | 1.64 (1.58+0.06) | HEAVY_MIDDLE_RIGHT | 15 (10) | 0..1.02 | ATTACK_MOVE_DIST less than 2 |
| HeavyAttack/Unarmed/InitialAttacks | Initial_Heavy_B | EN4_COM_ATT_heavy_B | heavy | unarmed | 1.24 | 1.32 | 1.42 | 1.72 | 1.86 (1.80+0.06) | HEAVY_MIDDLE_STRAIGHT | 15 (10) | 0..1.19 | ATTACK_MOVE_DIST less than 2.2 |
| HeavyAttack/Unarmed/InitialAttacks | Initial_Heavy_C | EN4_COM_ATT_heavy_C | heavy | unarmed | 2.08 | 2.16 | 2.26 | 2.56 | 1.87 (1.81+0.06) | HEAVY_UPPER_RIGHT | 15 (10) | 0..2.03 | ATTACK_MOVE_DIST in [1.6;2.4[ |
| HeavyAttack/Unarmed/InitialAttacks | Initial_Heavy_D | EN4_COM_ATT_heavy_D | heavy | unarmed | 1.42 | 1.50 | 1.60 | 1.90 | 1.76 (1.70+0.06) | HEAVY_UPPER_LEFT | 15 (10) | 0..1.37 | ATTACK_MOVE_DIST less than 2.1 |
| HeavyAttack/Unarmed/InitialAttacks | Initial_Heavy_E | EN4_COM_ATT_heavy_E | heavy | unarmed | 1.95 | 2.03 | 2.13 | 2.43 | 2.10 (2.10+0.00) | HEAVY_UPPER_STRAIGHT | 15 (10) | 0..1.90 | ATTACK_MOVE_DIST in [1.8;2.4[ |
| HeavyAttack/Unarmed/InitialAttacks | Initial_Heavy_F | EN4_COM_ATT_heavy_F | heavy | unarmed | 1.64 | 1.72 | 1.82 | 2.12 | 2.04 (1.98+0.06) | HEAVY_UPPER_STRAIGHT | 15 (10) | 0..1.59 | ATTACK_MOVE_DIST in [1.8;2.4[ |
| HeavyAttack/Unarmed/DashAttacks | rush_Heavy_A | EN4_COM_ATT_heavy_A | heavy | unarmed | 0.20 | 0.28 | 0.38 | 0.68 | 1.64 (1.58+0.06) | HEAVY_MIDDLE_RIGHT | 15 (10) | 0..0.15 |  |
| HeavyAttack/Unarmed/DashAttacks | rush_Heavy_B | EN4_COM_ATT_heavy_B | heavy | unarmed | 0.10 | 0.18 | 0.28 | 0.58 | 1.86 (1.80+0.06) | HEAVY_MIDDLE_STRAIGHT | 15 (10) | 0..0.05 |  |
| HeavyAttack/Unarmed/DashAttacks | rush_Heavy_F | EN4_COM_ATT_heavy_F | heavy | unarmed | 0.28 | 0.36 | 0.46 | 0.76 | 2.04 (1.98+0.06) | HEAVY_UPPER_STRAIGHT | 15 (10) | 0..0.23 |  |
| HeavyAttack/Unarmed/GeneralAttacks | Heavy_A | EN4_COM_ATT_heavy_A | heavy | unarmed | 0.72 | 0.80 | 0.90 | 1.20 | 1.64 (1.58+0.06) | HEAVY_MIDDLE_RIGHT | 15 (10) | 0..0.67 | ATTACK_MOVE_DIST less than 2 |
| HeavyAttack/Unarmed/GeneralAttacks | Heavy_B | EN4_COM_ATT_heavy_B | heavy | unarmed | 0.75 | 0.83 | 0.93 | 1.23 | 1.86 (1.80+0.06) | HEAVY_MIDDLE_STRAIGHT | 15 (10) | 0..0.70 | ATTACK_MOVE_DIST less than 2.2 |
| HeavyAttack/Unarmed/GeneralAttacks | Heavy_C | EN4_COM_ATT_heavy_C | heavy | unarmed | 1.05 | 1.13 | 1.23 | 1.53 | 1.87 (1.81+0.06) | HEAVY_UPPER_RIGHT | 15 (10) | 0..1.00 | ATTACK_MOVE_DIST less than 2.4 |
| HeavyAttack/Unarmed/GeneralAttacks | Heavy_D | EN4_COM_ATT_heavy_D | heavy | unarmed | 1.00 | 1.08 | 1.18 | 1.48 | 1.76 (1.70+0.06) | HEAVY_UPPER_LEFT | 15 (10) | 0..0.95 | ATTACK_MOVE_DIST less than 2.1 |
| HeavyAttack/Unarmed/GeneralAttacks | Heavy_E | EN4_COM_ATT_heavy_E | heavy | unarmed | 0.82 | 0.90 | 1.00 | 1.30 | 2.10 (2.10+0.00) | LIGHT_MIDDLE_STRAIGHT | 15 (10) | 0..0.77 | ATTACK_MOVE_DIST in [1.8;2.4[ |
| HeavyAttack/Unarmed/GeneralAttacks | Heavy_F | EN4_COM_ATT_heavy_F | heavy | unarmed | 1.10 | 1.18 | 1.28 | 1.58 | 2.04 (1.98+0.06) | HEAVY_UPPER_STRAIGHT | 15 (10) | 0..1.05 | ATTACK_MOVE_DIST in [1.8;2.4[ |
| LightAttacks/Armed 1H | 1H_light_A | EN4_COM_WPN_1H_light_A | light | 1h | 0.92 | 1.00 | 1.10 | 1.40 | 1.45 (1.45+0.00) | LIGHT_UPPER_RIGHT | 18 (12) | 0..0.87 |  |
| LightAttacks/Armed 1H | 1H_light_B | EN4_COM_WPN_1H_light_B | light | 1h | 1.25 | 1.33 | 1.43 | 1.73 | 1.79 (1.79+0.00) | LIGHT_UPPER_LEFT | 18 (12) | 0..1.20 |  |
| LightAttacks/Armed 1H | 1H_light_C | EN4_COM_WPN_1H_light_C | light | 1h | 0.51 | 0.59 | 0.69 | 0.99 | 1.32 (1.32+0.00) | LIGHT_MIDDLE_RIGHT | 18 (12) | 0..0.46 | NOT ACTION INITIAL_ATTACK |
| LightAttacks/Armed 1H | 1H_light_D | EN4_COM_WPN_1H_light_D | light | 1h | 1.01 | 1.09 | 1.19 | 1.49 | 1.44 (1.44+0.00) | LIGHT_UPPER_STRAIGHT | 18 (12) | 0..0.96 |  |
| LightAttacks/KnockDowns | BS2_KnockDown | BS2_COM_WPN_1H_unblockable | light | unarmed | 0.52 | 0.60 | 0.70 | 1.00 | 1.35 (1.35+0.00) | KNOCKDOWN_UPPER_STRAIGHT | 7.5 (5) | 0..0.47 | ATTACK_MOVE_DIST less than 1.6; cannot be broken off; no speed-up; Twilight Lady combo only (KNOCKDOWN) |
| LightAttacks/Unarmed/InitialAttacks | Light_A | EN4_COM_ATT_light_A | light | unarmed | 1.21 | 1.29 | 1.39 | 1.69 | 0.98 (0.91+0.07) | LIGHT_MIDDLE_RIGHT | 7.5 (5) | 0..1.16 |  |
| LightAttacks/Unarmed/InitialAttacks | Light_B | EN4_COM_ATT_light_B | light | unarmed | 1.52 | 1.60 | 1.70 | 2.00 | 1.18 (1.11+0.07) | LIGHT_UPPER_LEFT | 7.5 (5) | 0..1.47 |  |
| LightAttacks/Unarmed/InitialAttacks | Light_C | EN4_COM_ATT_light_C | light | unarmed | 1.38 | 1.46 | 1.56 | 1.86 | 1.46 (1.39+0.07) | LIGHT_MIDDLE_STRAIGHT | 7.5 (5) | 0..1.33 |  |
| LightAttacks/Unarmed/InitialAttacks | Light_D | EN4_COM_ATT_light_D | light | unarmed | 1.40 | 1.48 | 1.58 | 1.88 | 1.52 (1.45+0.07) | LIGHT_MIDDLE_RIGHT | 7.5 (5) | 0..1.35 |  |
| LightAttacks/Unarmed/InitialAttacks | Light_E | EN4_COM_ATT_light_E | light | unarmed | 1.20 | 1.28 | 1.38 | 1.68 | 1.32 (1.25+0.07) | LIGHT_UPPER_LEFT | 7.5 (5) | 0..1.15 |  |
| LightAttacks/Unarmed/InitialAttacks | Light_F | EN4_COM_ATT_light_F | light | unarmed | 1.68 | 1.76 | 1.86 | 2.16 | 1.36 (1.29+0.07) | LIGHT_UPPER_STRAIGHT | 7.5 (5) | 0..1.63 |  |
| LightAttacks/Unarmed/InitialAttacks | Light_G | EN4_COM_ATT_light_G | light | unarmed | 1.47 | 1.55 | 1.65 | 1.95 | 1.42 (1.35+0.07) | LIGHT_UPPER_STRAIGHT | 7.5 (5) | 0..1.42 |  |
| LightAttacks/Unarmed/InitialAttacks | Light_H | EN4_COM_ATT_light_H | light | unarmed | 1.25 | 1.33 | 1.43 | 1.73 | 1.58 (1.51+0.07) | LIGHT_UPPER_RIGHT | 7.5 (5) | 0..1.20 |  |
| LightAttacks/Unarmed/DashAttacks | Dash_Light_A | EN4_COM_ATT_light_A | light | unarmed | 0.29 | 0.37 | 0.46 | 0.74 | 0.98 (0.91+0.07) | LIGHT_MIDDLE_RIGHT | 7.5 (5) | 0..0.24 |  |
| LightAttacks/Unarmed/DashAttacks | Dash_Light_C | EN4_COM_ATT_light_C | light | unarmed | 0.30 | 0.37 | 0.46 | 0.73 | 1.46 (1.39+0.07) | LIGHT_MIDDLE_STRAIGHT | 7.5 (5) | 0..0.24 |  |
| LightAttacks/Unarmed/DashAttacks | Dash_Light_D | EN4_COM_ATT_light_D | light | unarmed | 0.25 | 0.33 | 0.43 | 0.73 | 1.52 (1.45+0.07) | LIGHT_MIDDLE_RIGHT | 7.5 (5) | 0..0.20 |  |
| LightAttacks/Unarmed/DashAttacks | Dash_Light_E | EN4_COM_ATT_light_E | light | unarmed | 0.21 | 0.29 | 0.39 | 0.69 | 1.32 (1.25+0.07) | LIGHT_UPPER_LEFT | 7.5 (5) | 0..0.16 |  |
| LightAttacks/Unarmed/DashAttacks | Dash_Light_F | EN4_COM_ATT_light_F | light | unarmed | 0.39 | 0.46 | 0.55 | 0.82 | 1.36 (1.29+0.07) | LIGHT_UPPER_STRAIGHT | 7.5 (5) | 0..0.33 |  |
| LightAttacks/Unarmed/DashAttacks | Dash_Light_G | EN4_COM_ATT_light_G | light | unarmed | 0.29 | 0.36 | 0.45 | 0.72 | 1.42 (1.35+0.07) | LIGHT_UPPER_STRAIGHT | 7.5 (5) | 0..0.23 |  |
| LightAttacks/Unarmed/DashAttacks | Dash_Light_H | EN4_COM_ATT_light_H | light | unarmed | 0.26 | 0.33 | 0.42 | 0.69 | 1.58 (1.51+0.07) | LIGHT_UPPER_RIGHT | 7.5 (5) | 0..0.20 |  |
| LightAttacks/Unarmed/GeneralAttacks | Light_A | EN4_COM_ATT_light_A | light | unarmed | 0.51 | 0.59 | 0.69 | 0.99 | 0.98 (0.91+0.07) | LIGHT_MIDDLE_RIGHT | 7.5 (5) | 0..0.46 |  |
| LightAttacks/Unarmed/GeneralAttacks | Light_B | EN4_COM_ATT_light_B | light | unarmed | 0.62 | 0.70 | 0.80 | 1.10 | 1.18 (1.11+0.07) | LIGHT_UPPER_LEFT | 7.5 (5) | 0..0.57 |  |
| LightAttacks/Unarmed/GeneralAttacks | Light_C | EN4_COM_ATT_light_C | light | unarmed | 0.81 | 0.89 | 0.99 | 1.29 | 1.46 (1.39+0.07) | LIGHT_MIDDLE_STRAIGHT | 7.5 (5) | 0..0.76 |  |
| LightAttacks/Unarmed/GeneralAttacks | Light_D | EN4_COM_ATT_light_D | light | unarmed | 0.55 | 0.63 | 0.73 | 1.03 | 1.52 (1.45+0.07) | LIGHT_MIDDLE_RIGHT | 7.5 (5) | 0..0.50 |  |
| LightAttacks/Unarmed/GeneralAttacks | Light_E | EN4_COM_ATT_light_A | light | unarmed | 0.70 | 0.78 | 0.87 | 1.14 | 1.32 (1.25+0.07) | LIGHT_UPPER_LEFT | 7.5 (5) | 0..0.65 |  |
| LightAttacks/Unarmed/GeneralAttacks | Light_F | EN4_COM_ATT_light_F | light | unarmed | 0.87 | 0.95 | 1.05 | 1.35 | 1.36 (1.29+0.07) | LIGHT_UPPER_STRAIGHT | 7.5 (5) | 0..0.82 |  |
| LightAttacks/Unarmed/GeneralAttacks | Light_G | EN4_COM_ATT_light_G | light | unarmed | 0.89 | 0.97 | 1.07 | 1.37 | 1.42 (1.35+0.07) | LIGHT_UPPER_STRAIGHT | 7.5 (5) | 0..0.84 |  |
| LightAttacks/Unarmed/GeneralAttacks | Light_H | EN4_COM_ATT_light_H | light | unarmed | 0.71 | 0.79 | 0.89 | 1.19 | 1.58 (1.51+0.07) | LIGHT_UPPER_RIGHT | 7.5 (5) | 0..0.66 |  |

Notes:

- The four BS2_* states (KnockDowns, SuperDamage, AreaDamage, Stuns groups) require an OVERRIDE_ATTACK_COMBO value that only Twilight Lady's combo strings produce; "Enemy Combos" strings have no override, so an ordinary Dominatrix never plays them [data + code]. They are listed because they live in the same class; the Initial groups are also closed to Twilight Lady (`NOT TWILIGHT_LADY`), who starts with the Dash group instead.
- Armed 1H states have no INITIAL/DASH split and need ATTACK_MOVE_DIST < 1.8 (light) / 2.5 (heavy).
- `RushToAttack` (clip `EN4_COM_ATT_dash_cycle`, loop 0.97 s): entered when the attack is issued at 0.1-5 m but no attack state's distance criterion holds; re-issues the attack after 0.4 s as a Dash attack.
- Her attack can be: **dodged** (Rorschach; she then loses her target and her combo, and a following fast attack is his combo counter); **blocked** (Nite Owl holding block with power > 0: she plays `AttackBlocked`, he loses 0.04 power, takes no damage); **countered** with the counter button inside the window above; **out-ranged** (more than 1.8 m away at PRE_IMPACT); **interrupted** - any hit on her puts her in a hit reaction (`break_off_attack` / HITTAKEN); she has no armoured attack states except the four BS2 ones.
- What the hit does to the hero: the "Pose sent" column, converted by direction/height (2.5), selects the hero's hit reaction; heavy/knock-down poses give stronger camera recoil; no stun or push-back (her strings carry none).

### 5.2 Her defensive moves and paired moves she masters

| State | Clip | Length s | master_of | Selected when | IMPACT (damage) s from entry | ALLOW_ATTACK s |
|---|---|---|---|---|---|---|
| BackFlip | BS2_COM_MOV_cartwheel_back_cycle | 1.03333 | None | ANY OF(DIRECTION less than -1.55|DIRECTION greater than or equal to 1.55); TARGET_LOCK; SPEED >= 0.01 [entry] | - | - |
| DodgeLeft | EN4_COM_ATT_dodge_left | 3.16667 | None | DIRECTION in [-2.4;0[; ACTION DODGE [entry] | - | - |
| DodgeRight | EN4_COM_ATT_dodge_right | 3.06667 | None | DIRECTION in [0;2.4[; ACTION DODGE [entry] | - | - |
| DodgeBack | EN4_COM_ATT_dodge_back | 2.33333 | None | NOT DIRECTION in [-2.3;2.3[; ACTION DODGE [entry] | - | - |
| Counter_B RSH_CattleProd | BS2_COM_ATT_cattleprod_counter_RSH_B | 6.8 | 30 | RORSCHACH; ACTION COUNTER_ATTACK [entry]; TWILIGHT_LADY | 3.7562 | - |
| Counter_A NTO_CattleProd | BS2_COM_ATT_cattleprod_counter_NTO_A | 5.66667 | 29 | NITE_OWL; ACTION COUNTER_ATTACK [entry]; TWILIGHT_LADY | 3.5079 | - |
| Counter_A RSH_CattleProd | BS2_COM_ATT_cattleprod_counter_RSH_A | 6.66667 | 29 | RORSCHACH; ACTION COUNTER_ATTACK [entry]; TWILIGHT_LADY | 4.127 | - |
| Counter_B NTO_CattleProd | BS2_COM_ATT_cattleprod_counter_NTO_B | 9.23333 | 30 | NITE_OWL; ACTION COUNTER_ATTACK [entry]; TWILIGHT_LADY | 6.5073 | - |
| Counter_A RSH | EN4_COM_ATT_counter_RSH_A | 4.33333 | 10 | RORSCHACH; ACTION COUNTER_ATTACK [entry] | 1.5683 | - |
| Counter_A NTO | EN4_COM_ATT_counter_NTO_A | 3.16667 | 10 | NITE_OWL; ACTION COUNTER_ATTACK [entry] | 1.0761 | - |
| Counter_RSH_WPN | EN4_COM_WPN_1H_counter_RSH | 3.8 | 28 | RORSCHACH; ANY OF(BASH_1H|TWILIGHT_LADY); ACTION COUNTER_ATTACK [entry] | 1.1745 | - |
| Counter_B NTO | EN4_COM_ATT_counter_NTO_B | 5.0 | 27 | NITE_OWL; UNARMED; NOT TWILIGHT_LADY; ACTION COUNTER_ATTACK [entry] | 0.9223 | - |
| Counter_B RSH | EN4_COM_ATT_counter_RSH_B | 3.4 | 27 | RORSCHACH; ACTION COUNTER_ATTACK [entry] | 1.2364 | - |
| Counter_NTO_WPN | EN4_COM_WPN_1H_counter_NTO | 4.0 | 28 | NITE_OWL; ANY OF(BASH_1H|TWILIGHT_LADY); ACTION COUNTER_ATTACK [entry] | 1.4909 | - |
| RushToAttack | EN4_COM_ATT_dash_cycle | 0.96667 | None | ATTACK_MOVE_DIST in [0.1;5[; ACTION NORMAL_ATTACK [entry] | - | - |
| BackFlick | EN4_COM_ATT_dodge_back | 2.33333 | None |  | - | - |

- Dodge states are chosen by the DIRECTION value set by `AILib.SetGoodDodgeDir`. She has **no block state**: a BLOCK action has nothing to enter, so the "counter" reaction shows only as the counter pair 0.15 s later [inferred from the absence of BLOCK states in Enemy04].
- Her counters (pair ids 10, 27 unarmed; 28 with a 1H weapon) hit the hero at the IMPACT time shown for `10 (Enemy Combos counter) x 0.75 (playable victim) x 1.5 = 11.25` damage. The hero can break out while the pair signals FORCE_ALLOW_BREAKOUT. The cattle-prod counters (pair ids 29, 30) are Twilight Lady only; her database counter base is 20 -> 22.5.

### 5.3 What the player can do to her, and her reactions

| Player action | Rule | Result on her |
|---|---|---|
| 1st / 2nd attack of one kind | no table row matches | hit: 5 (fast) or 12 (heavy) damage unarmed; 15 / 25 with 1H; 25 / 35 with 2H |
| 3rd consecutive same-kind attack, nothing older remembered | row LLL / HHH -> DODGE | she dodges (left / right / back by direction), attacker loses target |
| 3rd same-kind attack with an older attack remembered, or the attack after a dodge | row LLL* / HHH* -> COUNTERATTACK | counter pair on the hero 0.15 s later, memory cleared |
| alternate light and heavy | never three of a kind | every attack lands |
| attack from behind | gate PLACEMENT_REAR | no reaction, lands |
| any unblockable attack (weapon in hand, uber rage, electrified, 2nd+ item of a combo list) | gate | no reaction, lands, not remembered |
| wait 4 s | decay | memory cleared |
| throw | 40% dodge (80% in phase 1), never blocks; not when stunned/prone or not facing | thrown: pair id 1, `ThrownByRorschach` / clip `EN4_COM_DMG_throw_RSH` |
| counter button during her attack | 2.3 window | hero counter pair: 20 damage; if her health <= 20 it becomes a finisher |
| drop her below 44 health with a player hit | 3.2 | finisher prompt for 3.0 s (random button) -> finisher pair, instant kill |
| stun string (FFFF / FHF Rorschach; FHF / FFF Nite Owl) | combo stun 6 s | STUN pose -> `StunUpper` state (on knee), then Stunned states; a heavy attack on a kneeling target is the KNOCKDOWN string |
| knock-down string / 2H heavy | KNOCKDOWN pose | knock-down state then ragdoll; prone -> any attack becomes a KICK; three kicks = stomp string (ability 4) |

Hit reactions (HitTakenGroup of Enemy04) [data]:

| State | Clip | Length s | Selected by DAMAGE_POSE (+criteria) | CLEAR_DEADZONE s | ALLOW_ATTACK s | Flags |
|---|---|---|---|---|---|---|
| Ragdoll-Hit | EN1_COM_DMG_knockdown_body_front | 0.8 | RELATIVE_HEAD_HEIGHT less than 0; ALL OF(ANY OF(KNOCKDOWN_MIDDLE_BACK|KNOCKDOWN_MIDDLE_LEFT|KNOCKDOWN_MIDDLE_RIGHT|KNOCKDOWN_MIDDLE_STRAIGHT|KNOCKDOWN_UPPER_BACK|KNOCKDOWN_UPPER_LEFT|KNOCKDOWN_UPPER_RIGHT|KNOCKDOWN_UPPER_STRAIGHT)|NONE); NOT TWILIGHT_LADY | - | - | disallow attack, stun-lock |
| LightUpperStraight | EN4_COM_DMG_light_head_front | 1.43333 | LIGHT_UPPER_STRAIGHT | 0.3241 | - | disallow attack, stun-lock |
| LightUpperLeft | EN4_COM_DMG_light_head_left | 2.06667 | LIGHT_UPPER_LEFT | 0.4313 | - | disallow attack, stun-lock |
| LightUpperRight | EN4_COM_DMG_light_head_right | 1.43333 | LIGHT_UPPER_RIGHT | 0.349 | - | disallow attack, stun-lock |
| HeavyUpperStraight | EN4_COM_DMG_heavy_head_front | 1.6 | HEAVY_UPPER_STRAIGHT | 0.384 | - | disallow attack, stun-lock |
| HeavyUpperLeft | EN4_COM_DMG_heavy_head_left | 2.06667 | HEAVY_UPPER_LEFT | 0.434 | - | disallow attack, stun-lock |
| HeavyUpperRight | EN4_COM_DMG_heavy_head_right | 1.43333 | HEAVY_UPPER_RIGHT | 0.43 | - | disallow attack, stun-lock |
| LightMiddleStraight | EN4_COM_DMG_light_body_front | 1.3 | LIGHT_MIDDLE_STRAIGHT | 0.2836 | - | disallow attack, stun-lock |
| LightMiddleLeft | EN4_COM_DMG_light_body_left | 1.43333 | LIGHT_MIDDLE_LEFT | 0.3909 | - | disallow attack, stun-lock |
| LightMiddleRight | EN4_COM_DMG_light_body_right | 1.53333 | LIGHT_MIDDLE_RIGHT | 0.3485 | - | disallow attack, stun-lock |
| HeavyMiddleStraight | EN4_COM_DMG_heavy_body_front | 1.7 | HEAVY_MIDDLE_STRAIGHT | 0.476 | - | disallow attack, stun-lock |
| HeavyMiddleLeft | EN4_COM_DMG_heavy_body_left | 1.93333 | HEAVY_MIDDLE_LEFT | 0.5413 | - | disallow attack, stun-lock |
| HeavyMiddleRight | EN4_COM_DMG_heavy_body_right | 1.56667 | HEAVY_MIDDLE_RIGHT | 0.4387 | - | disallow attack, stun-lock |
| StunUpper | EN4_COM_DMG_stun_head_front | 2.56667 | ANY OF(STUN_UPPER|STUN_MIDDLE) | 0.77 | - | disallow attack, stun-lock ; events KNEE |
| LightUpperBack | EN4_COM_DMG_light_head_back | 1.6 | LIGHT_UPPER_BACK | 0.4364 | - | disallow attack, stun-lock ; events REVERSE_HEADING |
| LightMiddleBack | EN4_COM_DMG_light_body_back | 1.3 | LIGHT_MIDDLE_BACK | 0.3073 | - | disallow attack, stun-lock ; events REVERSE_HEADING |
| HeavyMiddleBack | EN4_COM_DMG_heavy_body_back | 1.7 | HEAVY_MIDDLE_BACK | 0.3555 | - | disallow attack, stun-lock ; events REVERSE_HEADING |
| HeavyUpperBack | EN4_COM_DMG_heavy_head_back | 1.8 | HEAVY_UPPER_BACK | 0.4255 | - | disallow attack, stun-lock ; events REVERSE_HEADING |
| StunUpperBack | EN4_COM_DMG_stun_head_back_knee | 2.43333 | ANY OF(STUN_UPPER_BACK|STUN_MIDDLE_BACK) | 0.73 | - | disallow attack, stun-lock ; events KNEE,REVERSE_HEADING |
| KnockdownStraightTwilightLady | EN4_COM_DMG_heavy_head_front | 1.6 | ANY OF(KNOCKDOWN_UPPER_STRAIGHT|KNOCKDOWN_UPPER_LEFT|KNOCKDOWN_UPPER_RIGHT|KNOCKDOWN_MIDDLE_LEFT|KNOCKDOWN_MIDDLE_STRAIGHT|KNOCKDOWN_MIDDLE_RIGHT); TWILIGHT_LADY | 0.3934 | - | disallow attack, immune, stun-lock |
| KnockdownBackTwilightLady | EN4_COM_DMG_heavy_body_back | 1.7 | ANY OF(KNOCKDOWN_MIDDLE_BACK|KNOCKDOWN_UPPER_BACK); TWILIGHT_LADY | 0.4327 | - | disallow attack, immune, stun-lock ; events REVERSE_HEADING |
| KnockdownUpperStraight | EN1_COM_DMG_knockdown_body_front | 0.8 | ANY OF(KNOCKDOWN_UPPER_STRAIGHT|KNOCKDOWN_UPPER_LEFT|KNOCKDOWN_UPPER_RIGHT) | 0.2182 | - | disallow attack, immune, stun-lock |
| KnockdownUpperBack | EN4_COM_DMG_knockdown_head_back | None | KNOCKDOWN_UPPER_BACK | - | - | disallow attack, immune, stun-lock ; events REVERSE_HEADING |
| KnockdownMiddleStraight | EN4_COM_DMG_knockdown_body_front | None | ANY OF(KNOCKDOWN_MIDDLE_LEFT|KNOCKDOWN_MIDDLE_STRAIGHT|KNOCKDOWN_MIDDLE_RIGHT) | - | - | disallow attack, immune, stun-lock |
| KnockdownMiddleBack | EN4_COM_DMG_knockdown_body_back | None | KNOCKDOWN_MIDDLE_BACK | - | - | disallow attack, immune, stun-lock ; events REVERSE_HEADING |

Paired moves in which she is the partner (victim), primary pairs only [data]: counters by Rorschach `Countered_by_Rorshack_A..G, X, Y, 1H, 2H` and `Disarmed_by_Rorshack` (pair ids 10, 27-32, 55, 57, 71, 72, 81); by Nite Owl `Countered_by_Nite_Owl_A..G, X, Y` and `Disarmed_by_Nite_Owl` (10, 27-32, 55, 71, 72); finishers `Finished_by_Rorshack_A..J, 1H, 2H` (8, 33-38, 56, 79, 80, 82, 83) and `Finished_by_NiteOwl_A..J` (8, 33-38, 56, 79, 80); throw (1); bull-rush impact (11). The master picks by its own weapon class; the Disarm masters require **her** to hold a weapon. Full list with clips: JSON `pair_triggers` filtered on `partner_class == "Enemy04"`.

## 6. JSON tables (`findings/wp3_combat_tables.json`)

| Key | Content |
|---|---|
| `enums`, `enum_extra` | the enum tables the other keys refer to (incl. combo items, target status, buttons, TARGET_MODE) |
| `code_constants` | 32 constants with exe address, width and meaning (all re-read from exe bytes) |
| `special_def_data` | CharacterSpecialDef (rage / electricity numbers) |
| `combos_data` | 12 combo databases: base damages and every string (items with target status, bonus damage, stun, push-back, override, flags, ability id) |
| `character_defs_data`, `ai_defs_data` | health / regeneration / modifier per CharacterDef; every EnemyDef and PartnerDef with probabilities, timings, decoded reaction rows and combo lists |
| `weapons_data` | 21 weapons |
| `attack_states` | per animation class, every attack / counter / finisher / throw / dodge / block / special state: clip, duration, event times from state entry and in clip time, impact distance + modification, impact position / direction, damage pose, state and inherited group criteria, random-pick flag, combat flags, sweep parameters, button and weapon class, required combo override |
| `hit_reaction_states` | per class, DAMAGE and STUNNED states with their pose criteria and recovery times |
| `damage_pose_rules` | the five pose conversions as explicit maps, upper-pose set, recoil and slow-motion classes |
| `pair_trigger_rules`, `pair_triggers` | the five trigger rules and the rule for each of the 413 pairs |

## 7. Proposals for the animation metadata export (not implemented)

1. **Per-state `combat` block** (all values are in the fragments already parsed here):
   `is_attack`, `button` (light / heavy from the PUNCH / HEAVY_PUNCH group criterion), `weapon_class`, `entry` (initial / after_dash / general), `combo_override_required`, `damage_pose`, `impact {time_from_entry_s, pre_impact_s, branch_s, clear_deadzone_s, can_move_s, distance_m, distance_modification_m, pos, dir, bone}`, `flags {disallow_attack, immune_to_attacks, keep_combo_alive, stun_lock, sweep, ignore_weapon_sound, get_away_from_me, immune_to_combo_speedup, ignore_target_lock}`, `sweep {within_speed, begin/impact/end angle, length, playpos}`, `idle_time_s [min, max]` for SET_IDLE_TIME states, `allow_attacks_s` for reactions.
2. **Inherited group criteria on every state**, not only on pair masters: `group_criteria` (ordered outermost to innermost, each with `entry_only`) and `group_random_pick`. Without them a consumer cannot tell Initial / Dash / General or Armed / Unarmed variants of the same clip apart. Interval criteria should be rendered from the stored interval values, not from the node name (several names are stale, e.g. a node named "less than 2.2" storing max 2.0).
3. **Per-pair `trigger` block**: `rule` (counter / finisher / throw / bull_rush / enemy_counter), `action` (control action id), `opponent_models`, `master_weapon_class`, `partner_weapon_required`, `distance_m [min, max]`, `specific_model`, `damage {source: counter_base | kill | bull_rush | none, at_event: IMPACT | KILL_ANIMATION_PARTNER | BULLMOVE_IMPACT, time_from_entry_s}`, `breakout {from_s, to_s}` from the FORCE_ALLOW_BREAKOUT / ..._NO_MORE events.
4. **Class-level `combat` block** linking the animation class to its data: CharacterDef(s), combo database, base damages, damage modifier, reaction rows - so a viewer can show "this attack does N damage" without a second file.
5. Event times should be exported both as clip time and as time from state entry (the latter depends on `m_nstartplaypos`); the combo speed-up start position (CLEAR_DEADZONE time minus 0.15 / 0.2 s) can be precomputed per attack state as `combo_entry_playpos`.
6. Add enum 7 TARGET_MODE value names (2 dead, 3 stunned/knee, 4 prone) to the enum table; they are currently null.

## 8. Not established, and what each would take

| Item | What is missing | What it would take |
|---|---|---|
| Who may attack when (orchestrator grant loop, `AttackEnemy.command_may_attack`, `FindUsableCombo`, `Enemy.Evaluate`) | treated as given | WP4; read `AttackEnemy` and CO request/register handlers |
| Sender of `i_will_hit_you` (what fills the dodge list) | handler read, caller not located | grep the lifted corpus for the command id and read the caller |
| Sweep volume stepping (`CharacterSweepAttack` loop, hit test geometry) | only `begin` read | read the remaining ~3 handlers of the class |
| Target selection filter (`brain.get_target_empty_ignore`), i.e. whether allies can be soft-targeted | not read | read the AIBrain/Perception native or script handler |
| Throw: control flow of the block/dodge branch and where throw damage (15) is applied; THROW_MODE_STORE_TARGET / THROW_BRANCH_POINT event cases | lifted text only, events 38 and 70 skimmed | disassembly of 0x68d870 around the two RNG calls; read event cases 0x26, 0x46 |
| Bull rush contact (CHARGE physics state -> BullmoveImpact pair), secondary victims | BULLMOVE_IMPACT read, contact not | read the physics-state-4 collision callback in CharacterRoot |
| Nite Owl grenade and electric blast resolution (events 29-31), electrify charge bookkeeping | data known, handlers not read | read event cases 0x1d-0x1f and `CharacterEffectDef` |
| Weapon steal on disarm (event 32) | not read | read event case 0x20 |
| Twilight Lady reaction routine (`command_react_to_attack_twilight_lady`), Underboss `is_attack_successful` | not read | read those two handlers |
| Unique attack id de-duplication | id creation seen, check not located | search readers of damage struct +0x38 in `give_damage` |
| `takeahitstruct` | no use found in the handlers read | grep corpus for the struct type |
| RELATIVE_HEAD_HEIGHT source (used for prone, block test and throw fail) | setter not read | read `CR.UpdateAnimationValues` value 14 |
| Difficulty | no reader in the damage path; `g_nglobaldamagefactor` has no script writer | search native code for writers of the global and for the settings value |
| Property defaults marked [default] | registry defaults; the instance fragments of CharacterRoot / CharacterRootLogic templates were not diffed | parse `CharacterRootTemplate_*.fragment` for overrides of `_nslomotimemultiplier`, `_ncleardeadzoneoverride`, `_thitinvsmodedefenddeadzonetime` |
| Hit sounds / impact effects | out of scope here | WP6 / WP7 |
| Dead-state details (ragdoll freeze, corpse removal, event id broadcast at the end) | call level only | WP2 |
| Achievement conditions | hooks listed only | read the two Achievement classes (about 2250 lines) |
