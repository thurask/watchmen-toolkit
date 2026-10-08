# Combat metadata (`combat` in `anim_meta.json`)

`wlib/combat_meta.py` adds the game's combat rules to the animation metadata
table that `watchmen animmeta` / `watchmen char` write. The table stays
`watchmen-anim-meta/2`: everything here is additive and marked by
`combat_format: "watchmen-combat-meta/1"`. A table without combat data (no
CharacterDef / combo fragments in the extract, or a fragment the module cannot
read) simply has no `combat_format`.

Source of every statement: `re/wp3_combat.md` (the game's script, lifted
from `KapowMultiDEDRM.exe`, Part 2 PC) and the later reads of the damage path,
the area attacks, the sweep and the enemy AI, each cited with its handler in
`combat.rules`. Evidence classes used below and in the JSON:

- **read from code** – a script handler, cited with its address; numeric
  constants were read from the executable's bytes (`combat.rules.constants`).
- **data** – read from the shipped binary fragments.
- **derived** – computed by the toolkit from the two above (said per field).
- **not established** – left out; listed in `combat.not_established`.

## Where things are

| Key | Content |
|---|---|
| `classes.<Class>.states[*].group_criteria` | criteria the state inherits from its state groups, outermost first: `[{group, random_pick, criteria: [{text, entry_only?}]}]`. Groups that test nothing and do not pick at random are left out (the state's `path` names them). |
| `classes.<Class>.states[*].criteria_rendered` | the state's own criteria, same rendering |
| `classes.<Class>.states[*].combat` | per-state combat block (below); absent on states without a combat role |
| `pairs[*].trigger` | what starts the paired move and what it does (below) |
| `combat.rules` | the fixed rules as data: constants, damage formula with its receiving side, unblockable, defender options, impact and sweep, ragdoll contact damage (the throw), who may attack when, Twilight Lady's reaction, combo rule, finisher prompt, damage-pose conversions, pair rules and the area attacks, the bull rush, the partner AI (`partner_ai`), what special handling BULL_MOVE does, and — when the data has an `UnderbossDef` — `underboss` |
| `combat.enums` | enum tables the block uses that `enums` does not carry (TARGET_MODE, combo items, target status mask, AI definition type, buttons, and the partner AI families PARTNER_AI_STATE, PARTNER_MODIFIED_STATE, PLAYER_AI_STATES, REPEAT_DEFENCE, STOP_CRITERIA, TACTICAL_INFO), each with its evidence |
| `combat.achievements` | the achievement controllers of the data: names, conditions, thresholds, two defects (below) |
| `combat.combo_databases` | every `CharacterComboDatabase`: base damages and strings |
| `combat.character_defs` | every `CharacterDef`: health, finisher threshold, damage modifier, combo database, weapon collections, and the animation class it uses |
| `combat.ai_defs` | every `EnemyDef` / `PartnerDef`: attack probabilities, timings, throw reactions, damage modifier (`damage_modifier_own` as stored, `damage_modifier_effective` with `damage_modifier_source`), reaction rows, combo list |
| | PartnerDef records also carry the follow distances, the kill-vs-crowd-control weight, the reaction / special probabilities and cooldowns, and `visual_range`; their use is in `combat.rules.partner_ai`. `rules.partner_ai.waypoint_move` holds the constants of `BehaviorWaypointMove` (0x6289b4, 0x629b68, 0x62aef5) and says that an AI partner never uses a trigger from there (inferred from two read facts); `known_defects` states the kill-target defect with its two effects (0x6e6495, 0x6e388e). |
| | `crowd_control_combos[*].weight`: the engine builds a list with each combo repeated `weight` times, keeps only combos whose every item fits the current weapon animation type (items 1/4 unarmed, 2/5 one-handed, 3/6 two-handed), and draws uniformly (`FindUsableCombo` 0x6f2971, `TryAddComboToList` 0x5eee3a). `m_tdocrowdcontrolcombo` is not read by the partner behaviours. |
| `combat.special_def` | `CharacterSpecialDef` (rage / electricity / bull-rush numbers) |
| `combat.weapons` | the weapon database (class, durability loss per hit, hits to break) |
| `combat.classes.<Class>` | links and totals per animation class |
| `combat.totals`, `combat.not_established` | counts; what is not exported and why |

### Rendered criteria

Texts are built from the STORED values, not from the node caption (several
captions are stale: a node named "ATTACK_MOVE_DIST less than 2.2" stores the
maximum 2.0). Interval kinds follow `MathLib.InsideInterval` 0x77aa25:
`X in [a;b[`, `X < b`, `X >= a`. An ENUM criterion reads `VARIABLE = VALUE`;
`TARGET_MODE` (enum 7) uses the names of `combat.enums.TARGET_MODE`. `NOT` is
the criterion's own flag. `entry_only` criteria are not tested while the
current state lies inside the group that owns them. The existing `criteria` /
`criteria_tree` fields are unchanged.

`random_pick`: a group with "Choose Random State" starts its member scan at a
random member; otherwise the first acceptable member in tree order is taken
(GetValidState 0x5f0792).

## The per-state `combat` block

`kind` is one of `attack` (the state has `m_tisattackstate`), `rush`
(RESEND_PUNCH_WHEN_IN_RANGE), `counter`, `finisher`, `throw`, `bull_rush`,
`dodge`, `block`, `hit_reaction`, `stunned`, `special` (by animation type), or
`other` (only flags). `flags` lists the truth properties the combat script
reads that are set: `disallow_attack`, `immune_to_attacks`, `keep_combo_alive`,
`stun_lock`, `sweep`, `ignore_weapon_sound`, `get_away_from_me`,
`immune_to_combo_speedup`, `ignore_target_lock`, `upper_attack`, `heavy_attack`.
`upper_attack` and `heavy_attack` are computed as 0x5f0e63 does (damage pose in the upper set;
an ACTION HEAVY_PUNCH criterion on the state or a group); the stored properties are false in
all shipped data. The state kind, the combo speed-up and `reaction_table_sees` use the computed
`animation_type` (measured: it differs from the stored value on 150 of 1,290 Part 2 states and
196 of 1,279 PC Part 1 states; `upper_attack` on 227 / 260 states, `heavy_attack` on 109 / 106).

### Attack states

| Field | Meaning | Evidence |
|---|---|---|
| `attack_class`, `attack_class_source` | `light` / `heavy`: the control action its groups ask for (PUNCH = fast attack, HEAVY_PUNCH = heavy attack). `null` with the reason when neither is asked (stomp / taser, the rush-to-counter state). | data |
| `animation_type` | computed as the game does when the state is initialised (`initialize_external` 0x5f0e63 → `DetermineAnimationType` 0x5f277a): the first ACTION criterion with a mapped action, or ENUM CHARACTER_MODE = STUNNED, among the state's criteria and then its groups'. The stored property is overwritten (kept in `animation_type_stored` of the state record). | read from code; that the handler runs for every state is inferred |
| `weapon_classes` | values of WEAPON_ANIMATION_TYPE its criteria allow (all three when none is tested) | data |
| `entry` | `initial` (INITIAL_ATTACK), `dash` (AFTER_DASH_ATTACK), `initial_or_dash`, `general` | data; INITIAL_ATTACK is fired with the first attack of a string (ExecuteAttack 0x68b351) |
| `combo_override` | `required`: the single OVERRIDE_ATTACK_COMBO value the state needs (KNOCKDOWN / STUN / AREA_DAMAGE / SUPER_DAMAGE), else null; `allowed`: every value its criteria leave possible | data |
| `target_mode`, `combo_item` | TARGET_MODE values required / excluded; `combo_item: "KICK"` when the target must be prone | data + code (AddAttackToCombo 0x68bca8) |
| `attack_move_dist_m` | `[min, max]` of ATTACK_MOVE_DIST over the unconditional criteria of the chain | data |
| `timing` | `start_playpos`, `duration_s`, `speed`, and for `clear_deadzone`, `pre_impact`, `impact`, `branch`, `can_go_to_movement`: `{playpos, clip_time_s, from_entry_s}` | copied from the state's own event records (`events[*].playpos / time_s / play_time_s`), i.e. the same start-position and slot-speed rules |
| `combo_speedup` | where a combo continuation enters the state: `entry_playpos` = CLEAR_DEADZONE play position − lead / clip duration (lead 0.15 s LIGHTATTACK, 0.2 s HEAVYATTACK), and the impact / branch times from that entry; `applies: false` with the reason otherwise | derived from command_start_animation_state 0x688961 |
| `reach` | `impact_distance_m`, `modification_m`, `total_m` (what the script copies to `m_nimpactdist`) | data |
| `damage_pose` | pose sent (`id`, `name`), its `class` (light / heavy / knockdown / stun), `upper`, and the pose a hit from behind becomes; the full conversion tables are in `combat.rules.damage_pose` | data + code |
| `sweep` | the ten stored sweep parameters when the state is flagged `sweep` | data |
| `damage` | one row per owning CharacterDef × combo database × weapon class: `base` (with the database property it comes from) and `variants: [{modifier, damage, ai_defs}]`. `damage = base × modifier`; the full formula and every input's source are in `combat.rules.damage`. `null` / `[]` comes with `damage_reason`. | data, formula read from code |
| `defender.counter` | the latest moment the counter button still passes: `latest_playpos` = IMPACT − 0.13 s / clip duration, and `latest_from_entry_s` | derived from TestForCounterAttack 0x68d36a |
| `defender.whiff_distance_m`, `whiff_basis` | 1.8 m (`ai`), 2.2 m (`ai_big`), `null` for a hero class (`player`) | PRE_IMPACT event case |
| `defender.reaction_table_sees` | the animation type the defender's reaction table records for this attack; `null` = NOTSET, the table is not evaluated | Enemy.command_react_to_attack 0x721958 |
| `defender.hit_reaction_starts_from_entry_s` | PRE_IMPACT: the victim's hit / block animation starts here, health is removed at IMPACT | code |
| `defender.cannot_be_broken_off` | special handling IMMUNE_TO_BREAK_ATTACK | data |

### Other kinds

`hit_reaction` / `stunned`: `damage_poses` (the DAMAGE_POSE values the state's
own criteria accept) and the `clear_deadzone` / `allow_attacks` times.
`counter` / `finisher` / `throw` / `bull_rush`: the times of `impact`,
`kill_partner`, `bullmove_impact`, `allow_attacks` where present.

## The per-pair `trigger` block

| Field | Meaning |
|---|---|
| `rule`, `rule_basis` | `counter`, `enemy_counter`, `finisher`, `throw`, `bull_rush` – read from the control action the master's criteria chain asks for (else from the damage event it carries). The condition text of each rule is in `combat.rules.pair_triggers.rules`. |
| `action` | the control action (`COUNTER_ATTACK` 12, `FINISHING_MOVE` 3, `THROW` 4, `BULLMOVE` 6) |
| `opponent_models`, `master_weapon_classes`, `opponent_weapon_classes`, `specific_model` | what the master's criteria require of the opponent's model, its own weapon class, the opponent's weapon (disarm states) and SPECIFIC_MODEL (Twilight Lady) |
| `distance_m` | `[min, max]` of ATTACK_MOVE_DIST |
| `damage` | `source` (`counter_base`, `kill`, `bull_rush`, `ragdoll_contact` for throws), the `event` that applies it and its time (`at`), and the amount: counters `counter_damage × 0.75 (playable partner) × modifier` per owner (`amounts`; the game adds a completed string's bonus before the modifier and multiplies by the global and uber factors), finishers 100000 at KILL_ANIMATION_PARTNER, bull rush `m_nbullrushdamage` (× 0.4 on a playable victim) with its stun. A throw has no damaging event (`event` and `amount` are null): see "Throws" below |
| `breakout` | the partner's FORCE_ALLOW_BREAKOUT … FORCE_ALLOW_BREAKOUT_NO_MORE window (`from_s`, `to_s`, play positions) |
| `finisher_prompt` | for finishers: per CharacterDef of the partner class its `critical_health`, `max_health`, `prompt_time_s`. The rule (first player hit below the threshold, 3 buttons on PC / 4 on consoles, re-roll, wrong-button grace) is `combat.rules.finisher_prompt`. |

## Combo databases

`combat.combo_databases.<name>`: `base_damage.{light,heavy}.{UNARMED,BASH_1H,BASH_2H}`,
`counter_damage`, `throw_damage` with `throw_damage_used: false`, and
`strings[*]`: `items` (each with `item`, `button`, `weapon_class`,
`target_status`), `bonus_damage`, `stun_s`, `pushback_velocity`,
`pushback_time_s`, `override`, `terminate`, `uninterruptable`, `ability_id`,
`enabled`.

`throw_damage` (`m_ndefaultdamagethrow`) is stored but dead: no code reads it,
by hash, by name, by slot or by offset (read from code). It is kept because it
is data; nothing in the game uses the number.

Two derived fields per item:

- `override_in_effect` – the override the engine has set when that item is
  pressed: that of the longest enabled string equal to the tail of the presses
  so far (get_longest_valid_combo 0x66cd98). Other strings count only when a
  target in DEFAULT status satisfies them. Example: Nite Owl's `[F] [H]` is an
  AREA_DAMAGE string, so the H of `[F] [H] [F]` is played from the area group.
- `draws_from.<Class>` – the attack groups of that class the step can play, in
  tree order (same button, weapon class allowed, override allowed, target not
  prone, no INITIAL group after the first press). The first listed group whose
  remaining criteria (distance, angle, height) hold is the one played; inside a
  `random_pick` group the member is random. `combat.classes.<Class>.attack_groups`
  lists what each group's states have in common and their names.

A string has no animation of its own: it changes which group the last hit is
drawn from and adds bonus damage, stun and push-back at that hit.

## Damage, from the hit to the health bar

All of this is `combat.rules`; every entry names its handler.

### A hit (`rules.damage`)

`CharacterRootLogic.SetCloseCombatDamageToTarget` 0x6ae57f builds the damage:

```
damage = (base × modifier × global × uber) × [0.2 if the target's electric armour fired
                                               and the attacker is not the Underboss]
       + [string completed]  bonus_damage × modifier × global × uber
       + [attacker charged]  m_ndamageperchargeattack × global × uber      (no modifier)
```

- `base` is set when the attack is initialised (`InitializeNextAttack`
  0x68bf6f), from the button and the weapon class held at that moment, not by
  the animation state played.
- `modifier` is the attacker's `damage_modifier_effective`: every AI
  definition's getter returns its own value when that is not 0 and the
  CharacterDef's `_ndamagemodifier` otherwise. A stored 0 therefore means "use
  the CharacterDef's", never "no damage" (9 of the 31 Part 2 PC definitions
  store 0).
- `global` is `PublicLib.g_nglobaldamagefactor`: default "1.000000", no script
  writer, not present in the extracted fragments. No difficulty input exists
  in script code, and no data: the key bytes occur in no fragment or scene of
  the six sets (de-chunked search; control key found 488 / 519 times). Same on
  X360 Part 2 (constants read from the image: default `"1.000000"`, one
  registration `0x82bf1d84`).
- A blocked hit deals no damage unless the attacker has electrified charges;
  it still costs weapon durability, and so does every further sweep victim
  that is not blocking.
- `rules.damage.override`: `SetCloseCombatDamageToTarget` has three callers.
  Two pass −1.0. The IMPACT_EFFECTS event with `m_ttruth1` passes `m_nvalue`
  (27 events in Part 2 PC: Enemy04 ×22, Rorschach ×5).
  `rules.damage.override_events` lists them for the extract: `{class, state,
  time_s, override_damage}`.
- The unique attack id (damage struct +0x38) is passed by `give_damage` to
  `DecreaseHealth` and from there only into game events 0xcb and 0xc9; no
  handler compares it. `i_will_hit_you` is sent by
  `CharacterRootLogic.command_start_animation_state` 0x688961 when a state with
  `m_tisattackstate` or special handling 4 starts and an attack target exists;
  the receiver keeps the entry 1.5 s (`rules.attack_id`).

`rules.damage.receive` lists, in code order, what the victim does with the
number (`CharacterRoot.command_give_damage` 0x691b10, then `DecreaseHealth`
0x695632): the pose is dropped in the reverse-direction window; × 0.2 for an
Underboss victim hit by a character without a player controller; a victim
inside a paired move loses health only to its partner or itself; ×
`m_nincomingdamagefactor`; × `max(1/uber, 0.7)` when an uber-rage attacker
hits a playable victim (so 2.25 nets 1.575 there); no loss when invulnerable;
then the floors (Underboss, AI partner 1.0, `m_nminhealth`).

**Electric armour.** `ElectricArmor.command_electric_armor_hit` 0x71ea63 is
true only in the armour's `StateActive` with charge power above 0; each time
it takes 1 / `m_nelectrifycharges` off the charge. Same on X360 Part 2
(constants read from the image, `0x82d89e78`). The animation event
ELECTRIFY_ARMOR enters that state (and sets the charge to
`m_nmaxelectrifypower` when the ability is unlocked); DISCHARGE_ARMOR sets
the charge to 0.

**Death.** Health 0 and game event 201 is the path of every character.
`rules.damage.death` adds the two outcomes that exist only in a hero-versus-hero
fight (one playable has `agentFaction` 1): the forced finishing move in scene
40 with the victim left at 0.5 health, and the game-mode rule that leaves the
victim at 1.0 with game event 104 / 105. The game modes are the exe enum family
`GAME_MODES`: 1 RORSCHACH, 2 NITEOWL, 3 COOP (that `ProjectLib.GetGameMode`
returns these values is inferred). X360 Part 2 has the same constants (0.5,
−1.0, 40, 104, 105, 201) in `0x82e5fc40`; branch order not compared.

### Throws and ragdoll contact damage (`rules.ragdoll_damage`)

A throw deals no scripted damage: its states carry no IMPACT or
KILL_ANIMATION_PARTNER event and the combo database's `throw_damage` is never
read. The thrown body is released as a ragdoll at 9.0 m/s (5.0 m/s when big)
and loses health like every other ragdoll in the world, per contact
(`CharacterVisual.ModelCollisionContactAdded` 0x69d00a):

```
damage = mass(body) × min(|(0.2 Fx, Fy, 0.2 Fz)|, 4000) × 0.00007
```

- Gates: contact force above `m_nragdollimpactforcethresholdforsound` (300),
  mean ragdoll speed above 2.0 m/s, the other body is not the ragdoll's own
  and does not belong to a placeholder character.
- A body more than 3.0 m below the visual of its animation partner (the
  thrower) takes 100000 instead.
- The sum is delivered once per frame when it exceeds 1.0
  (`command_give_ragdoll_damage_increment` 0x6914f2), × 0.3 for a
  player-controlled victim, and then goes through `DecreaseHealth` like a hit.
- Cap per contact: `mass × 0.28` (`per_contact_cap_factor`;
  `combat_meta.contact_damage_cap(mass)`). The run-time mass is the ragdoll
  file's mass, so with the `mass` of a `*.ragdoll.json` body: the Dominatrix
  (17 bodies, 85 kg) caps at 2.789 per thigh contact, 2.55 pelvis, 1.70 head,
  0.186 hand; the untuned Twilight Lady rig (17 × 100 kg) at 28.0.
- `_naddeddamage` is written with the same amount and decays by 20 per second
  but is never read. Same on X360 Part 2 (constants read from the image: one
  registration, 20.0 in `0x82e702e0`).

Standing characters hit by a ragdoll (`bystanders`) lose no health directly:
the hit they receive is multiplied by a constant 0.0 and carries a 3.0 s stun
and one of four poses. Above `m_nragdollimpactragdolltrigger` (6000) the
bystander is ragdolled itself and then takes contact damage under the same
rule. `visual_def` holds the five `CharacterVisualDef` numbers the handler
reads; `unread_in_script` names the two it stores without a reader.

What is not established is how much health a throw removes in practice:
contact forces and contact counts are run-time physics.

### Area attacks (`rules.pair_damage`)

- `FLASH_GRENADE`: radius 3.0 m; `(11.0 − distance) × modifier × global × uber`
  for a playable target and 0 for any other; stun 3.0 s; characters of the
  attacker's faction are skipped. Enemies are stunned, not hurt.
- `DISCHARGE_ARMOR`: needs charge power above 0, a partner and
  `is_attack_successful`; `(attacker health + 10.0, or 0.4 × the victim's
  maximum health when the victim is playable) × modifier × global × uber`.
- `ELECTRIFY_ARMOR`: the event only charges the armour and pays
  `m_narmorcost`; the area damage is dealt by `ElectricArmor.AreaDamage`
  0x72769f with `t = max(0, (10.0 − d) / 10.0)`, d between the two
  `m_echaractervisual` positions, 10.0 a code constant (f32 0x9eb1d8;
  `m_nelectrifyrange` is not read here; its only reader, 0x6a71b6 in
  `CharacterRootLogic.command_animation_event_received` (event ELECTRIFY_ARMOR),
  stores it in a local that is not read afterwards, so the property — 4.0 in all
  six sets — has no effect; `rules.pair_damage
  .ELECTRIFY_ARMOR_range_m`): damage = uber × global × modifier × (t ×
  `m_nelectrifydamclose` + (1 − t) × `m_nelectrifydamfar`), stun likewise from
  the stun pair, with a pose by distance and side: d >
  `m_nelectryfypushbackrange` → LIGHT (front 5 / 2, behind 24 / 23); d >
  `m_nelectryfyfallrange` → HEAVY (front 8 / 11, behind 26 / 25); else KNOCKDOWN
  (front 17 / 14, behind 28 / 27); the first id is drawn when rand < 0.5; behind
  = the attacker's position has z < 0 in the victim root's frame; victims: other
  faction only, a playable victim not while its state is DODGE, a non-playable
  one only within ± 2.2 m of height; push 13.0 × t along the direction for
  0.3 s.

### Sweeps (`rules.sweep`)

A state flagged `sweep` checks once per 0.05 of play position (not at
`m_nchecksprsec`, which is never read), through the three stored slices
(begin, impact, end). A potential target other than the main one is hit when
it is nearer than 0.8 m to the segment the check point travelled, at most once
per sweep, and then takes the normal hit above unless it is blocking.

The check point (`rules.sweep.check_point`, read from code, PC): P = visual
world position + (visual position − last recorded model position, refreshed
after the check when it moved > 0.01 m) + conj(Q)·(sin r, 0, cos r)·Q × dist; Q
= the visual's world orientation; r = angle[i−1] + pct × right slice
(clockwise) or angle[i−1] − pct × (2π − right slice) (counter-clockwise); right
slice(a, b) = a − b, plus 2π if negative, taken as (angle[i], angle[i−1]); dist
= (1 − pct) × len[i−1] + pct × len[i]; pct = (counter − playpos[i−1]) /
(playpos[i] − playpos[i−1]). Direction (`rules.sweep.direction`):
counter-clockwise when rightSlice(impact, begin) > rightSlice(end, begin)
(`DetermindTravDir` 0x69b2be); the property `m_tcounterclockwise` is not read.

### Bull rush (`rules.bull_rush`)

Read from code (PC); animation and state data measured on PC Part 2.

- Start: animation event 15 CHARGE sends `CharacterPhysics.command_state_charge`;
  the state ends in free fall as soon as the current state's special handling is
  not BULL_MOVE.
- Contact: animation value 9 DISTANCE_TO_END_POS = 3D distance root to lock
  target, 0 without a target, 10.0 while the target blocks or is electrified
  (`SendBullRushDataToAnimationCtrl` 0x696d2d); Rorschach starts the impact pair
  on [0.05, 1.0); EnemyBig 'Freight Train' leaves to CombatGroup below 2.0 or at
  animation end.
- Secondary victims: every target-list entry that is not a placeholder, the lock
  target or the animation partner; within capsule radius + 1.0 (3D); in front
  (dot(face heading, horizontal direction) > 0); victim state
  `m_tstunlockstate` == 0 (set on the hit-reaction, Ragdoll-Hit, AttackBlocked
  and ThrownInAir states: 100 states on PC Part 2). Damage
  `special_def.m_nbullrushsecondarydamage`, no global / uber / modifier factor;
  stun `special_def.m_nbullrushsecondarystun`; pose 11 or 8 (rand < 0.5 first)
  when |local x| ≥ 0.2 or the victim is big, else 17 or 14, then
  DirectionManipulateDamage; push, when animation speed > 2.0: 0.3 s at 4.0 m/s
  along normalise(sign(local x), local y, local z) in the attacker's frame
  (diagonal to sideways, on the victim's side); in low violence a prone victim
  is skipped.
- Blocked by a player: a blocking or electrified playable lock target nearer
  than 1.1 m gets `hit_soon`(pose 2) and `give_block_damage`; the attacker is
  forced to animation 9 and fires actions 14 and 30.

States with special handling BULL_MOVE carry `combat.special_handling_rule:
"BULL_MOVE"`; what the value does is `rules.special_handling.BULL_MOVE`: after
event 15 CHARGE it keeps CharacterPhysics in charge mode (leaving it → free
fall); for a player the `StateActive` local `nrotatefactor` (name from
declaration order) is 1.5 for the first 0.25 s of the state, then 0; on state
end the heading override is cleared, a non-player loses its lock target and a
player gets `release_dodge_lock`; like any non-NORMAL value it stops the
character being pushed. It is also set on counter-attack and finishing-move
states.

### Who may attack when (`rules.attack_permission`)

`orchestrator_grant`: per hero and frame the combat orchestrator grants one
waiting attacker when the hero has fewer than the allowed current attacks and
the last attack and the last grant are older than the attack frequency; no
grant while the hero's animation is immune, and current attacks are then
broken off. The limits are level data (the orchestrator presets a level's
triggers select) and are not part of this block: `watchmen levelmeta` exports
them as `combat_presets` (LEVEL_META.md). `enemy_evaluate`: the
priority order of `Enemy.Evaluate` 0x72587d. A PASSIVE enemy neither chases
nor attacks: it idles (or returns to its zone) until it is attacked, damaged
or switched by a SET_AI_STATE trigger. `faction_filter`: target lists come from
`AIBrainNode.GetVisibleAIEnemies` 0x484235 (sweeps: Perception's known-enemy
list, fed by `GetSeenAIEnemies` 0x48460d): another active agent whose faction
is not NEUTRALFACTION (2) and differs from the caller's, and that passes the
sight test; a character set as `Perception.m_forceperceptedcharacter` is added
without a faction test; that member is written only by `Enemy.StateActive`
0x724071 (store at 0x725078): on acquiring a target, each other living member of
the enemy's group whose known-enemy list is empty receives the enemy's own
target if the enemy can see it; `Perception.AddNewKnownEnemies` 0x7dcc88 uses it
once and clears it.

### Twilight Lady (`rules.twilight_lady_reaction`)

She does not use the reaction table below: her routine counts the attacks of
each attacker and answers with a dodge (probability 0.22 early on), a forced
fast attack, a stun attack or a counter, using engine random numbers. The
four constants, the rule that attacks from behind are not exempt and the
clamp of `dodges_before_counter` were read twice; the branch order once.

### Underboss (Part 1) (`rules.underboss`)

Present only when the data has an `UnderbossDef` (Part 1). Read from code (PC
executable); the hit / block counts, the shockwave numbers and the target
re-check time (6.0, `UnderbossLib.ntargetlocktime`) are registered defaults —
the shipped fragment stores neither count property, so whether 3 / 2 are live
rests on the property-default rule (see "Not exported"); no writer of the
re-check time was found (`attack.target_recheck_is`).

- **Success test.** `is_attack_successful` returns 1 through the shared body
  0x7f09ac in 33 of its 37 registrations; `BehaviorHandler` 0x618da2,
  `Underboss` 0x891084 and `UnderbossCombat` 0x8832a4 forward it to their
  current behaviour (1 when none); the only body returning 0 is
  `UnderbossPhase1` in state `StateFleeToJumpPoint` (0x87b96e). There
  PRE_IMPACT sends `block_timed(1.0)` and `m_idamagestate` is 1. That state is
  entered above `StateActive`, so its no-op `react_to_attack` shadows the one
  below.
- **Defence** (`react`, `UnderbossPhase1.command_react_to_attack` 0x88aa08). An
  attack is counted when the attacker is not behind and (the attacker is AI or
  the attack is not a player's unblockable one). First attack: count 0, series
  kept until now + 3.0, retaliate after now + 1.5. While the count is below
  blocks − 1 + hits it rises by one and the series is kept 1.0 s; he blocks
  (`block_timed(1.0)`) from count ≥ hits − 1. With the registered defaults 3 /
  2: hits 1–3 land, 4–5 are blocked, 6 and later are countered. The counter is
  skipped in an IMMUNE_TO_BREAK_ATTACK state. Phases 1–2: `attack_slow`, fire
  ONE_FRAME_ACTION, NORMAL_ATTACK, HEAVY_PUNCH, unfire PUNCH,
  OVERRIDE_ATTACK_COMBO NORMAL. Phases 3–4: `attack_fast`, ATTACK_POSE
  POSE_AFTER_DASH unless the attacker's animation type is COUNTERATTACK or
  FINISHINGMOVE, fire NORMAL_ATTACK, PUNCH, ONE_FRAME_ACTION,
  OVERRIDE_ATTACK_COMBO KNOCKDOWN. ATTACK_MOVE_DIST 1.5. An attack that is not
  counted sets retaliate-after to now + 3.0. The handler is live in
  `StateActive`, `JustAttacked` and `StateStopAttacker`; for the phase 4 states
  it was not traced.
- **Interrupts** (range 4.0 m): a FINISHINGMOVE whose `m_eattacktarget` or
  animation partner is the Underboss; a BULLMOVE / THROW / FAILED_THROW by an
  enemy that faces the Underboss (the Underboss is in the enemy's local +z).
  He answers with `attack_fast`, OVERRIDE_ATTACK_COMBO KNOCKDOWN.
- **Punish**: on a completed combo of the attacker, unless a DELAY_OPPONENT
  arrived within 2.0 s; `JustAttacked` stuns at least 0.8 s (0.7 on a re-hit);
  a forced punish ignores the prone gate.
- **Attack**: range 4.5 m, in front, not immune; AI targets only within 2.1 s
  of being attacked; a prone target is attacked again after 4.0 s. The target
  is re-checked at most every 6.0 s: when another known enemy is within
  `UnderbossDef.m_nenemyengagementdist` (shipped 5.0) he switches to the first
  other known enemy, not the nearest.
- **Phases** (`defs[*].phases`): phase 1 from 1.0 to
  `m_nhealthfractiongotonextphase`, phase 2 to
  `m_nhealthfraction1gotonextphase`, phase 3 to
  `m_nhealthfraction2gotonextphase` (f2). Phase 4 always has four stages k =
  1..4, from f2 − (k−1)·step to max(0, f2 − k·step), step = (1 − f2) /
  `m_istepsinphase4`; the stage count is hard-coded, not that property. Health
  cannot go below the current threshold (`command_set_lower_bound`, 0x8932d1;
  sent by `UnderbossPhase1.StateActive` on every entry); death at health ≤ 1.
  Max health is `CharacterDef.m_nmaxhealth` of the character type
  (`UnderbossDef.m_nmaxhealth` is not read, because only `CharacterDef`
  registers into `g_echaracterdeflist`, 0x666db8). Shipped: 1.0 → 0.8 → 0.7 →
  0.5 → 0.375 → 0.25 → 0.125 → 0, max health 1000.
- **Shockwave**: event TRIGGER_END_INTERPOLATING (67) in `JumpOnCharacter`;
  damage 10.0, radius 2.5 (horizontal), pose KNOCKDOWN_UPPER_STRAIGHT inside
  and HEAVY_UPPER_STRAIGHT outside; playables are skipped at stage 4;
  `_ndamspreadspeed` is not used.
- **Flamer**: damage per contact `UnderbossDef.m_iflamerdamage`, pose base
  HEAVY_UPPER_STRAIGHT, 5 − stage bursts before he re-equips.
- **Damage modifier**: `UnderbossDef` +0x148 is `_ndamagemodifier` (+0x144
  `_tmodifydamagemodifier`); 0x8841f3 returns it when non-zero, else
  `CharacterDef.command_get_default_damage_modifier` 0x666cf1. Shipped: own 0.0.
- **Unreachable**: `UnderbossPhase1.command_hit_by` 0x888c4b (`UnderbossCombat`
  does not forward `hit_by`), so its voice lines never play in this build.
- **Game events** (`game_events`, exe enum family GAME_EVENTS):
  UNDERBOSS_GOTO_PHASE1..4 700–703, UNDERBOSS_DEFEATED 704, UNDERBOSS_JUMPS 705,
  UNDERBOSS_JUMPS_FINAL_TIME 706, UNDERBOSS_JUMPS_2ND_TIME 707,
  UNDERBOSS_JUMPS_3RD_TIME 708, UNDERBOSS_ESCAPE_PHASE1..3 709–711,
  UNDERBOSS_PLATFORM_HIT..HIT4 712–715.
- **Series reset**: when his state is not BLOCK and now − keep > 0.0, the attacker
  list and the block count are cleared (0x8933cb–0x89341a).
- **Retaliation** (0x893ee3): in phase 4 or against an AI target, OVERRIDE_ATTACK_COMBO
  KNOCKDOWN and `StateStopAttacker`; against a player in phases 1–3, `attack_slow`
  with override NORMAL. `JustAttacked` also ends as soon as his animation type is no
  longer 11 (read from lifted text). He keeps a target that is in an attack state
  and targets him (`m_eattacktarget`, else `m_etargetlockentity`, 0x87a6e5).
- **Phase ends**: a phase 4 stage ends on the 0.99 test at 0x893439–0x8934fe.
  `StateFleeToJumpPoint` sends game events 709–711, forces state 73 and waits up to
  6.0 s in phases 1–2 (4.0 m height test 0x88a0d6, 1.0 m distance test 0x88a7c4).
  Phase 3 (read from code, `UnderbossPhase1__StateActive` 0x8927b0): `m_iphase` is
  compared with 3 at 0x8928bd and the phase 3 block 0x8929d5 ends with `jmp 0x892dd4`
  (0x892adf); phases 1 and 2 leave through 0x8929c8 to 0x8932ac, so 0x892dd4–0x8932ab runs
  in phase 3 only (its resume labels 4–12 of the table at 0x895694 are set inside it:
  0x892fed, 0x893261, 0x89331b). There he waits, frame by frame, until a playable
  character's height is within 2.0 of his (absolute difference against the float at
  0x9e663c, `fld` at 0x892fa8, flag cleared at 0x892fb8), sends
  `command_play_specific_anim` with `_epipe` and state 54 (0x892dee, `mov dword [ebp-0x10],
  0x36` at 0x892df6), waits for the weapon flag (0x892e40), turns to `_elookatpos` and
  counts a timer down from 1.5 (float at 0x9e5ff0, `fld` at 0x893229) by the script time
  step 0xe14304 (`fsub` at 0x893297) until it is no longer above 0 (0x8932a0–0x8932aa).
- **Flamer push**: × 4.0 for 0.3 s (0x7370b1, 0x7370e0).
- **Platform**: character type 25 is excluded and each character counts once; hits
  send game events 712–715 (0x88eaa7–0x88ead2), states 50 / 58, jumps 705 / 707 /
  708 / 706.
- **Shockwave details**: push 0.3 when the distance is above 0.1; each overlap entry
  owned by a `CharacterPhysics` is damaged once and erased; event 66 stores the end
  point and 68 returns to `StateActive` (0x890057–0x89006b).
- **Movement** (`rules.underboss.movement`; `UnderbossMovement.command_defaut_movement`
  0x887a07, read from lifted code, constants from exe bytes), d = distance to
  the target:
  - d > max melee distance: run after the target, full speed when d ≥ 5.0
    (0x9e97fc), else walk speed; pathfinder goal = target + (0, 1, 0).
  - d ≤ max melee and d > `m_nattackdistance`: walk speed × 0.5.
  - d ≤ `m_nattackdistance` and d > `m_nminimumdistance`: stop (idle speed).
  - d ≤ `m_nminimumdistance`: step back facing the target at walk speed × 0.5. If
    the facing error is outside ±1.5 rad he turns first. After 0.5 s of stepping
    back with move speed below 0.6 (0x9ea12c) he stops.
  - Speed above 0.5 clears the target lock.
  - If the facing error is outside ±0.3 rad or the speed is below 0.2, and he is
    not attacking, the speed is 0 and he turns (the error × 0.2 while moving
    faster than 0.3).
- **Flee** (`rules.underboss.flee`; `UnderbossFlee`, read from lifted code):
  - Points come from scene nodes: every sibling named `fleepointlinear`, and
    `fleepointcircular1…` until a number is missing (init 0x886106).
  - Trigger (`StateActive` 0x884a6f): the closest player is nearer than the
    current flee distance and the vertical gap is under
    `m_nminverticaldistwhenfleeing`. The flee distance is redrawn uniformly
    between `m_nmindistwhenfleeing` and `m_nmaxdistwhenfleeing` (0x87a5d0).
  - Linear flee takes the next list point; when the list ends, circular flee is
    used from then on (0x8867e2).
  - Circular flee (0x886913): candidates are points that are not the nearest
    point of either hero on his level (height within 2.0), whose index differs
    by 1 or 3 from his own nearest point (0x87a6c3), and whose direction from him
    has a dot of at most 0.9 with the direction to each hero (0x886eed,
    0xa299a0). One candidate is picked at random.
  - With no candidate, or after more than `m_inumberofpointsincircular` picks, he
    is "surrounded" and leaves the state when a hero comes within the surrounded
    distance.
  - Arrival: within 2.0 horizontally and vertically (0x88643d).
- **Flamethrower volumes** (`rules.underboss.flamer_volumes`; `FlameThrower`, read
  from lifted code; registered defaults length 12.0, speed 10.0, 5 capsules at
  0x74449e, 0x7444b3, 0x7444c8; `Init` 0x7385f9, state `active` 0x7414e7):
  - Five capsule nodes of width 2.0 start with ages (length / speed)·i/(N−1) = 0,
    0.3 … 1.2 s.
  - Each tick age += dt and position = flamethrower position + direction × speed
    × age, with y taken from `ResidualLimiterNode`.
  - When age exceeds 1.2 s the capsule restarts at age 0 with the current aim
    direction while firing; otherwise it gets a zero direction.
  - That the local `vpos` is the aim vector is inferred.
- Not read: shipped values of the `UnderbossDef` flee properties, `FaceTarget`,
  the residual fire areas.

### Achievements (`combat.achievements`)

Conditions read from code; names are the exe enum family `ACHIEVEMENTS`
(registered in 0x80c150), not UI captions (the caption "Rrararghgh" differs
from the enum name `RRARARARGHGH`). One record per controller class the data
has: `AchievementPart2Ctrl` (ids 0–11) or `AchievementCtrl` (Part 1, ids
12–23), each with `thresholds` (the fragment's stored value, else the
registered default; `threshold_source` says which) and `conditions` keyed by
id. Shipped Part 2 thresholds equal the registered defaults; Part 1 (identical
on the three platforms): TURBO 4800.0 s, VIGILANTE 20 kills in 101.0 s, SHIELD
25, STRONGARM 100, RETALIATOR 200, EXTERMINATOR 250.

- TAGEM (3): kills by the signed-in player of an enemy the other hero threw
  less than `_itagem_timelimit` (+5.0 s low violence) before.
- `defects`: Part 1 RETALIATOR (22) and EXTERMINATOR (23) increment saved
  counters +0x10 / +0x14 but compare the dodge-or-block counter +0x18 with
  their threshold (0x59925d, 0x599222); ELECTRICEXPLOSION (5) tests the raw
  overlap entry against the playable list, so playable capsules are counted
  (inferred).
- `turbo_clock`: playing time is set to 9999.0 on game event 5 and when a level
  is entered out of order; to 0 when level 1 is entered.

## EnemyDef members that are not tuning values

Read from code and a displacement scan of the whole code section; `combat_meta` exports
none of these from the `EnemyDef`:

- `m_nhealthregen`, `m_nhealthregenlow`: display copies of the `CharacterDef` values
  (`GetHealthProperties` 0x5972c2 overwrites them); the live value is the `CharacterDef`'s
  (`health_regen_per_s`).
- `m_nprobofcounteratt`, `m_nprobofdodge`, `m_nprobofblock`, `_nprobofcounteratt`,
  `_nprobofdodge`, `_nprobofblock`, `_nepsilon`, `_nprevprobfastatt`, `_nprevprobslowatt`,
  `_tmodifydamagemodifier`, `_tcopydrssetup`: editor handlers only (`Justify*`,
  `FilterExposedProperties`).
- `m_nsidesteptime`: no reader found.
- `m_iagentbasetype`: written by `command_set_type` 0x598105 from
  `AILib.DeriveBaseAgentBaseType` 0x597696; read only by
  `BehaviorHandler.command_set_ai_parameter_sheet` 0x6180e6, which ignores a
  definition of another base type.

## Movement contact rules (read from code, not exported)

Documentation only; nothing here is in `combat.rules`.

- **Pushed** (`CollisionContactAdded` 0x67c845, `command_being_pushed_by` 0x6908e0): contact
  value > 200, own animation speed < 1.0, move speed < 0.2, not attacking / prone / in attack
  state / absolute mode / main menu; 0.4 s, target 2.0 m along the push; animation weight
  min(1, 5·t).
- **Object push** (`FeedBack` 0x681e7b): dynamic object slower than 2.5 and too tall to step
  on; impulse 250 × √|requested velocity| × physics dt along the blend of facing and direction,
  vertical part removed. Never runs: its only caller is the command `CollisionResponse` 0x67c7e4 (slot call at
  0x67c81e), and nothing sends that command — its hash 0x4cb780c2 occurs only at the
  registration, none of the 23 `SubscribeToCollisionInfo` /
  `SubscribeToCollisionInfoFirstContact` call sites names it, and the native handle stored in
  0xe15290 (0x50f255) is never read (read from code, PC). The four console executables each
  hold the hash once and no subscription string for it (measured).
- **Heavy object** (`DynamicObjectFeedBack` 0x6825ff, Rorschach and Nite Owl only): dynamic
  `Model` with mass > 5 in a 0.4 × 0.4 capsule cast → move speed × 0.3 in that frame only (flag
  cleared at the start of every `command_attempt_move`, 0x67d5bf); after more than 100
  consecutive moving frames under 0.1 m per frame, impulse 2 × mass away from the character.
- **Wall stop** (`command_detect_wall` 0x67b508, `StateActive`): one ray from capsule centre to
  feet level + 0.25 × width ahead + 0.75 m along the move direction pitched 46° up; sheet mask
  0x200; stop when the angle between the horizontal hit normal and the move direction exceeds
  135°. Applies only to characters with a `PlayerCtrl`. `CharacterRoot.m_eplayerctrl` (+0x88) is
  written only at 0x7f4a50 (`PlayerCtrl.StateActive`, entered only from
  `command_activate_player_ctrl` 0x7f4929). On SCENE_ACTIVATED,
  `PlayerManager.command_game_event` 0x7f9d1b activates the first `PlayerCtrl` on playable 0 in
  game mode 1, the second on playable 1 in mode 2, and both in mode 3. An AI-driven partner hero
  therefore has none and is never wall-stopped; the nested AI branch is unreachable (read from
  code).

## Reaction table (`combat.ai_defs[*].reaction_rows`)

Rows as the engine builds them (a slot counts only when its first attack and
its result are set): `newest_first` attack types, `result` (BLOCK / DODGE /
COUNTERATTACK), `clear_history`. The table is deterministic; the gates and the
matching rule are in `combat.rules.defender.reaction_table`.
`combat_meta.react(rows, history)` applies it (history = animation type ids,
newest first).

## Class links (`combat.classes.<Class>`)

`class_id`, `model_type`, `playable`, `big`, `character_defs`,
`combo_databases`, `state_counts` (by kind), `attack_states`,
`attack_states_without_damage` (with the reason), `attack_groups`.

The link CharacterDef → animation class is read from data:
`CharacterDef.m_emodelfragment` → the FragmentNode of `CharacterVisual.fragment`
→ the `*CharVisual` fragment → its body `AnimationCtrlWM.m_ianimationclassid`
→ the AnimationClass of that id.

## Using it

```python
import json
m = json.load(open("anim_meta.json"))
if m.get("combat_format"):
    for s in m["classes"]["Enemy04"]["states"]:
        c = s.get("combat")
        if c and c["kind"] == "attack":
            t = c["timing"]["impact"]
            dmg = [v["damage"] for r in c["damage"] or [] for v in r["variants"]]
            print(s["name"], c["attack_class"], t and t["from_entry_s"], c["reach"]["total_m"], dmg)
```

`python3 wlib/combat_meta.py anim_meta.json` prints the per-class totals.

Notes for consumers:

- Per-state `damage` is the plain hit (`base × modifier`); add the string's
  `bonus_damage × modifier` on its completing hit and multiply by
  `special_def.m_nrageuberdamagefactor` in uber rage — against a playable
  victim the net uber factor is `uber × max(1/uber, 0.7)`
  (`combat.rules.damage`, `receive`).
- A throw pair has no amount: the health it removes is ragdoll contact damage.
- A hero class lists one damage row per database its owner can use (the
  player's own database and the AI-partner ones).
- Times are for the state's default entry (`timing.start_playpos`); a combo
  continuation enters at `combo_speedup.entry_playpos`.
- `whiff_distance_m` applies to AI attackers only; players have no range test
  at impact.

## In a character GLB, and in a resumed export

`anim_meta.clip_extras` copies a pair's `trigger` into the `pairs[*]` entries of the clip's
`extras.watchmen` (beside `placement`, `timeline` and the camera cuts of FX_META.md). The
per-state `combat` block, `group_criteria` and the top-level tables are not in the GLBs: a clip
is shared by several states, so they stay in `anim_meta.json`.

`watchmen characters` reuses an `anim_meta.json` it finds in the output folder only when it
carries this block's current marker (`combat_format`) and the effects marker (`fx_format`) besides
the table and face formats; an older table, or one with another `combat_format`, is rebuilt. If the combat step itself fails on an extract
(`combat: skipped (...)` in the log) the table has no marker and is rebuilt on every run.

## Not exported

See `combat.not_established`: ragdoll contact force magnitudes and contact
counts (so the health a thrown body really loses), the AI behaviours behind
the attack permission rules (the enemy side; the partner's rules are in
`rules.partner_ai`) and the orchestrator's level presets, Twilight Lady's
punish and back-flip routines, a native or data writer of the global damage
factor outside the files scanned (script code has no difficulty input),
property defaults (a registered default is parsed into the slot at instance
creation, 0x47dfed; nine combat defaults absent from every decoded JSON of the
six sets (1,207 / 1,174 files); a property without a registered default starts
as 0, null, a zero vector or an empty list (type virtual +0xc: 0x4fa365,
0x4fa89c, 0x4fb82b, 0x50030f)).
Underboss: whether the registered defaults 3 / 2 are live (neither property is stored in the
shipped fragment).
