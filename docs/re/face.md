# Face animation: which face pose plays during which body animation, and when

Target: `KapowMultiDEDRM.exe` (image base 0x400000) and the Part 2 PC fragments.
Read 2026-10-03. Machine-readable table: `findings/face_map.json`
(`watchmen-face-map/1`, 2.5 MB). Scratch and generator: `work/face/`
(`gen_face_map.py`, `sim.py`, `facecls.py`, `finalize.py`).

Evidence tags: **[R]** read from code (address given), **[D]** measured on the
game data, **[I]** inferred (reason given), **[N]** not established.

## 0. Answer in short

The face is **not** paired with body animations. There is no table, name
convention, state id, play-position copy or forwarded animation event that
links a body clip to a face clip.

1. Every character with a face has a second `Character` entity (the head
   model) with its own `AnimationCtrlWM`, running a small separate state
   machine (14–16 states). All 24 face clips are one-frame poses; a face
   "animation" is a pose held for some seconds with a 0.21 s cross-fade [D].
2. The body side feeds that controller exactly four inputs [R]:
   - enum `CHARACTER_MODE` (noncombat / combat / stunned / prone / dead), every frame;
   - action `NORMAL_ATTACK`, every frame while the body's current state has
     "Attack state" set;
   - action `HITTAKEN` + enum `DAMAGE_POSE`, when the character is hit;
   - actions `START_SPEAK` / `STOP_SPEAK`, when the character starts / is not
     playing a sound.
   The face classes test exactly these and nothing else (plus play time) [D].
3. So during a body animation the face is: an **attack pose** for the whole of
   an attack state; a **hit pose** for 0.75 s from each hit; a **talk
   flutter** while a voice line plays; a **dead pose** from death on;
   otherwise an **idle cycle** with a random fidget (for the women the fidget
   is the blink). Changes in the middle of a body animation come from hits
   (in paired moves: the attacker's `IMPACT_EFFECTS` / `IMPACT` events on the
   shared clock), from death (`DIE`, `KILL_ANIMATION_PARTNER`), from the
   choke event, and from speech.
4. Rorschach has no face controller at all [D].

Of 1,290 body states: 309 have no face (Rorschach), 617 show only the idle
cycle, 242 hold the attack pose, 67 start with a hit pose, 6 are dead poses,
49 change mid-animation on their own (45 by death at the `DIE` event, 4 by
speech, 1 by the choke event). In primary pairs, 115 of the 203 states that
have a face change mid-animation (section 5).

## 1. Architecture

### 1.1 Entities [D]

`TNT/Production/Fragments/GameEssentials/CharacterVisual/*CharVisual.fragment`
(eight files) each contain:

```
[Character]        HeadModel                      the head, a separate character model
  [AnimationCtrlWM]  AnimationCtrl                m_ianimationclassid = face class
    [AnimationDataWM]
[CharacterVisual]  <body>
  [AnimationCtrlWM]                               m_ianimationclassid = body class
  [CharacterHeadCtrl] HeadCtrl                    look-at parameters; _eheadcharacter empty
  [BoneAttacher]     HeadAttach                   attachedBone = -1 in the file
```

| CharVisual fragment | body class id | face class id |
|---|---|---|
| GoonCharVisual (`EN1_goon`) | 3 `EN1` | 7 `EN1_FACE` |
| PrisonerFastCharVisual | 3 `EN1` (speed 1.2) | 7 `EN1_FACE` |
| PrisonerBigCharVisual (`EN2_prisoner`) | 5 `EN2` | 7 `EN1_FACE` |
| En3CharVisual | 6 `EN3` | 7 `EN1_FACE` |
| En4CharVisual, Bs2CharVisual (`EN4_Dominatrix`) | 10 `EN4` | 11 `EN4_FACE` |
| NiteOwnCharVisual | 1 `NTO` | 8 `NTO_FACE` |
| RorschachCharVisual | 0 `RSH` | — no `HeadModel`, no face controller; `HeadCtrl` only |

Ids are `CHARACTER_ANIMATIONS` (exe enum: 7 `EN1_FACE`, 8 `NTO_FACE`,
9 `UB_FACE`, 11 `EN4_FACE`). The face fragments carry the matching
`m_iclassid`: `AnimationClassEnemy01Face` 7, `AnimationClassNiteOwlFace` 8,
`AnimationClassEnemy04Face` 11. `UB_FACE` (9) has no fragment in Part 2.
So the face class is chosen **per character rig family, by the class id on the
head's own controller**, not per head model and not by the body class.

The head *mesh* is chosen separately: `CharacterHeadCtrl.command_activate`
0x669496 asks the character's model collection for its head model collection
(`command_get_head_model` 0x6ed452d4, 0x6696xx) and takes the model with index
`_imodelindex` (`command_get_model_by_id` 0x8ffd39d; the index is set by
`command_set_character_model_id` 0x662728), then sets it on the head character
(0x6696e5) [R calls, I that the index is the body variant's]. The level
fragments `Fragments/Enemy/{ThugFace,BordelloFace,NightClubFace,TwilightHeadFace}.fragment`
are those collections (`CharacterHeadModel` nodes: `Large_Head_1..`,
`GimpHead1..3`, `FemaleHead_*`, `Heavies_Head_1`, `TwilightLady_Head`) [D].

### 1.2 Wiring [R]

- `CharacterHeadCtrl.Init` 0x664a11 finds, by node name, `"headmodel"`
  (→ data +0x64 `_eheadcharacter`), `"headattach"` (→ +0x08) and the head
  model's child `"AnimationCtrl"` (→ +0x0c `_eanimationctrl`). It then turns
  the head model's and the face controller's own frame update **off**
  (`FUN_00491395(0)`, `FUN_004f9b96(0)`): both are ticked explicitly by the
  body (1.4).
- `CharacterVisual` data +0x0c is `m_eheadctrl`; `CharacterHeadCtrl.command_get_animation_ctrl`
  (0x31908a4d, handler 0x890ac2) returns the face controller. That hash occurs
  at eleven places in the exe; besides its registration and
  `DeleteCharacterRootFragment` they are the nine driver sites of section 2,
  i.e. the list of drivers is complete.
- `AnimationCtrlWM.IsShownOrClose` 0x5ab2ac sets `_tishead` (+0xf8) on a
  controller whose character is not the root's own model, and the visibility
  flags (+0x158 shown, +0x160 / +0x164 in frustum) the head update uses.

### 1.3 Attachment of the face skeleton [R, composition order I]

`command_activate` 0x669496:

- `HeadAttach.attachedBone` := the body's **`Spine2`** bone (0x669713–0x669730).
- head character `worldPos` := the body visual's world position (0x6697f7);
  `worldOrient` := body orientation composed with a rotation of **90° about
  +Y** (quaternion (0, sin, 0, cos) of the double 0.785398 = π/4 at 0xa0f240;
  0x66987f–0x6698b2).
- builds a map head-bone-type → head-model bone id by name:
  `Head` (0), `Neck` (1), `Bip01` (2, "SPINE2" slot), and for character type 1
  (`NITE_OWL`) also `L Clavicle` (3), `R Clavicle` (4), `LUpArmTwist` (5),
  `RUpArmTwist` (6) (`CHARACTER_HEAD_BONE_TYPE`, 0x669a13–0x669c55).

`HeadCharacterUpdate` 0x66a2a5, every frame the head is visible:
`UpdateHeadBone{body bone id, head bone id}` 0x663ea5 reads the body bone's
position and orientation (`FUN_004b05b3` / `FUN_004b05de`) and writes them to
the head model's bone (`FUN_004ba7ad`) for body `HEAD` (0) → head `Head`,
body `NECK` (1) → head `Neck`, and for Nite Owl body `LEFT_CLAVICLE` (0x13),
`RIGHT_CLAVICLE` (0x15), `LEFT_TWIST` (0x14), `RIGHT_TWIST` (0x16) → the four
cowl bones (`CHARACTER_BONE_TYPE`, registered at 0x672a62–0x672b91).

So: the head model sits in the body's frame; its `Head` and `Neck` bones are
**overwritten by the body's Head and Neck bone transforms**, and the face
bones (jaw, lips, lids, brows) below `Head` keep the pose the face controller
gives them. There is no offset other than the 90° model-axis turn. This agrees
with what the toolkit measured earlier (Nite Owl's cowl clavicles riding the
body, `ENGINE_CONSTANTS.md` 1287) and with how the GLBs attach the face rig
(`f_anchor` follows the body `Head` joint). Not established: the space of the
copied bone transforms (model space is assumed) [N].

### 1.4 Update order [R]

`CharacterRoot.StateActive` 0x6b367a → `CharacterVisual.command_update_animation`
0x69b988 `{dt, direction, mode}` (three call sites; `StateDead` 0x6bb12a calls
it with `{0, 0, 2}`):

1. body controller inputs, then the body controller is ticked (`FUN_004f9baa`
   0x69c654) and the body skeleton updated (0x69c68c);
2. face controller `m_tforceupdate` (+0x2c) := the body controller's (0x69c635);
3. face inputs are written (section 2.1);
4. `CharacterHeadCtrl.command_update_head_ctrl` 0x669f45 `{force, shown}` —
   only when the face controller was in frustum: ticks the face controller
   (0x669fc7), runs look-at (1.5), then `HeadCharacterUpdate` (head model pose
   update 0x66a31b, then the bone copy).

When the character is neither updated nor visible, `StateActive` calls
`command_update_animation_fast` 0x69b87d instead, which touches the body
controller only: an off-screen face does not advance.

`StateDead`, late stage (0x6bc008–0x6bc0db): `CharacterHeadCtrl.command_set_anims`
0x663bb3 stores the body Head/Neck transforms once (`_tselfcontained`-style
flag at +0xe4, re-applied by `HeadCtrl.StateActive` 0x669c94), the face
controller is disabled (`enabled` := 0). The face is frozen from then on.

### 1.5 Look-at is a body feature, not a face feature [R]

`command_update_head_ctrl` picks a target (`root+0x70` attack target, else
`root+0x7c` locked target, plus `_neyeheight` 1.6 m; or an explicit
`command_look_at_pos` / `command_look_at_pivotnode` with a timer) when the
body's current state has `m_tallowheadctrl` (state data +0x160; set on 215 of
1,290 states [D]) and `CharacterPhysics.command_is_headctrl_allowed` agrees.
`UpdateHeading` 0x66a5ae / `UpdatePitch` 0x66ab44 run a small steering model
(mass, max force, max speed from the `HeadCtrl` node) and write
`ANIMATION_VALUE` 17 `HEAD_ANGLE_TO_TARGET` (0x66ab17) and 18
`HEAD_VERTICAL_ANGLE_TO_TARGET` on the **body** controller. The head turn
itself is the body class's additive `HeadTurn` overlay, which the toolkit's
interpreter already models. `LOOK_AT_TARGET` (45) stays camera-only.

## 2. The driver

### 2.1 Per frame — `command_update_animation` [R]

| What | Where | Detail |
|---|---|---|
| `SetAnimationEnum(face, 1 CHARACTER_MODE, args[2])` | 0x69c728–0x69c74f | value computed in `StateActive` (frame +0xac): 0, 1 `COMBAT` when in combat, 3 `STUNNED` while the stun timer runs, 4 `PRONE`; `StateDead` passes 2 `DEAD` |
| `FireAnimationAction(face, 1 NORMAL_ATTACK)` | 0x69c764–0x69c7c3 | when `CharacterRoot.command_is_attacking` (0x693249: alive, has an attack target, and current state `m_tisattackstate` or special handling 4) **or** the body's current state has `m_tisattackstate` (state data +0xa0) |
| `FireAnimationAction(face, 32 STOP_SPEAK)` | 0x69c7d7–0x69c843 | every frame `SoundCtrl.command_is_entity_playing_sound(root)` (0x2cf8f3ce, 0x830fe5) is false |

Actions live for one controller update (`FireAnimationAction` 0x5aa83f sets
`m_tforceupdate` and queues; `CopyTmpListToControlActionList` 0x5abe69,
`ClearOneFrameEvents` 0x5aa4c0), so "every frame" is what keeps the attack
pose up.

The same function sets body enum 7 `TARGET_MODE` to the mode of the
character at `root+0x74` (0x69c46c–0x69c5df); that is a body input, mentioned
because the decompile shows it next to the face code.

### 2.2 On events [R]

| Trigger | Site | Face input |
|---|---|---|
| `CharacterRoot.command_hit_soon` (sent by the attacker's `PRE_IMPACT`, by 31, 38) | 0x6906be–0x690773 | `HITTAKEN` (2) + `DAMAGE_POSE` := args[1]; skipped when the victim is in a `BLOCK` state (special handling 8) and blocks |
| `CharacterRoot.command_give_damage` (attacker's `IMPACT`, 20, 33, 85 …) | 0x6929e9 | `HITTAKEN` + `DAMAGE_POSE` from the damage record |
| attacker's `IMPACT_EFFECTS` (56) | 0x6ab6a6–0x6ab7d9 | on the **target's** face: `HITTAKEN` + `DAMAGE_POSE` := `DirectionManipulateDamage(event enum +0x20)` |
| own `DO_CHOKE_EFFECT` (93) | 0x6a7512–0x6a7542 | own face: `HITTAKEN` + `DAMAGE_POSE` := 16 `KNOCKDOWN_MIDDLE_LEFT` |
| `CharacterVisual.command_start_speak` | 0x69b7a1 | `START_SPEAK` (31). Callers: own `SOUND` (9) event with its speak flag (`m_ttruth1`) 0x6aba76; `SpeakCtrl.Active` 0x83d414; `TriggerActionSound.TriggerSoundPlay` 0x853e88 |
| `CharacterVisual.command_stop_speak` | 0x69b806 | `STOP_SPEAK` (32). Caller: `SpeakCtrl.Active` |

`ProjectAnimationLib.DirectionManipulateDamage` 0x802ae8 replaces a pose by
its `*_BACK` variant when the attacker is behind the victim, otherwise returns
it unchanged.

The body receives `DAMAGE_POSE` and its own action in the same calls
(`hit_soon`: body enum 4 before the head, body action 14 after it; `give_damage`:
body enum 4 and action 14 right after the head — same decompiled blocks), which is why a body
damage state and the face hit pose start together.

### 2.3 Candidates checked and ruled out

- **Forwarded animation events**: `CharacterRootLogic.command_animation_event_received`
  0x6a525e touches the face controller in two cases only (56, 93). The face
  classes contain no event nodes (0 in all three) [D], and no `EVENT`
  criterion.
- **Shared variables**: the face controller gets enum 1 and enum 4 only. No
  `ANIMATION_VALUE` is written to it, and the face classes have no `VALUE`
  criterion [D]. The body's state id, animation type and play position are
  not passed.
- **Explicit commands** (`hh.py face / expression / emotion / lip / blink /
  mouth / eye / talk`): no such command or property exists. `head` gives
  `CharacterHeadCtrl` (above) and `speak` gives the two `CharacterVisual`
  commands.
- **Lip-sync**: none. Speech only switches the Talk group on and off; there
  are no visemes and no amplitude input (section 3.4).
- **Blink**: not procedural. For `EN4_FACE` it is the idle state `IdleB`
  (pose `MouthClosed_EyesClosed`); the male classes have no blink at all
  (section 3.2). This corrects `ENGINE_CONSTANTS.md` 317 ("Blink timer — does
  not exist … the engine has no … blink") only in so far as a blink does
  exist for the women, as data.

## 3. The face state machines [D, rules R]

Parsed with the toolkit's loader (`anim_meta.load_class_tree`, face exclusion
bypassed); full records in `face_map.json` → `face_classes`. All three share
one layout:

```
Alive
  Active   (choose random)
    Idles  (choose random)   IdleA, IdleB
    HitResponse  [ACTION HITTAKEN, entry only]   HitLeft, HitRight, HitCenter, HitLow (+1 in EN4)
    Combat       Retreat [DAMAGE_POSE == STUN_MIDDLE], Attack [ACTION NORMAL_ATTACK]
  Talk     (choose random)   OpenMouth, ClosedMouth, Talk, ClosedMouth3 (some twice)
Dead       DeadA, DeadB  [CHARACTER_MODE == DEAD]
```

Every state: one layer (`MOTION_LAYER_1`), not looping, start position 0,
ease-in 0.21 s (0.37 s on `EN4` `KnockDownMiddleLeft(ClosedEyes)`), no events,
no idle timers except `NTO` `IdleB` (0.58 / 1.86 s, unused: single idle).
Every slot is a one-frame clip ("0.033333 s (1 frames, 30 fps)"), so the play
position is irrelevant and criteria use `PLAY_TIME` (seconds in the state).

### 3.1 Clips per state

| Face state | `EN1_FACE` (`Animation/EN1/FACE`) | `EN4_FACE` (`Animation/BS2/FACE`) | `NTO_FACE` (`Animation/NTO/FACE`) |
|---|---|---|---|
| IdleA | MouthClosed_EyesOpen | MouthClosed_EyesOpen | — |
| IdleB | Provocatively | **MouthClosed_EyesClosed** | NiteOwl_MouthClosed |
| HitLeft | DamageL | DamageL | NiteOwl_Biting |
| HitRight | DamageR | DamageR | NiteOwl_Biting |
| HitCenter | DamageStomach | DamageStomach | NiteOwl_Biting |
| HitLow | DamageBalls | DamageStomach | NiteOwl_Biting |
| KnockDownMiddleLeft(ClosedEyes) | — | Dead1 | — |
| Retreat | MouthClosed_EyesOpen | MouthClosed_EyesOpen | NiteOwl_MouthClosed |
| Attack | Attack1 + MouthShout_EyesAnger | Attack1 + MouthShout_EyesAnger | NiteOwl_Biting |
| Talk group | MouthShout_EyesAnger, Provocatively, MouthTalk_EyesAnger, MouthClosed_EyesOpen | MouthClosed_EyesOpen ×3, MouthTalk_EyesAnger ×2 | NiteOwl_Talk ×3, NiteOwl_MouthClosed, NiteOwl_Smile, NiteOwl_Biting |
| DeadA / DeadB | Dead1 / Dead2 | Dead1 / Dead1 | NiteOwl_MouthClosed ×2 |

All 24 shipped FACE clips are referenced, and no face class references a clip
outside its directory. `Attack` holds two slots in one blend node that has no
control parameter (`m_iblendctrlparam` 0, both `m_nweight` 1, the second with
`m_npriority` 0.3): the mix of the two poses is **not established** (the
toolkit's interpreter has the same open point for uncontrolled multi-slot
blends) [N].

### 3.2 Idle and fidgets

Transitions `IdleA → Idles [PLAY_TIME ≥ 3]`, `IdleB → Idles [PLAY_TIME ≥ 0.5]`;
the group has "Choose Random State". `command_get_valid_state` 0x5f076f
starts its scan at a uniform random index when the group flag (+0x0c) is set
(0x5f07bb–0x5f07d7, `FUN_0047aa2e`, a Mersenne-twister draw) and a pick of the
current state is a no-op. So: neutral for at least 3 s, then each frame a 50 %
chance to switch to the fidget pose, which is held at least 0.5 s, then each
frame a 50 % chance to switch back; 0.21 s ease each way.

- `EN1_FACE`: fidget = `Provocatively`.
- `EN4_FACE`: fidget = `MouthClosed_EyesClosed` → **this is the blink**
  (about every 3.1 s, eyes closed about 0.5 s, slow lids).
- `NTO_FACE`: one idle state, no fidget.

There is no dependence on the body animation: the cycle free-runs, and the
state the face is in when a body state begins is whatever the cycle is at.

### 3.3 Attack, hit, death

- **Attack**: `Idles → Combat [ACTION NORMAL_ATTACK]` (`EN1_FACE`
  additionally `CHARACTER_MODE == COMBAT`), `Attack [ACTION NORMAL_ATTACK]`.
  When the action stops, `Attack`'s criteria fail and its fallback transition
  returns to `Active` → idle on the next frame. `EN4_FACE` also leaves
  `Combat` for `Idles` after 0.3 s when not in combat mode.
- **Hit**: `Alive → HitResponse` (EN1, EN4: from anywhere under `Alive`,
  including Attack and Talk; NTO: from `Idles` only). Member by `DAMAGE_POSE`
  (`face_map.json` → `hit_pose_to_state`): upper-left / upper-straight /
  upper-back / stun-upper → `HitLeft`; upper-right → `HitRight`; middle-left /
  -right / -back / stun-middle / knockdown-middle → `HitCenter`; everything
  else, including `NO_POSE` and `*_MIDDLE_STRAIGHT`, falls to `HitLow`, the
  member without criteria. `EN4_FACE` sends `KNOCKDOWN_MIDDLE_LEFT` (the choke
  pose) to `KnockDownMiddleLeft(ClosedEyes)` = `Dead1`. `NTO_FACE` reacts to
  six poses only, all with `NiteOwl_Biting`.
  Leaving: EN1 / EN4 `HitResponse → Idles [PLAY_TIME ≥ 0.75]`. A further hit
  that maps to another member replaces it and restarts the 0.75 s; one that
  maps to the same member does nothing (EN4's knock-down member has "Allow
  more than once" and restarts). `NTO_FACE` has no timed exit: it leaves on
  the first frame `STOP_SPEAK` is fired, i.e. as soon as Nite Owl is not
  playing a sound — the hit pose lasts as long as his grunt [I from the
  transitions + 2.1].
- **Death**: `Alive → Dead`, members `[CHARACTER_MODE == DEAD]`; the group is
  not random, the scan starts at index 0, so `DeadA` is always taken and
  `Dead2` (`EN1` `DeadB`) is never reached by this path [I from 0x5f0792].

### 3.4 Speech

`Alive → Talk [ACTION START_SPEAK]`, `Alive → Active [ACTION STOP_SPEAK]`.
Inside Talk every member returns to the group after 0.2 s (EN1) / 0.15 s
(EN4, NTO); the group re-rolls a random member. With 0.21 s eases the mouth
never settles: that flutter between open, talk and closed poses is the whole
"lip-sync". It starts when a voice line starts and ends on the first silent
frame. `STOP_SPEAK` arriving every silent frame does not disturb the other
groups: the engine skips group members that are already in the evaluation's
tested list (3.5).

### 3.5 Two engine rules the toolkit's interpreter does not have [R]

Needed to simulate these classes; both are in `work/face/sim.py`.

1. `command_get_valid_state` 0x5f076f: the scan starts at index **0**
   (0x5f0792), or at a random index for a "Choose Random State" group. It is
   not a round-robin cursor (`anim_state_machine.Interpreter.get_valid_state`
   keeps `rr_index`).
2. The same function skips members found in the caller's tested list and
   appends each member it examines (the `(7)` / `(9)` list calls at the top of
   its loop); `command_get_valid_transition` 0x5f7873 and
   `GetValidStateGroupTransition` 0x5c6140 append every transition target
   before testing it. Without this rule `EN4_FACE` would re-roll its idle
   state on every silent frame and `EN1_FACE` would drop a hit pose after one
   frame; with it both behave as described.

## 4. Synchronisation

- **Start position**: irrelevant — one-frame clips, start 0, no walk-cycle
  flag, no sync markers, no override positions [D].
- **Play position copy**: none. The slave lock of pairs
  (`UpdatePagePlayPos` 0x5b5756) copies the master's source into the
  *partner's body* controller; the face controller's `_eslaveof` is never set
  (`goto_slave_mode` is sent to the partner's body controller only,
  `SetupNewPage` 0x5b9afb) [R].
- **Timing source**: the face reacts in the frame an input arrives (inputs are
  written and the face controller ticked inside the same
  `command_update_animation` call; hits arrive from the event handler in the
  same frame's body tick or one frame earlier) and then runs on its own
  `PLAY_TIME` clocks.
- **Paired animations**: there are no face clips per paired move and no
  selection by state id. Each side's face is driven like any other:
  - the master's face would hold `Attack` only if the master state had
    "Attack state" set; **no master state of a primary pair has it** [D], so
    the attacker's face stays in the idle cycle through finishers, counters
    and throws (unless it is hit or speaks);
  - the partner's face takes a hit pose at each of the master's
    `IMPACT_EFFECTS` (pose stored on the event), `PRE_IMPACT` and `IMPACT`
    events, at the master's time (the pair's shared clock), for 0.75 s each;
  - `KILL_ANIMATION_PARTNER` (master) or `DIE` (partner) switch the partner's
    face to `DeadA` for the rest;
  - `DO_CHOKE_EFFECT` on the partner state gives the closed-eyes pose.
  Example (`face_map.json`, Enemy04 `Finished_by_NiteOwl_F`, pair with
  NiteOwl `Finish_move_F`, seconds on the shared clock): idle → 0.43 HitLeft →
  1.20 idle → 1.57 HitLeft → 2.33 idle → 2.60 HitLow → 3.37 idle → 4.33
  KnockDown(ClosedEyes) (choke, re-triggered by each further choke event) → 7.67 DeadA.

## 5. The table — `findings/face_map.json`

Built by `work/face/gen_face_map.py` from the real fragments (staged
read-only from the device), the event nodes' raw properties, and
`anim_meta_v2.json` for durations, speeds, event times and pairs. For every
body state it lists the face inputs the game generates (`inputs`), the hits
the state deals to the other character (`inflicts`), and the resulting face
track (`track`; per primary pair `pair_tracks`), obtained by running the face
class in the interpreter (30 Hz, silent character, idle and talk states
collapsed to `IDLE` / `TALK`). The schema is in the file under `schema`.

Input rules used, with their level:

| Input | Rule | Level |
|---|---|---|
| `NORMAL_ATTACK` for the whole state | state has `m_tisattackstate` | R + D |
| `DEAD` from t = 0 | state's criteria chain requires `CHARACTER_MODE == DEAD` | R + D |
| `HITTAKEN` at t = 0 | state's criteria chain tests `DAMAGE_POSE`; the pose is one of the allowed values | R for the mechanism, **I** that the state is entered by that hit; several face states possible when several poses are allowed (`HIT_BY_POSE`) |
| `HITTAKEN` pose 16 at an own `DO_CHOKE_EFFECT` | event time from anim_meta | R + D |
| `START_SPEAK` at an own `SOUND` event with the speak flag | event time; end = end of the sound | R + D; end **N** |
| `DEAD` at an own `DIE` event | event time | R + D (I that the damage is lethal) |
| partner: `HITTAKEN` at the other side's `IMPACT_EFFECTS` | pose = event `m_ivalue00` | R + D; I that the attacker is not behind the victim |
| partner: `HITTAKEN` at the other side's `PRE_IMPACT` / `IMPACT` | pose = attacker state's Damage Pose | R for the call, **I** for the pose; left out of the track when that pose is 0 / unknown |
| partner: `DEAD` at the other side's `KILL_ANIMATION_PARTNER` | | R + D |

Statistics (Part 2 PC, 1,290 body states):

| | Enemy01 | EnemyBig | Enemy04 | NiteOwl | Rorschach | all |
|---|---|---|---|---|---|---|
| no face controller | | | | | 309 | 309 |
| idle cycle only (generic) | 152 | 95 | 153 | 217 | | 617 |
| attack pose for the whole state | 52 | 58 | 49 | 83 | | 242 |
| hit pose at entry | 20 | 17 | 25 | 5 | | 67 |
| dead pose for the whole state | 2 | 2 | 2 | 0 | | 6 |
| changes mid-animation on its own | 12 | 12 | 25 | 0 | | 49 |
| in a primary pair (with a face) | 38 | 28 | 55 | 82 | | 203 |
| … of those, changes mid-animation in the pair | 32 | 22 | 48 | 13 | | 115 |

- States with a specific face state: 364; falling back to the idle cycle: 617.
- Causes of the 49 solo mid-animation changes: death at `DIE` 45, speech 4,
  choke 1 (a state can have more than one).
- Causes in pairs (states): hit 126, death 53, speech 4.
- Hits dealt (`inflicts`): `IMPACT_EFFECTS` 317 events (poses: HEAVY_UPPER_STRAIGHT
  96, HEAVY_MIDDLE_STRAIGHT 71, LIGHT_MIDDLE_STRAIGHT 64, LIGHT_UPPER_STRAIGHT
  35, KNOCKDOWN_UPPER_STRAIGHT 20, …, NO_POSE 7), `IMPACT` 406, `PRE_IMPACT`
  334, `KILL_ANIMATION_PARTNER` 39.

Confidence per row: `high` (data + read code only), `medium` (contains an
inferred input), `low` (depends on sound playback: any talk segment, any Nite
Owl hit segment).

## 6. Proposed metadata extension (additive; not implemented)

### 6.1 `anim_meta.json`

Keep `format` "watchmen-anim-meta/2"; add a version key so consumers can test
for the block: `"face_format": "watchmen-face/1"`.

```
face
  classes      { face class: { engine_name, class_id, clip_dir, default_state,
                   groups [ {path, criteria, choose_random_state} ],
                   states [ {name, path, clips, ease_in_s, criteria, criteria_tree} ],
                   transitions [ transition record as in classes.*.transitions ],
                   hit_pose_to_state { DAMAGE_POSE name: face state | null },
                   idle_cycle { states {name: {clip, min_s}}, rule, evidence },
                   talk_cycle { states [ {name, clips} ], min_s, rule, evidence } } }
  body_class   { body class: face class | null }
  inputs       { NORMAL_ATTACK | HITTAKEN | START_SPEAK | STOP_SPEAK | DEAD:
                   {kind: action|enum, id, lifetime, sent_by, evidence} }
  attachment   { driven_bones [ {head_bone: "Head", body_bone: "Head"},
                                {head_bone: "Neck", body_bone: "Neck"} ],
                 nite_owl_extra [ L Clavicle, R Clavicle, LUpArmTwist, RUpArmTwist ],
                 attach_bone: "Spine2", head_model_yaw_deg: 90, evidence }
  conventions  { time: "t_s = seconds of play time since the state was entered;
                        clip time = start_playpos*duration + t_s*speed",
                 idle: "IDLE = idle_cycle, free-running, not tied to the body clip",
                 … }
```

On each **state** (`classes.*.states[*]`):

```
face { class, category, confidence, confidence_basis,
       inputs [ {t_s, time_s, input, damage_pose?, damage_pose_any_of?,
                 face_state_by_pose?, source, evidence} ],
       track  [ {from_s, to_s, face_state, clips?, ease_in_s?, one_of?,
                 sound_dependent?} ] }
inflicts [ {t_s, time_s, playpos, event, event_id, damage_pose, damage_pose_id,
            pose_basis, kills} ]
```

`time_s` (clip timeline) beside `t_s` (play time), as events already do.
`face` is `null` for a class without a face controller.

On each **pair** (`pairs[*]`):

```
face { clock: "seconds since both states started (timeline.playpos_per_second)",
       master  { class, inputs [...], track [...] },
       partner { class, inputs [...], track [...] },
       confidence, confidence_basis }
```

The events block could additionally expose, per event record, `enum_value`
(`m_ivalue00`) and `flags` (`m_ttruth1..3`): the face rules need the pose of
`IMPACT_EFFECTS` and the speak flag of `SOUND`, and format 2 drops both.

### 6.2 GLB

| Where | What |
|---|---|
| `skins[1].extras.watchmen` (the face skin) | `{ face_class, clip_dir, anchor_node: "f_anchor", anchor_follows: {body_joint: "Head"}, engine_attachment: <face.attachment>, pose_animations: { "MouthClosed_EyesOpen": <animation index>, … } }` |
| each `FACE <dir>/<clip>` animation's `extras.watchmen` | `{ face_clip: "<dir>/FACE/<clip>", pose: true, used_by: [face state names] }` |
| each body animation's `extras.watchmen.face` | the state `face` record of 6.1 for the states using the clip, with `written_time_s` beside every `t_s` when the clip is retimed (as events have) |
| `animations[i].extras.watchmen.pairs[*].face` | the pair's `face` record |
| synthetic animations | mark `FACE SYNTH Blink` / `FACE SYNTH Talk` and the face channels inside body animations with `extras.watchmen.synthetic: true` and the rule that produced them |

With that a Blender consumer can: put the idle cycle on an NLA track of its
own (IdleA ≥ 3 s, IdleB ≥ 0.5 s, 0.21 s blends, random), and on top of it
key, per body clip, the `track` segments as holds of the named `FACE …` pose
actions with `ease_in_s` blend-in — for a pair from `pairs[*].face`.

### 6.3 What the GLBs need for it

- **Pose clips**: present and findable. Every clip the three classes use is
  already in the animation list as `FACE EN1/…` (11), `FACE BS2/…` (9),
  `FACE NTO/…` (4) on the rigs that have a face (checked on
  `characters_v140`: Dominatrix_1..10, TwilightLady, Heavy, NiteOwl,
  NiteOwl_Dry) [D].
- **Attachment**: exported in substance (`face_root` → `f_anchor` keyed in
  every body clip from the body `Head` joint; proxies for body-driven
  parts). What is missing is only the *description* (which joint, that Neck
  is driven too) — the `skins[1].extras` entry above.
- **Missing face rigs**: Gimp1/2, Gimp7–11 and the three KnotTop thugs have no
  face nodes and no FACE animations, although the game gives those characters
  a head model with a face controller (`GoonCharVisual` etc. → `EN1_FACE`;
  head meshes from `BordelloFace` / `ThugFace`: `GimpHead1..3`,
  `Large/Medium/Small_Head_*`). Their face rigs would have to be attached
  before any face track can play on them.
- **Current face channels in body clips** (pose picked from the clip *name* by
  `face_synth.category_pose`, blink keys every 2.7–3.6 s) are not the game's
  rule: attack pose depends on the state's "Attack state" flag, hit poses on
  the damage pose and last 0.75 s, the blink exists for `EN4_FACE` only and is
  ~0.5 s closed every ~3.1 s, males have a `Provocatively` fidget instead.
  They should either be replaced by channels baked from `track` or be removed
  from body clips in favour of the pose actions + metadata; in both cases
  labelled.

## 7. Not established

- Mix of the two slots of the `Attack` state (`Attack1` /
  `MouthShout_EyesAnger`): uncontrolled blend, weights not read.
- The `DAMAGE_POSE` carried by `give_damage` / `hit_soon` when sent from
  `IMPACT` / `PRE_IMPACT` (taken as the attacker state's Damage Pose) and from
  `KILL_ANIMATION_PARTNER` / `DIE`; whether every such hit is delivered
  (range, block and `is_attack_successful` tests were not traced).
- How long a voice line or grunt plays (ends Talk; ends Nite Owl's hit pose).
  `SPEAK` (37) events only queue a line in `SpeakCtrl`; when it starts is not
  in the animation data.
- When `CHARACTER_MODE` is `COMBAT` for a given body state (it is game state:
  `StateActive` frame +0xac). It matters only for `EN1_FACE` `Attack`
  (requires `COMBAT`) and `EN4_FACE`'s 0.3 s exit; attack states were assumed
  to run in combat.
- The space of the bone transforms copied to the head model, and the exact
  composition order of the 90° turn.
- Which `CharVisual` fragment (hence face class) each `CHARACTER_TYPE` uses —
  read from the eight fragments' contents, not from the character
  definitions that reference them. `UB_FACE` (Underboss) has no data in
  Part 2.
- Head model index → mesh (`_imodelindex`) per character variant.
- Whether the face classes behave identically on Part 1 data (not parsed).

## 8. Addresses

| What | Where |
|---|---|
| `CharacterHeadCtrl` class registration | 0x671099 |
| `CharacterHeadCtrl.Init` (finds headmodel / headattach / AnimationCtrl, disables their own updates) | 0x664a11 |
| `command_activate` (head model, Spine2 attach, 90° turn, bone map) | 0x669496 |
| `command_update_head_ctrl` (tick face ctrl, look-at, bone copy) | 0x669f45 |
| `HeadCharacterUpdate` / `UpdateHeadBone` | 0x66a2a5 / 0x663ea5 |
| `UpdateHeading` / `UpdatePitch` (values 17 / 18 on the body ctrl) | 0x66a5ae / 0x66ab44 |
| `command_set_anims` (freeze at death) | 0x663bb3 |
| `command_get_animation_ctrl` (0x31908a4d) | 0x890ac2; uses at 0x6906be, 0x6929e9, 0x69b7bd, 0x69b822, 0x69c5f9, 0x69c80e, 0x6a7542, 0x6ab7d9, 0x6bc06d, 0x676366 |
| `CharacterVisual.command_update_animation` (face part 0x69c5f4–0x69c8b4) | 0x69b988 |
| `command_update_animation_fast` (no face) | 0x69b87d |
| `command_start_speak` / `command_stop_speak` | 0x69b7a1 / 0x69b806 |
| `command_hit_soon` / `command_give_damage` | 0x6903ea / 0x691b10 |
| `IMPACT_EFFECTS` face part / `DO_CHOKE_EFFECT` | 0x6ab6a6–0x6ab7d9 / 0x6a7512 |
| `DirectionManipulateDamage` | 0x802ae8 |
| `command_is_attacking` | 0x693249 |
| `IsShownOrClose` (`_tishead`, shown / frustum flags) | 0x5ab2ac |
| `command_get_valid_state` (start index, random, tested members) | 0x5f076f |
| `command_get_valid_transition` / `GetValidStateGroupTransition` | 0x5f7873 / 0x5c6140 |
| `FireAnimationAction` / `CopyTmpListToControlActionList` / `ClearOneFrameEvents` | 0x5aa83f / 0x5abe69 / 0x5aa4c0 |
| `CHARACTER_BONE_TYPE` / `CHARACTER_HEAD_BONE_TYPE` registrations | 0x672a62–0x672c08 |

Side note for whoever maintains the tools: `hh.py` fails on any name with more
than a few hits (`KeyError: 'argc'` — the registry records have no `argc`
key); `work/face/h.py` is a working copy with a `class:<name>` listing.
