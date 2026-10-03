# Engine constants from decomp — the ×3 playback mystery SOLVED (2026-07-09)

## Clip header, fully decoded
`.animation` header layout (verified on ALL 1163 clips, zero mismatches):

    offset 0  f32  keyRate     keys per second == (keyCount-1)/duration EXACTLY
    offset 4  f32  duration    true clip duration in SECONDS
    offset 8  u32  0
    offset 12 u32  keyCount    number of keys per track (t1/t2 tracks)
    offset 16 u32  frameRateScale   1=FULL 2=HALF 3=THIRD (of 30fps engine rate)

Decomp anchor: `Animation::SetFrameRateScaling` / property `frameRateScale`,
editor dropdown `items=FULL:1,HALF:2,THIRD:3`
(ghidra_kapow_out/deep3/decomp/part_0019.c, kernel/assets/animation/animation.cpp).
Scale histogram over the corpus: FULL 49, HALF 354, THIRD 760.
keyRate = 30/scale nominally (THIRD ≈ 10Hz, HALF ≈ 15Hz, FULL = 30Hz); actual
header keyRate varies slightly per clip because it's stored as (nk-1)/dur.

## What the old "×3 capture-calibrated" constant really was
The pipeline read hdr[0] (keyRate ≈ 10 for THIRD clips) AS THE DURATION and
divided by 3 — numerically close for THIRD clips (760 of 1163), wrong by 1.5×
for HALF and 3× for FULL clips. All timing now uses hdr[1] (true seconds):
`fps = (frames-1)/duration` (== keyRate × upsample). bake_v4 returns true
seconds; `bake_v4.fps_for()` is the one formula everywhere.

## SPEED_MULT post-mortem (variant_glb.py)
With header-exact fps, the old empirical multipliers for turn_180/turn_90/
turn_settle/step_forward/step_back/run_start/run_stop are reproduced NATIVELY
(needed-mult vs empirical: 2.66-3.19 vs 3.0, 1.79-1.83 vs 2.0, 1.42-1.65 vs
3.5→ etc.) — the captures were matching the true header rate all along. Those
entries are DELETED. What remains (genuinely runtime, engine `AnimSlot.SetSpeed`
scales locomotion to actual velocity):
- walk_cycle 2.3 (capture strut 1.43-1.63s vs authored 3.4s)
- run_cycle 2.6 (capture-era estimate rebased)
DANCE smalls: old 9.15/9.33 "beat sync" multipliers were calibrated against the
misread base and don't transfer; dance_cage_small_C is 882 keys / 88s authored.
Playing at header rate now — NEEDS QA; if dances look slow, suspect script
property `nanimspeed` (strings.tsv 0x00a5f3f0) or .sequence-driven playback.

## Cache format change
_bake npz now stores explicit `fps` (header-exact); loader falls back to the
legacy formula for old caches. FULL REBAKE recommended (finger-shear fix wants
it anyway): HALF/FULL-scale clips were playing 1.5×/3× too slow in every glb
built before this date.

## FACE pose holds
FACE clips (static poses, nk=2, header dur 30s): exported at fps=2 (1s hold)
instead of header-exact 30s strips — deliberate deviation, Blender ergonomics.

## Session gotcha (severe)
The Edit tool truncated/corrupted wlib files FIVE times this session
(characters_export ×2, variant_glb ×2 incl. trailing NUL bytes, bake_v4 ×1,
face_export ×1). face_export's tail was recovered by disassembling
wlib/__pycache__/face_export.cpython-310.pyc (marshal+dis) — pycache is a
viable recovery source. 
Protocol: edit wlib ONLY via python scripts writing to /tmp + ast.parse + copy.

# m_iHeadModelType — SOLVED (2026-07-09c)
It's the `ANIMATION_HEAD_MODEL` enum (full value map recovered from the enum
registration PUSH pairs, deep2/decomp/part_0029.c @0x0080b31c):
LARGE_HEAD_1=0 _2=1 _3=2 MEDIUM_HEAD_1=3 _2=4 _3=5 LARGE_3KT=6 SMALL_HEAD_1=7
SMALL_1KT=8 MED_MERC_1=9 _2=10 SMALL_MERC_1/2=11/12(inferred) LARGE_GOATEE=13
MED_GOATEE=14 UNDERBOSS=15 NITE_OWL=16 TWILIGHT_LADY=17 DOMINATRIX_1=18
GIMP_1=19 GIMP_2=20 DOMINATRIX_2=21 HEAVY_1=22 DOMINATRIX_3=23 DOMINATRIX_4=24
DOMINATRIX_5=25 GIMP_3=26.
Runtime: CharacterHeadModel (characterheadmodel_tnt.cpp, autodropdown over the
enum) + HeadCtrl script (FUN_0069c8e3: reads m_iHeadModelType, picks the model
from the level's head CharacterModelCollection — e.g. BordelloFace.fragment
holds GimpHead1-3 + the 5 female cutscene heads; gimpmask special-cased).
Dominatrix variants map: 1→21(D2) 2→18(D1) 4→24(D4) 5/7/10→23(D3=afro)
6→25(D5) 8→24 9→21.
BODY SKIN: settled — no code or data path selects a dark body texture.
FemaleSkinBody_{Dominatrix1,Black} both ship with ZERO references; every suit
model + every variant sheet says FemaleSkinBody_White. The dark trio differs
only by HEAD (enum 23 → dark head). Our _Black TEX_OVERRIDES stays a
deliberate user-chosen restoration, not game-exact.

# Jiggle — engine constants recovered (2026-07-09c)
GameEssentials.fragment PhysicsWorld node:
m_nbreastspringconstant=200 damping=0.8 distancelimit=0.08;
belly 70/0.8/0.1; hair 100/0.8/0.3.
Damping 0.8 behaves as a damping RATIO (d=2ζ√k≈20.9 predicted; capture-fit
AR(2) implies d≈17.9-19.4, k≈166-170 vs 200 — within ~15-20%; integrator
function not in our decomp dump, semi-implicit Euler assumed).
[corrected 2026-10-02: the capture-fit figures (k 166-170, d 17.9-19.4) came
from reading a capture that runs at about 55 fps as 30 fps; re-measured they
are K about 570, D about 37.5 for the breasts. The damping-ratio reading was
withdrawn on 07-09i. See "2026-10-02 (later)".]
jiggle_pass.py: now falls back to engine-derived AR(2) coeffs when
jiggle_params.npz is absent (fresh-install bug fixed: the npz lived only in
wlib/). Capture-fit npz stays preferred when present.

# Runtime layers / weapon grip (2026-07-09d)
Engine machinery confirmed in exe: AnimLayer (kernel/animation/animlayer.cpp;
additive flag, ease in/out, weight, ANIMATION_LAYER enum) driven by the
animation STATE MACHINE in AnimationClass*.fragment (AnimationStateGroupWM
nodes: m_ianimationcriteria/value/action, m_neaseinduration, m_nweight,
m_etostate transitions...).  Full graph reversing = its own project; NOT done.
PRACTICAL EXTRACTION: while armed the hands hold the WPN-pose grip.  Exported
as `GRIP 1H` / `GRIP 2H` 2-frame PARTIAL anims per character glb (channels
only on the R-Hand subtree, +L for 2H; source = frame 0 of the family's
WPN_xH_idle_stand, fallback idle_fidget/any WPN clip).  NLA-layer them over
any body clip, exactly like FACE poses.  variant_glb.write_glb now accepts
4-tuple manifest entries (name, pal, fps, bone_indices) for partial anims.
QA: GRIP_QA_Dominatrix2.glb (run_cycle + idle + WPN fidget + GRIP 1H).

# Face synthesizer (tier-3) — DONE (2026-07-09f)
wlib/face_synth.py: blend_pal (per-bone slerp between static pose palettes),
blink_anim (open->0.07s close->0.07s hold->0.10s open, loopable 4s),
talk_anim (4Hz syllable bursts x phrase envelope, seeded, loop-clean),
category_pose (body-clip name -> shipped pose name).
Wiring: _face_attach appends 'FACE SYNTH Blink'/'FACE SYNTH Talk' (shipped
poses only: blink = BS2 family only, males/NTO ship no eyes-closed pose) and
returns auto_poses/blink_closed; variant_glb write_glb AUTO-PAIRS: every body
anim's face channels = category pose (ATT/WPN/counter->Attack1|Shout|Biting,
DMG->DamageL/R/Stomach, dead->Dead1/2, dance/flirt->Provocatively|Smile) or
neutral + sparse BLINK keys on the EyeLid bone (~3s cadence, deterministic
per clip name).  QA: SYNTH_QA_Dominatrix2.glb.

# WARNING: _bake cache integrity (2026-07-09g)
101/190 npz in 20260708/characters/_bake/female READ as corrupt from this
session's sandbox mount (this session also saw 6 tool-side file truncations
incl. NUL-byte tails, so the mount is suspect, not necessarily the disk).
CHECK ON REAL HW: python -c "import glob,zipfile;print([f for f in glob.glob(r'20260708/characters/_bake/**/*.npz',recursive=True) if not (lambda x:(zipfile.ZipFile(x),1)[1] if 1 else 0)(f)])"
-- harmless either way: the header-exact fps + finger-shear fixes require a
full rebake (delete _bake/* and characters/*.glb, rerun watchmen.py characters).

# Empirical remainder + decomp coverage assessment (2026-07-09h, session close)

## Decomp coverage
ghidra_kapow_out IS the full exe: 14,910 functions, 38 shards, 0x401000-
0x9e4400 (+4 deep re-passes).  "Not found" hereafter means vtable/data-driven
dispatch or genuinely external — not missing decomp.
[corrected 2026-10-02: that dump was not complete. 2,000 functions that open
with the __EH_prolog call were 10-byte stubs, and 1,191 registered handlers
had never been defined as functions. tools/ghidra/ repairs both; the program
then has 17,225 functions.]

## PhysX (user callout — likely right)
Game ships PhysX 2.8.1 installer (prerequisites/); exe wraps it
(kernel/collision/physx/physx_{physicssystem,rigidbody}.cpp, PhysXBlockCloth
allocators).  If jiggle springs feed PhysX joints, the integrator is in
NVIDIA's closed DLLs — explains zero exe refs to the spring-update AND zero
code refs to the "Breast Distance Limit" caption.  DECIDABLE TEST: find where
m_nbreast{springconstant,springdamping,distancelimit} are CONSUMED in the exe
(prop-hash lookup) and see what they feed.  NxSpringDesc semantics are public:
force=-k*x-d*v, damper ABSOLUTE => 0.8 absolute at k=200 would be near-
undamped (zeta~0.03), but capture fit shows d~18 => either the game converts
(2*zeta*sqrt(k), our current ratio assumption) or jiggle is game-side.

## Still-empirical inventory (verdicts)
IRREDUCIBLE (runtime, no file constant): walk/run SPEED_MULT 2.3/2.6
(AnimSlot.SetSpeed velocity sync); blink/talk timing (engine does it
procedurally, talk likely audio-driven — one grep for a FaceCtrl-ish blink
timer constant is worth doing before calling it invented).
IN THE DUMP, DIGGABLE: grip/aim state-machine interpreter semantics
(AnimationStateGroupWM handlers; graph itself = fragment data we already
parse) — would replace 3 heuristics at once (grip timing, face pairing,
layer weights); enemy-class->weapon-collection binding; CharacterHeadModel
attach/skinning; SMALL_MERC enum 11/12 (read more of part_0029 PUSH list);
dance rate (nanimspeed script host?  dropped mults, needs QA at header rate).
HALF-IN: roughnessGen spec model — exe selection logic + derived_pc/
precompiled_shaders on disk (D3D9 bytecode, disassemblable externally).
DATA/ANALYSIS, NOT DECOMP: RSH/NTO palette-set mixing (residual 0.03-0.06,
never re-examined post-filebind); head-twin ICP/weight-transfer (0.7mm,
good enough unless CharacterHeadModel read says otherwise).
CHOICES, NOT BUGS: players get all 15 weapons; FACE 1s holds; _Black skin
restoration; jiggle distance limit unimplemented in jiggle_pass.

## Next decomp session, in order
1. Jiggle prop-consumption trace (settles PhysX-vs-game-side + damper units).
2. State-machine interpreter (biggest payoff, 3 heuristics).
3. Cheap ride-alongs: SMALL_MERC values, blink-timer grep, nanimspeed/dance,
   weapon-collection binding.

# JIGGLE PROP TRACE — SOLVED: it IS PhysX, via NxD6Joint swing soft-limits (2026-07-09i)

## Why previous greps failed
The registration fn FUN_0047fde4 has an SEH prologue (mov eax,imm; call 0x991850)
that made Ghidra truncate it to a 10-byte stub, and the whole PhysicsWorld ctor
(0x7eba0e) + CharacterAddonCtrl code (0x6563a0-0x657d54) fell in DECOMP GAPS.
Raw capstone disasm of the executable was required. Caption strings are
pushed as code immediates (PUSH imm32), findable by scanning .text for the
string VAs — grep of decomp .c files misses them.
[corrected 2026-10-02: the truncation is repaired by
tools/ghidra/FixEHProlog.java (0x47fde4 decompiles to 175 bytes, 0x7eba0e to
694). The CharacterAddonCtrl code was not truncated: those handlers were never
defined as functions, which tools/ghidra/DefineKapowHandlers.java does.]

## PhysicsWorld property slots (class "PhysicsSimulation"/"PhysicsWorld", id 0xfb)
Ctor at 0x7eba0e registers 16 float props in order; values live in a block at
[[[0xe171f8]+0x10]]+0x10 + slot*4 (0xe171f8 = script-class instance global):
slot 7 breast k (hash 0x868ac175 = kapow_hash("M_NBREASTSPRINGCONSTANT"), default 1000)
slot 8 breast damp (0x35ae65e1, default 0.5)   slot 9 breast lim (0x0daaedf3, 0.08)
slot 10/11/12 belly k/damp/lim (0x05da2a7e/0x92c25d0c/0xaac6d51e, 1000/0.5/0.1)
slot 13/14/15 hair k/damp/lim (0xd0d08f4d/0xbfbeb999/0x87ba318b, 1000/0.5/0.3)
Each hash appears EXACTLY ONCE in the exe (registration); consumption is by
direct slot read.

## Addon setup (CharacterAddonCtrl, 0x6574cd)
Per skeleton: Spine2->BreastL, Spine2->BreastR, Spine->JiggleBelly (+hair) each get
a dynamic "MockupBox" (depth=width=height=0.1, movementtype=1, enabled) inside an
"EmbeddedJointNode", collision-grouped, mass-ish call 0x4fe514(0.1).
Per-type distance limit (slots 9/12/15) is copied to [joint+0xc] at 0x657c93:
addon idx 0/1->slot9(breast), 2->slot12(belly), 3->slot15(hair).
[corrected 2026-10-02: there are two boxes per addon. The 0.1 m box is the
kinematic anchor, placed on the PARENT bone; the simulated body is a second
MockupBox of 0.8 m (f32 @0xa06d84), mass 0.1, placed on the child bone. The
EmbeddedJointNode is a child of the anchor box. The fourth addon is
Head->Hair.]

## Spring consumption (0x648b27-0x648cd1) — THE ANSWER
k/d selected per addon type (breast slots 0x1c/0x20 = 7/8, belly 0x28/0x2c,
hair 0x34/0x38 in the *4 block) and applied to the D6Joint at [body+0x138]:
  SetYMotionType(0=Locked) 0x517982, SetZMotionType(0=Locked) 0x517994
  Swing1LimitSpring = k   (0x5194ed -> [d6+0x100])
  Swing2LimitSpring = k   (0x5195b0 -> [d6+0x120])
  Swing1LimitDamping = d  (0x519516 -> [d6+0x108])
  Swing2LimitDamping = d  (0x5195d9 -> [d6+0x128])
  Swing1LimitValue = 45.0 (0x51947c <- const @0x9fffa8)
  Swing2LimitValue = 0.0  (0x51953f)
Setter->name proof: D6Joint property registration records at 0x520xxx pair
"D6Joint::Set<Prop>" debug strings with the setter fns (c7 45 e0 imm32).
Motion enum = Locked:0,Limited:1,Free:2 (== NxD6JointMotion).

## VERDICT
- Jiggle simulation = PhysX 2.8.1 (PhysXLoader.dll, virtual dispatch — hence
  zero import-level evidence). The game only CONFIGURES an NxD6Joint.
- Translation locked => box is an ANGULAR pendulum around the bone anchor.
[corrected 2026-10-02: the pivot is the PARENT bone origin (the joint frame is
the anchor box's frame), the lever is the parent->bone offset, and twist about
X is locked too.]
- m_n*springdamping 0.8 is the NxJointLimitSoftDesc.damping (ABSOLUTE, torque
  domain), NOT a damping ratio. Swing2 limit=0 deg => its soft spring is
  always engaged (continuous restoring spring); Swing1 free cone to 45 deg.
- m_n*distancelimit is GAME-side: position clamp + writeback in the big addon
  update fn 0x6563a0 (the sqrt-guard code), independent of the joint.
- Consequence for jiggle_pass: capture-fit AR(2) stays the ground truth (it
  measures the emergent linear-domain response incl. box inertia/lever arm).
  The engine-constant fallback's 2*zeta*sqrt(k) "ratio" reading was a numeric
  coincidence; exact file-only reproduction would need MockupBox inertia
  (0.1^3 box, mass~0.1) + swing-limit mechanics — capture npz preferred stands.
[corrected 2026-10-02: the simulated body is the 0.8 m box, not the 0.1 m
one.]

# AnimationStateGroupWM interpreter — architecture + key semantics (2026-07-09j)

## Method table (animation-system script class, id 0x15; registered @0x5e58a2+)
AnimationCriteriaMet=0x5c5781  TransitionMet=0x5c5ea4  StateGroupCriteriaMet=0x5c6002
GetValidStateGroupTransition=0x5c6140  StateCriteriaMet=0x5c647c
GetAnimationValue=0x5ae18f  GetHeldAnimationValue=0x5ae1c5  SetAnimationValue=0x5aa701
FireAnimationAction=0x5aa83f  UnfireAnimationAction=0x5aa86b  IsAnimationActionPending=0x5aa7f7
GetAnimationPlayPos=0x5ae294  SetAnimationPlayPos=0x5ae2e1
Class registrations (all Ghidra-stubbed, need raw disasm): AnimationStateGroupWM
ctor=0x605148 (handlers: command_get_valid_state=0x5f076f, command_add_criteria=0x5f9c49,
command_add_transition=0x5f0741), AnimationCriteria(WM) ctor=0x5d2b00s,
AnimationTransitionWM ctor=0x60d4a0s, blend-node classes 0x5a6f00s/0x5a7900s.

## ANIMATION_CRITERIA enum (from PUSH pairs)
VALUE=0 ACTION=1 ENUM=2 EVENT=3 PLAY_TIME=4 PLAY_POS=5 REVERSE_PLAY_POS=6
OVERLAY_PLAY_POS=7 REVERSE_OVERLAY_PLAY_POS=8 ANIM_PLAY_DONE=9 FORCE_ANIM=10
ANY_OF=11 ALL_OF=12

## AnimationCriteriaMet (0x5c5781) semantics recovered
- Criteria object: testtype@[crit+0x10]+0x18 (INTERVAL:0, LESS_THAN:1, GREATER_THAN:2),
  min@+0x1c, max@+0x20; numeric compare via helper 0x77aa25(value,min,max,testtype).
[corrected 2026-10-02: type 2 is GREATER_THAN_OR_EQUAL. MathLib.InsideInterval
0x77aa25: 0 = min <= x < max, 1 = x < MAX (min is not read), 2 = x >= min.]
- m_ttestonentryonly: if set and not entering, returns cached/true early ([esi]=1 path
  @0x5c58a3 keyed on state-entry flag [ctx+0x38] compare).
[corrected 2026-10-02: an entry-only criterion is met without testing only
while the top page's state is the criterion's owner state or lies inside its
owner group, and never during the normal transition pass (state +0x68).]
- PLAY_TIME(4): value = current anim slot record +0x34 (seconds played).
- PLAY_POS(5)/OVERLAY(7): value = slot record +0x10 (normalized 0..1);
  REVERSE_* (6/8): value = 1.0 - playpos. Overlay variants read the OVERLAY slot
  (record picked via [state+0x10]+0xc chain with slot index from 0xe16fd8 global).
- EVENT(3): resolves event id, checks fired-event list (>=0 index -> met).
- ANY_OF(11)/ALL_OF(12): recurse over child criteria (OR/AND).
- NOT Criteria prop inverts the result; min/max are STRINGS in the fragment
  (support ANIMATION_VALUE refs, not just literals).

## AnimationTransitionWM fragment props (ctor 0x60d4a0)
to-state (entityref), fallback?, Override Ease In? + Ease In Duration (0..2s,
default 0), Override Start PlayPos? + Start PlayPos, Sync PlayPos?, and 8 pairs
of Sync markers (left/right, default -1): piecewise-linear playpos remap between
outgoing and incoming clips. m_neaseinduration consumed at 0x60b325/0x60d5b6/
0x60dd42; m_etostate at 0x60d56e/0x60dcfa.
[corrected 2026-10-02: the markers are (local, remote) play positions,
m_nsupersynclocal1..8 / m_nsupersyncremote1..8. They also gate the transition,
and the remap clamps to the first / last remote marker; it is a one-shot start
position. The addresses listed are registrations, not consumers (see 07-09m).]

## Blend-tree nodes (0x5a6f00s/0x5a7900s registrations)
Props: Force Playpos=1.0, Parent blend pos, Child value (ANIMATION_VALUE),
Polar compensation?, mode MANUAL:0/VELOCITY:1/DIRECTION:2, Blend interval
start/end (strings), Weight (m_nweight hash 0xc058b077, default 1.0).
=> m_nweight is the per-blend-node weight inside AnimBlendSource trees
(AnimLayer::Set* / AnimBlendSource::EaseIn/Out drive actual layer easing).

## Practical status
Full graph EXECUTION (state entry -> slot start w/ ease + layers) remains
unreversed; but criteria/transition/blend semantics above + the fragment graph
we already parse cover most of what the grip-timing/face-pairing/layer-weight
heuristics approximate. Handler addresses above give a fresh session a direct
on-ramp (raw capstone disasm required — ALL these fns are Ghidra 10-byte stubs
due to SEH prologue `mov eax,imm32; call 0x991850`).
[corrected 2026-10-02: repaired by tools/ghidra/FixEHProlog.java; these
functions decompile now.]

# Cheap ride-alongs — all closed (2026-07-09k)

## SMALL_MERC — CONFIRMED
ANIMATION_HEAD_MODEL SMALL_HEAD_MERC_1=11, SMALL_HEAD_MERC_2=12 (PUSH pairs;
also MEDIUM_HEAD_MERC_1=9/_2=10, matching earlier inference exactly).

## Blink timer — DOES NOT EXIST
Zero blink/eyelid/facectrl strings in the exe; zero 'blink' hits in extracted
Animation/TNT data. The engine has NO procedural blink. Our synthesized ~3s
EyeLid cadence is officially an invention (keep, but label as such).

## nanimspeed — script blackboard local, unused
Registered once (0x6c1259) as a script-VM LOCAL of an AI/character script class
(alongside nsign, etargetlist...). No value anywhere in extracted data. Dance
rate verdict: header-exact fps stands; if dance QA looks slow the cause is NOT
nanimspeed — check .sequence timing instead.

## Enemy class -> weapon binding — data/script-side
No exe table. WEAPON_TYPE enum: BASH_1H/MELEE_ONE_HAND=0, BASH_2H/MELEE_TWO_HAND=1.
[corrected 2026-10-02: this merges two families that share the prefix
WEAPON_TYPE___: WEAPON_TYPES {NONE -1, BASH_1H 0, BASH_2H 1} (registered in
0x6726d6) and WEAPON_TYPE {MELEE_ONE_HAND 0, MELEE_TWO_HAND 1} (0x8bb4aa). The
animation criteria test neither: enum variable 5 is WEAPON_ANIMATION_TYPE
{UNARMED 0, BASH_1H 1, BASH_2H 2}, variable 12 is OPPONENT_WEAPON_TYPE {NONE
-1, BASH_1H 0, BASH_2H 1}.]
Selection flows through script command "command_set_weapon" (+ thas1h/2hweapon
blackboard vars); per-class weapon sets live in fragment data (WeaponDB colls,
already wired 2026-07-09 attachments session). Hit-effect entityrefs
(Sharp/Body/Head weapon wood/steel...) = CharacterEffectDef class @0x66f652.

## Bonus: CHARACTER_TYPE enum (full)
RORSCHACH=0 NITE_OWL=1 BIKER=2 BIKER_BIG=3 PRISONER=4 PRISONER_FAST=6 THUG=8
THUG_BIG=9 THUG_FAST=10 THUG_LEADER=11 MERCENARY=12 MERCENARY_FAST=14
MERCENARY_LEADER=15 MINION=16 MINION_FAST=18 MINION_LEADER=19 COP=22
COP_LEADER=23 UNDERBOSS=25 BIKER_HEAD=26 PRISONER_ELITE=27 GO_GO_DANCER=28
HEAVIES=29 KNOT_TOP_NORMAL=30 _FAST=31 _BIG=32 DOMINATRICE=33 GIMP=34
TWILIGHT_LADY=35 GIMP_WITH_GAGBALL=36
[corrected 2026-10-02: the list omits COP_FAST=24 and INVALID=-1 (32 names).
The family is CHARACTER_TYPES, prefix CHARACTER_TYPE___. It is not what the
animation criteria test as the opponent's model type; that is
OPPONENT_MODEL_TYPE.]

# Session notes (2026-07-09 decomp session)
- Workflow that works: scan exe bytes for string-VA immediates / prop-hash
  immediates with Python+capstone; Ghidra decomp is unreliable for any fn with
  the SEH prologue (14,910 fns but MANY key ctors/handlers are 10-byte stubs).
- kapow_hash confirmed for engine PROPERTY hashes too (m_nbreast* etc.), not
  just asset records: hash = bit-CRC32(UPPERCASE name).
  [corrected 2026-10-02: the engine ANDs every byte of the name with 0xDF
  (FUN_00423ce8). That equals upper-casing only for letters and '_'; a name
  with a digit or punctuation hashes differently. The m_nbreast* names are
  letters only, so their hashes stand. On the first item: the stubs are
  repaired by tools/ghidra/.]
- Fresh-cache check FROM SANDBOX failed again (all npz/glb tails truncated via
  mount, glb header len 38.4MB vs served 27.6MB) — verify on real HW; disk
  likely fine, mount serves stale partials of large fresh binaries.

# NEXT SESSION HANDOFF (rewritten 2026-07-09 session r close)

## Session r status
Fresh-install SMOKE TEST PASSED (user-run: wlib + game.naz only, deps numpy+
Pillow): 7/7 binds file-only, audio/extracted exact parity vs 20260708,
textures/models strict superset (+decal obj/mtl, +roughnessGen.png).
smoketest/outdir_20260709130900 = candidate new canonical extract.
parse_model_nodes.py quat-scan overflow warning FIXED (f64 cast).
Exe constants promoted into wlib: engine_schema.py + reg_dump.json +
prop_names_from_reg.json (defaults(class), prop_info/caption).

## NEXT (user-approved): file-only jiggle — NxD6 integrator in wlib
Goal: retire capture-fit wlib/jiggle_params.npz (AR(2)) with a physics
integrator using only file-side data. Deliverable: wlib/jiggle_d6.py
(same interface jiggle_pass exposes, so bakes can switch).
Data sources (all file-only):
- spring/damping props: m_nbreastspringconstant etc. in fragments;
  PhysicsWorld slots 7-15, hash = kapow_hash(UPPERCASE), reg @0x7eba0e.
- joint frames + bodies: .model node aux EmbeddedJointNodes —
  parse_node_aux() in wlib/parse_model_nodes.py (Spine2->BreastL/R,
  Spine->JiggleBelly, 0.1^3 MockupBox bodies).
  [corrected 2026-10-02: the node aux records are collision volumes, not joint
  nodes, and hold no jiggle joint frames; the joint is created at run time in
  the parent bone's frame. The simulated body is a 0.8 m box.
  "kapow_hash(UPPERCASE)" above: see the hash note in the 07-09 session
  notes.]
Semantics (2026-07-09i/j, sections above + jiggle-physx memory):
- NxD6Joint: Y/Z translation LOCKED -> angular pendulum. k -> Swing1+Swing2
  LimitSpring ([d6+0x100]/[+0x120]); d -> LimitDamping ([+0x108]/[+0x128]).
  Swing1LimitValue=45deg, Swing2=0deg (always-engaged restoring spring).
  Damping is ABSOLUTE torque-domain (NxJointLimitSoftDesc), NOT a ratio.
- m_n*distancelimit = GAME-side position clamp (CharacterAddonCtrl update
  0x6563a0); setup 0x6574cd. Both are decomp GAPS -> use exe_dis.py.
- PhysX 2.x soft-limit: tau = spring*err + damping*vel while limit engaged;
  gravity + parent-bone acceleration drive the pendulum; dt = frame tick.
  [corrected 2026-10-02: gravity does not drive it. The game applies -m*g to
  the jiggle body every frame (0x656fb4). The physics step is 1/60 s, not the
  frame tick.]
Validation: jiggle_params.npz AR(2) output + capture QA glbs
(CHAR_Dominatrix_1_JIGGLE_QA / SPEED_JIGGLE / NOJIGGLE). Compare bone-angle
traces on the same clips; success = matches capture at least as well as
AR(2) fit.
Open detail to nail early: exact mass/inertia of the 0.1^3 MockupBox and
whether gravity vector is world -Z or -Y in engine space (check 0x6563a0).

## Also open (lower priority)
Interpreter hardening: transition from-filter (unnamed props 0x381c10c0/
0x1d3171a6/0x52340773/0x5234171b — read TransitionMet 0x5c5ea4 field
offsets), overlay pages, capture validation; then retire grip/face/layer
heuristics. Format residue: joint type4/5 blobs, meshbuffer internals,
.sequence flags{0,1,4} + tangent dwords, 2 asset-type hash names, magic
0x593F430A.
[closed 2026-10-02: the unnamed transition props are the runtime marker cache,
not a from-filter; joint type 4 / 5 records are convex-mesh and box collision
volumes; mesh buffers, .sequence, the two type-hash names and the block header
are in "2026-10-02 (later)".]

## Tooling
a capstone-based disassembler (pip install capstone
--break-system-packages) — ALWAYS use it over Ghidra for SEH-prologue fns
(CharacterAddonCtrl setup/update are such gaps). reg_scan.py = registration
scanner (regenerates wlib/reg_dump.json).
[corrected 2026-10-02: with tools/ghidra/ applied the Ghidra decompilation
covers these functions.]

# 2026-07-09m — STATE-MACHINE EXECUTION (run loop reversed)

## Correction to handoff
0x60b325 is NOT the m_neaseinduration consumer — it is a SECOND registration
of AnimationStateWM props (class registered twice: 0x605ce3 and ~0x60b1xx).
ALL 4 code refs to hash 0xc457385c are registrations. Runtime reads props via
the native record at [node+0x10] with FIXED OFFSETS (assigned at reg time),
never by hash — so hash-ref hunting cannot find consumers. Known offsets:
state rec: +0x38 easein, +0x6c transitions list, +0x78 fallback/default;
group rec: +0x14 transitions, +0x18 default state; transition rec:
+0x8 target, +0xc from-filter.
[corrected 2026-10-02: record offsets are 4 x registration index. State: +0x38
is m_nstartplaypos, +0x3c m_neaseinduration, +0x4c m_efallbackstate, +0x6c the
transition list, +0x78 m_estoredtransitstate. Transition: +0x08 m_etostate,
+0x0c m_tfallback (not a from-filter). Full table in "2026-10-02 (later)".]

## Registration scan (`watchmen gendata regdump` -> reg_dump.json)
Scans exe for call sites of:
  0x47e126 create class (name, classId, ?, baseName)
  0x47fde4 register prop (hash, defaultVA, uiCaptionVA, 3, X)
  0x47eccc register command (nameVA, argc, ?, hash, handlerVA)
441 classes, 4976 props, 6630 commands. Prop hash = kapow_hash(UPPER(m_name))
(verified: m_neaseinduration=0xc457385c, m_nstartplaypos=0x125d3ff7).
[corrected 2026-10-02: argument lists: 0x47e126 (name, classId, nativeBase,
scriptParent|0, flag, flag); 0x47fde4 (hash, defaultVA|0, uiVA, flags,
typeIdx); 0x47eccc (name, kind, arg3, hash|-1, cmdHandler, stateHandler,
methodHandler, typeIdx). "argc" is `kind` (1 or 3), not an argument count;
typeIdx is the declaring class. Counts: 5090 props (this scan missed 114),
6630 commands. Prop hash = CRC over the name's bytes & 0xDF, not UPPER(name);
the two verified names are letters only.]
Full AnimationState/StateGroup/Slot/Transition schemas incl. defaults + UI
captions in reg_dump.json. Fragment JSON nodes_full props carry the same
m_* names + values (kapow_fragment already resolves them) — interpreter needs
no exe access.

## Run loop (AnimationCtrlWM script methods, all in reg_dump.json)
StateMain 0x5b417b, Update 0x5b4613, EvaluateTransitions 0x5cbbc2,
TransitToState 0x5b4a31, SetupNewPage 0x5b7788 (NOT in ghidra - SEH),
UpdatePageBlendsFaster 0x5b4bd6, SetAllSlotBlends 0x5b4ef7,
UpdatePagePlayPos 0x5b56a9 (NOT in ghidra - SEH), TransitionPlayPos 0x5ac1aa,
SynchronizePages 0x5ac387, CheckPlayPosEvents 0x5b51f3.
[corrected 2026-10-02: "NOT in ghidra - SEH" names the wrong cause.
SetupNewPage and UpdatePagePlayPos are handlers reached only through the
registration table, and Ghidra had not defined them as functions.
tools/ghidra/DefineKapowHandlers.java creates them (9479 and 8415 bytes).]
Execution model = PAGES: each state entry pushes a new page (its slot set);
pages cross-fade by page blend; slot weight = m_nweight * pageblend
(UpdatePageBlendsFaster: FUN_0059397a(slot, w); slots >#9 maskable by
[rec+0x18] bitmask when [rec+0x14] set).
[corrected 2026-10-02: not every state entry pushes a page. None is created if
the top page already plays the state (unless "Allow more than once"); a state
already lower in the stack has its old page removed and the new one starts at
that page's share.]

## command_get_valid_state 0x5f076f (group cmd #6, hash 0x499d201a)
Round-robin over group children STARTING AFTER current index ([slot rec]:
cur idx, start idx, wrap at count; count = (hdr&0xffffff)/stride). Per child:
- classid via 0x4f99c3(node, 0, &out); 7=stategroup, else state.
- state child: must pass flag check (byte rec+0x54 && rec+0x40 bit0 =
  enabled/valid) then StateGroupCriteriaMet 0x5c6002; matching child with
  criteria present + met wins; group child: StateGroupCriteriaMet then
  RECURSE via its own command #6 (0x596d91 dispatch: cmd table idx 6, hash
  verified 0x499d201a at [class+0x1c][6]+0x18).
- returns 0 if a full cycle finds nothing.
[corrected 2026-10-02: the +0x54 / +0x40-bit0 tests are entity fields
(enabled), not record offsets.]
StateGroupCriteriaMet 0x5c6002: member2 (single criteria) evaluated if
present, then member1 = criteria LIST — ALL must pass (AND). Each criteria
evaluated by its class-method [criteria class rec + 0xc]+0x24 via thunk
0x479874(handlerVA, ctx, args) which sets script ctx global 0xe12d9c.
[corrected 2026-10-02: "member2" (record +0x08) is m_eanimstategroup, the
OWNING group, not a single criterion; +0x04 is m_ecriterialist.
StateGroupCriteriaMet = owner chain AND own list; StateCriteriaMet 0x5c647c =
own list only.]

## GetValidStateGroupTransition 0x5c6140 (method-table entry)
Transitions list: state IsKindOf([0xe16844]=AnimationState) -> [rec+0x6c];
group IsKindOf([0xe16f28]=AnimationStateGroup) -> [rec+0x14]. For each T:
- from-filter: [T rec+0xc] must equal current ([args+0x10]) (after typed
  index checks vtbl+0x60 types 7/9)
- TransitionMet (method idx 8 = 0x5c5ea4) with (args+8, args+0xc, T)
- target = [T rec+8]; if target classid==7 (group): StateGroupCriteriaMet +
  command_get_valid_state on it -> must yield state; else (state): its
  criteria (member2) must pass if present.
- WINNER: sets prop hash 0x761caa4e (= next/valid state ref, in
  AnimationState+StateGroup schema) via prop-set 0x5107b2, returns T.
- Fallback if none: node member2 criteria met -> default target:
  state rec+0x78 / group rec+0x18 ("Fallback state" prop 0x377d69a UI).
[corrected 2026-10-02: (1) T rec+0xc is m_tfallback, compared with the pass
flag: the normal pass takes only non-fallback transitions, the fallback pass
only fallback ones, and each target is tried once per evaluation. (2) A state
target is gated by the transition's criteria, the target state's own criteria
(appended by AnimationTransition.initialize_external 0x5f9b13) and
StateGroupCriteriaMet of its owner chain. (3) The fallback state is record
+0x4c. The fallback pass runs when the state's or its owners' criteria fail;
then m_efallbackstate, the class default state, the class safety state.
0x761caa4e is m_estoredtransitstate (+0x78).]

## TransitToState FUN_005b4a31 (ghidra part_0021.c:11791)
ease_in = args[2] if args[2] >= 0 else state_rec+0x38 (m_neaseinduration);
soft-blend variant flag from target-state rec (+0x18/+0x10 chain) selects
mode 1 w/ easein from top page state when overriding. Then invokes class
method [class rec+0xfc]+0x24 (native transit) with
{state, args[1], ease_in, softflag, page}.
[corrected 2026-10-02: args = {state, ease, playpos}. ease < 0 means the
state's own m_neaseinduration (+0x3c); args 2 is the START PLAY POSITION, < 0
meaning the state's m_nstartplaypos (+0x38). It passes {state, playpos, sync,
ease, pagelist} to SetupNewPage; sync is set when both states are walk
cycles.]

## PAGE BLEND CURVE — ENGINE-EXACT (FUN_0077ab7b + powf 0x423c2b)
  t = clamp(t, 0, 1)
  v = powf(t, curve_offset)            # m_ncurveoffset (default 1.0)
  if v <= 0.5:  b = powf(2*v,   hardness) * 0.5
  else:         b = 1 - powf(2 - 2*v, hardness) * 0.5
  # hardness = m_ncurvehardness (default 1.0); defaults => identity (linear)
powf = CRT pow with float32 truncation (fstp dword). Normalized page time via
FUN_0077a4d8 = clamped inverse-lerp (x-a)/(b-a).

## Still unread (SEH gaps, capstone-only): SetupNewPage 0x5b7788,
UpdatePagePlayPos 0x5b56a9 (playpos advance/loop details),
EvaluateTransitions 0x5cbbc2 body (2577B, ghidra part_0021.c:19256).

# 2026-07-09n — INTERPRETER SHIPPED + FILE-HEADER AUDIT

## wlib/anim_state_machine.py (task-3 deliverable)
Engine-faithful state-machine interpreter over extractor fragment JSONs.
load_tree(): rebuilds node tree from nodes_full (logicalParent/siblingOrder;
class from preamble instance strings — NOTE j['nodes'] type list is
misaligned, use instances[0] str_<id>), splices nested StateGroup fragments
via assetName. Interpreter: get_valid_state (0x5f076f round-robin),
get_valid_transition (0x5c6140 order incl. group-target recursion +
fallback), transit (0x5b4a31 ease-in/playpos overrides + supersync marker
remap), tick (advance/loop playpos, ancestor-chain transition tests,
one-frame event clear), slot_weights (page crossfade stack, engine-exact
blend curve, m_nweight x blend m_nweight). CLI: --list / simulation trace.
Unit checks: curve identity at defaults, hardness=2 t=.25 -> .125, sync
remap piecewise. Validated on Enemy01 + Rorschach classes end-to-end.
CAVEATS (documented approximations): transition from-filter word
[T rec+0xc] not implemented (unnamed props 0x381c10c0/0x1d3171a6/
0x52340773/0x5234171b on transitions — candidates); overlay-playpos
criteria (7/8) need overlay pages; page stack capped at 8.
[corrected 2026-10-02: there is no from-filter (the word at +0xc is
m_tfallback; the four unnamed props are the runtime marker cache), and
SetupNewPage has no page cap. The interpreter was rewritten in 1.3.0.]

## Header audit results (corpus scans)
.animation (1185 files): FULLY EXPLAINED.
  [f32 keyRate][f32 dur][u32 0 (all)][u32 keyCount][u32 frs in {1:71,2:354,
  3:760}][u32 0][u8 1][u32 nameCount][names][tracks t in {0,1,2,3}]
  [u8 0 terminator]. keyRate==(kc-1)/dur exact 1185/1185. Leftover: 1 byte
  (the terminator) on every file. Type-3 tracks: pos is f32x3 + 4 PAD bytes
  (0 in 10705/11125; 17 junk values repeated across files = baker
  uninitialized memory, NOT data).
.block_h_z (35 files = 7 levels x5): entry field `unknown_after_sizes` is
  the ASSET-TYPE kapow_hash: sound 0x80aa346d, Texture 0x7d8d9a63,
  animation 0x45870ad6, fragment 0xa048cb21, modelRes 0xf2e47acb,
  PropertySequenceAsset 0x5cf8a3cf, ParticleSystemAsset 0x46b6f587,
  grass 0x86a9d7dd, mediastream 0xe1faf50f, DetailMeshAsset 0xdeb3f74e;
  UNRESOLVED names: 0x41764525 (models, skinned?), 0x96ea413f (bmps).
  Meta@327: u8=2, u32 0x593F430A magic, tables_size, unk1 (varies ~2-19k),
  unk2 (varies ~0.3-1.4M), unk3 = header filesize-8, u32 8, num_tables,
  unk5 {0,1,14}, unk6 = COUNT OF FLAG>0 ENTRIES (verified bordello 581).
  OPEN: unk1, unk2, unk5. entry flag: 0=header-only, 1=has 6 stream chunks.
  [corrected 2026-10-02: 0x41764525 = ModelEffects(ModelRes), 0x96ea413f =
  TextureEffects(Texture); the hash folds bytes with & 0xDF, which is why a
  brute force with upper() failed. The fixed header is 400 bytes: unk1 =
  header-blob size of entry 0, unk2 = I/O buffer size, unk3 = offset of the
  trailing 8-byte blob, unk5 = number of localized records, unk6 = number of
  records with a stream. The flag is the LAST field of a record and belongs to
  that record. Table in "2026-10-02 (later)".]
.fragment: reg_dump prop hashes resolve 250 distinct key_XXXX (=56% of all
  339,574 unresolved prop instances; mapping written to
  prop_names_from_reg.json — feed into kapow_fragment key
  dict). Remaining unresolved keys are mostly small-int creation-record
  keys (key_00000000/2/6/7), different keyspace. Type guesses 'raw4?' etc.
  remain heuristic (seen: sync marker 8 local misread as vector?).
  [corrected 2026-10-02: the "small-int creation-record keys" were type
  records, FFFFFFFF + nodeId + word count + TypeName, read as properties; they
  are not a keyspace. With the hash fold, the built-in property types and
  type-record handling, 22 unknown-key occurrences remain corpus-wide.]
modelsk: NOT AUDITED this session (skeleton ModelRes headers not staged in
  sandbox; fem_modelsk.bin is the 32B-record live dump, no name records).
  PLAN: stage the 7 skeleton headers, then per record measure bytes between
  [u8][u32 par+1][u32 1] prefix and first 28B transform + post-tail.

# 2026-07-09p — FORMAT-GAP CLOSURE SESSION (all parsers audited)

## .model node AUX region (Node::Deserialize 0x545927 — SEH gap, capstone)
Region between a node's name and the next node's transform:
  [u32 f1=0][u32 parent][u32 cnt34]{cnt34 x u32 innerCnt}[u32 cnt40][u8 0]
  [u32 njoint]{njoint x 48B+blob}[u32 0][u32 0]
Joint item: [u32 type 4/5/6/7][u32 0][f32 pos x3][f32 quat x4 xyzw]
  [f32 a][f32 a'][u32 blobLen][blob]  — file-side EmbeddedJointNodes
  (jiggle/ragdoll). type7 blob=0 (508/508); type6 (UpperArm/Head twist)
  blob=7B; type4/5 blob layout OPEN. a~a' = limit angle pair (unconfirmed).
innerCnt>0 / cnt40>0 only on MESH nodes: inner item 0x2c =
  [str][u32 n][n ids][u8][u8][u32][u8] (material/palette binding);
  cnt40 items = meshbuffer descriptors ([vec3 bbox x2][u8 hasBuf][deep]) —
  functionally covered by existing extractor heuristics, not re-tiled.
Corpus: 5217 node regions, exact tiling 1742 (all joint-only nodes);
7/7 character skeletons 100%. wlib/parse_model_nodes.py:parse_node_aux().
NOTE skeleton_records.py is the OLD off-by-one parser (transform belongs to
FOLLOWING name) — keep only for reference.
[corrected 2026-10-02: these records are the node's COLLISION VOLUMES, not
joints. A node has two volume lists (one per PhysX scene) and a third list, so
the trailing two zero dwords are the second and third list's counts. Types: 2
concave mesh, 4 convex mesh, 5 box (52 B), 6 sphere (44 B), 7 capsule (48 B).
A capsule is type, base, diameter, height, pos x3, quat x4: "a, a'" are not
limit angles, and the old "pos" was (diameter, height, x). The blob is a
cooked PhysX mesh and exists only for types 2 and 4. skeleton_records.py now
holds the volume parser (parse_node_tail).]

## .pb (kapow_props) — CLOSED
File prefix (the nskip dwords) = [u32 bankId (sequential 0x16269ef8..fa)]
[u32 0x2964 version][u32 nblocks-1]. Zero trailing bytes on all 3 files.

## .sequence — header CLOSED
[f32 DURATION seconds (was mislabeled version; 0.3..60.0)][u32 flags 0/1/4]
[u32 nobjects (verified vs parse on 193/194 files)]. Object header pad
between path and classname = always 8 zero bytes. OPEN: flags semantics,
key tangent dwords (kept raw), parser misses 1 object in 15 files (resync).
[corrected 2026-10-02: the "8 zero bytes" are a u32 flag and a u32 id count of
0; an object can have a path and ids. The tangent dwords are per-key spline
handles (inT, inV, outT, outV per component) on number / vector / quaternion
tracks. The 15 missed objects are parsed since 1.3.0. Still not established:
the header flags and the object flag.]

## block_h_z / block_s_z — CLOSED (see KAPOW_NAZ_FORMAT.md, amended)
Meta @327 fully mapped: firstBlobSize, maxBlobSize (decomp buffer),
fileSize-8, numLocaleExtra (appended localization records: watchmenpart2 has
14 _uk textRes entries, mainmenu 1 logo bmp), numFlagged. Header file tail =
8 zero bytes. block_s_z = pure stream pool, zero head/tail (6/7 exact;
mainmenu has 109KB past last ref = other-language logo streams, zlib blobs
of identical 174800B decompressed). textRes hash = 0x7d6d720b.
Asset-type hashes: 2 still unnamed — 0x41764525 (model subtype: doors/
rubble/carpets/leaves) and 0x96ea413f (bmp subtype: terrain detail/decals);
no code refs (hashes computed at runtime), names not in exe strings,
suffix/prefix brute over 45k exe words failed. Semantics classified.
[corrected 2026-10-02: named: ModelEffects(ModelRes) and
TextureEffects(Texture). "fileSize-8" is the offset of the trailing 8-byte
"loadblock fragment" blob; the numLocaleExtra records sit behind a
per-language seek (u32 x6 @364); the six slots of a record are languages, not
platforms.]

## fragment key dict — no merge needed
All 429 caption-recoverable m_* names were ALREADY in kapow_fragment_keys
keytable (4564 entries). Sync-marker true names NOT brute-recoverable
(hash pairs 0xee2a40XX/0x4cadfbXX differ per digit); keep key_XXXX +
prop_names_from_reg.json side lookup (hash->class/caption/
default for all 3602 registered props).
[corrected 2026-10-02: recovered. The names are m_nsupersynclocal1..8 /
m_nsupersyncremote1..8; the per-digit pattern is the & 0xDF fold. 480 keytable
entries with digits in their names were filed under the wrong hash. 3695
distinct property hashes are registered, all named.]

## FORMAT SCOREBOARD after this session
CLOSED: .animation, .pb, block_h_z, block_s_z, .naz (modified ZIP,
round-trips), .sequence header/object framing.
NEAR: .fragment (lossless, 56% unknown-key instances explainable via reg
dump), .model nodes (exact for joint-only; mesh tails identified).
OPEN (bounded): joint type4/5 blobs, meshbuffer internals, .sequence flags +
tangent dwords, 2 asset-type hash names, block_h_z magic 0x593F430A meaning.
[closed 2026-10-02: all five, see "2026-10-02 (later)". 0x593F430A is inferred
to be the block version signature; the loader never checks it.]

# 2026-07-09q — exe constants promoted into wlib
Policy (user): exe-derived constants are legitimate library data. Added
wlib/engine_schema.py + wlib/reg_dump.json + wlib/prop_names_from_reg.json:
defaults(class) (fragments omit default-valued props!), prop_info/caption
for unresolved key_XXXX hashes, BASE_FPS. the registration scanner lives in wlib/gen_data.py as the
regenerator. Interpreter fallback defaults in anim_state_machine were
checked against registered defaults (match); future props should use
engine_schema.defaults().
FILE-ONLY REMAINDER after this: (1) jiggle/ragdoll MOTION — all params now
file-side (fragment springs + .model EmbeddedJointNodes), needs an NxD6
swing-soft-limit integrator in wlib to retire capture-fit jiggle_params.npz;
(2) grip/face/layer heuristics — retire via interpreter after from-filter +
overlay pages + capture validation; (3) irreducible: runtime criteria inputs
(simulate only), synth blink (invention, keep labeled).

# 2026-07-12 — JIGGLE D6 INTEGRATOR SHIPPED (wlib/jiggle_d6.py)

## Open details from the handoff — ALL CLOSED (capstone via exe_dis.py)
- MockupBox: 3 size props set to f32 0.1 (@0x9e664c) in setup FUN_006574cd;
  RigidBody::SetMass = FUN_004fe514 (stores [body+0xa0], virtual +0xb4;
  arg<=0 falls back to 0.1) called with 0.1 -> mass = 0.1.  Box prop hashes
  0x33aba79c/0x7801dabd/0xdaec7a56 (sizes), 0x61f13948/0x2708acba (generic
  node bools, set 1 after config); MockupBox class NOT in reg_dump (kernel
  registration path), created by name via 0x47bc97.
  [corrected 2026-10-02: 0.1 is the size of the ANCHOR box. The simulated
  body's three size props are 0.8 (f32 @0xa06d84); its mass is 0.1. SetMass is
  "argument if above a threshold, else 0.1".]
- Gravity: PhysicsWorld ctor FUN_0050d1e1 inits (0, -9.82, 0) (f32 @0xa26418,
  only code ref 0x50d214) — but GameEssentials.fragment PhysicsWorld node
  OVERRIDES: gravity=(0,-14.82,0), physicsIntegrationRateInHz=60,
  maxPhysicsIntegrationTimesteps=3.  All file-side.
- PhysicsWorld reg defaults (0x7ebb10..): k=1000 d=0.5 limits 0.08/0.1 —
  fragment overrides to breast 200/0.8/0.08, belly 70/0.8/0.1, hair
  100/0.8/0.3 (matches 2026-07-09c).
- Distance-limit clamp (update FUN_006563a0, per-record ebx): limit [ebx+4];
  delta = bodyPos-anchor -> [ebx+0x60], len -> [+0x6c]; if len>limit:
  t=limit/len [+0x70], pos = anchor+delta*t AND curQuat [ebx+0x18] =
  slerp(anchorQuat [ebx+0x50], curQuat, t) via FUN_0041fd54 (verified slerp:
  dot, shortest-path flip, sin weights).  Setup binds Spine2->BreastL/R,
  Spine->JiggleBelly by name string.

## Decoded dynamics (capture-fit AR(2) as cross-check)
Effective: x'' = -K x - D x' + r x f - alpha_parent   (rotvec dev, parent frm)
- r x f coupling (unit-inertia torque; NOT (rhat x f)/|r|): pinned by fitted
  C force-block magnitude ~|r|~0.35; engine RigidBody exposes
  GetUnitInertiaTensorMSG.  Fitted C alpha-diag ~ -1 pins -alpha term.
- DISCRETIZATION DECODED: implicit soft-constraint softening
  k_eff = k/(1+d*dts+k*dts^2), d_eff = d/(same), d=2*zeta*sqrt(k), dts=1/120
  (60Hz frame, 2 solver substeps): k=200,zeta=0.8 -> k_eff=166.3, d_eff=18.8
  = capture-fit AR(2) values (166-170 / 17.9-19.4) DEAD CENTER.
  (At dts=1/60: 139.6/15.8 — rejected by fit.)
- Static gravity sag engine-exact: idle d6 1.6-1.7deg vs AR2 1.3-1.4.
[corrected 2026-10-02: both points withdrawn. The dts = 1/120 match assumed a
30 fps capture; the PhysX step is 1/60 s and the capture runs at about 55 fps.
The game cancels gravity on the jiggle bodies every frame (ApplyForce(-m*g),
0x656fb4), so there is no static sag; the capture's mean deviation is zero.]

## Deliverable
wlib/jiggle_d6.py — apply_jiggle(P,fps,bind, mode='engine'|'ratio'|'absolute',
props=, extract_root=), same interface as jiggle_pass; reads PhysicsWorld
props from GameEssentials.fragment.json, geometry from bind npz (r=tb[bone]),
sim at 60Hz, engine radial clamp (replaces tanh).  Validation:
the jiggle validation harness.
[corrected 2026-10-02: r = tb is the bone's position from the model origin
(0.346 m for the breasts). The engine's lever is the parent->bone offset
(0.132 m), and its clamp is on the bone-origin displacement in metres, not on
the angle. This model is kept as jiggle_d6 model='pinned'.]
GOTCHA FIXED: derivatives must be taken on the ORIGINAL clip grid then
resampled — upsampling first turns linear-interp knots into accel impulses
(20 m/s^2 spikes at idle, pinned sim at the clamp).

## OPEN: dynamic amplitude factor ~1.7
d6(engine, gain=1) is x1.7 below AR2+gain on run/dance dynamics while statics
match.  AR2's own fitted gain=1.4 is inside that reference (provenance of the
1.4 unknown — fit script not preserved).  x2 visual double-cover (quat-imag
construction) matches dynamics but doubles statics -> rejected.  Candidates:
damping lower at resonance than implicit model predicts, regression shrinkage
in the AR(2) fit (gain compensating), capture overlay content.  DECIDER:
raw-capture window comparison — dominatrix_capture/ALL_deduped_palettes.npy
+ clip alignment (the clip-alignment oracle needs rebuilding via
collect_dump_palettes/oracle_setup).  Until then bakes should keep jiggle_pass
(capture-grade) as default; jiggle_d6 is the file-only fallback candidate to
replace the _engine_ar2 fresh-install path in jiggle_pass (strictly better:
exact constants, exact clamp, 60Hz grid).

# NEXT SESSION HANDOFF (2026-07-12 close)
1. Jiggle amplitude decider (above): rebuild capture-clip alignment, compare
   BreastL/R traces run_cycle/idle windows vs jiggle_d6 modes; if a clean
   factor emerges, promote jiggle_d6 to default in variant_glb (--jiggle).
2. Swap jiggle_pass fresh-install fallback to call jiggle_d6 (strictly
   better than _engine_ar2 path) — small, safe.
3. Prior open items unchanged: interpreter from-filter/overlay pages,
   joint type4/5 blobs, meshbuffer internals, .sequence flags, 2 asset-type
   hash names, magic 0x593F430A.

# 2026-07-12b — STATIC-ANALYSIS SWEEP (remaining gaps read)

## Jiggle update FUN_006563a0 — FULLY READ (box->bone conversion)
The big per-frame addon fn has three phases:
1. 0x6563a0-0x6567bc: show/hide pass. Walks child boxes, sets visibility via
   virtual dispatch (0x51ac25 setVisible / 0x512aaa / 0x51544f) by node type
   (0x4985f1/0x4cda0a/0x4f51d0 typechecks). Boxes hidden unless [world+0x6c]
   flag in {0,2}. Not dynamics.
2. 0x6567c0-0x656865: fetch character root / fallback bone (0x493a64,
   [0xe14324]+0x2a4). Sets up frame.
3. 0x65686a-0x6574ae: PER-BOX dynamics writeback. Reads box world pos [box+0xa4]
   and quat [box+0xb8] (PhysX body transform), computes delta vs the bone
   anchor, sqrt-normalizes (the "Invalid Sqrt argument" guards), applies the
   distance clamp (limit at [box+0xc], slot 9/12/15 copied in setup), and
   writes the result back to the bone palette slot. Box orientation maps
   DIRECTLY to bone rotation (quat delta), NO extra amplitude gain in this fn.
=> Confirms the x1.7 run/dance gap is NOT in the game-side writeback; it is
   either PhysX solver response (box inertia/lever, closed DLL) or the AR(2)
   fit's gain=1.4. jiggle_d6's r x f coupling + solver_soften remains the
   file-only best; decider still = raw-capture window compare.
[corrected 2026-10-02: the writeback replaces the bone's local POSITION AND
ROTATION with the body's pose relative to the anchor box (no gain: confirmed).
The clamp is on |pos - animated pos|, the rotation slerped by the same ratio.
The same function applies the anti-gravity force (0x656fb4-0x65707c), which
this read missed.]

## PhysX soft-limit spring apply FUN_0095abb0/0x95ac50 (found via [d6+0x100]
## /[+0x120] field scan) — this is the DLL-side integrator glimpse
NxD6 swing soft-limit: reads Swing1LimitSpring[+0x100]/Swing2[+0x120],
damping[+0x108]/[+0x128], computes swing error (limit value - current),
tau = spring*err (+ damping*vel), sqrt for angle magnitude, x1.5 const
@0x9e8320 (restitution/Baumgarte factor), integrates into [+0x19c]/[+0x1a0]
/[+0x1a4] accumulators scaled by dt [slot+0x58]. Confirms absolute
torque-domain spring with a 1.5 stabilization factor. (Full solver is in
PhysXCore.dll; this is the game's thin Nx wrapper.)

## Transition from-filter (0x381c10c0/0x1d3171a6/0x52340773/0x5234171b +
## 0xdfc5d866) — CLOSED, NOT NEEDED
All 5 register at 0x60d759-0x60d7bd with EMPTY default, null caption, type 3
(hidden). Corpus scan: across ALL 2459 shipped {trans to *} nodes, NONE of
these 5 keys is ever present (all default) => editor/tooling-only fields.
GetValidStateGroupTransition 0x5c6140 confirms the runtime from-filter is
STRUCTURAL: [transNode+0x10]+0xc compared to [args+0x10] (current), i.e. the
transition list's owning state IS the "from". anim_state_machine.py already
models this (transitions belong to their state). => interpreter caveat about
from-filter is RETIRED; no code change needed.
(Sync markers key_ee2a40XX/key_4cadfbXX default -1.0 = unused; the
"vector? [-1, 9.1e7, -1]" on marker 8 is the known 3-float misread, harmless.)
[corrected 2026-10-02: 0x381c10c0 / 0x1d3171a6 / 0x52340773 / 0x5234171b are
m_nsupersynclocal / m_nsupersyncremote (the sorted marker lists) and
m_nsupersyncmin / m_nsupersyncmax, rebuilt at init by UpdateSuperSync 0x5fa582
and therefore never stored; 0xdfc5d866 is m_eeventlist. The word compared at
transition record +0xc is m_tfallback against the pass flag, not a
from-filter.]

## TransitionMet FUN_005c5ea4 — READ
Confirms method: gates on target-state flags (rec+0x54 enabled, rec+0x40 bit0),
optional PLAY_POS window check ([edi+0x6c]/[edi+0x70] = lo/hi play-pos bounds
vs current normalized pos [state+0x10]), then evaluates the criteria LIST via
per-criterion method [class+0xc]+0x24 through thunk 0x479874 (ctx global
0xe12d9c). Returns 1 only if all pass. Matches interpreter's transit_met.
[corrected 2026-10-02: the "PLAY_POS window" is the sync-marker range: with
"Sync PlayPos?" set, the transition can fire only while m_nsupersyncmin <=
playpos <= m_nsupersyncmax. The +0x54 / +0x40 flags are entity fields. The
interpreter had no such gate until 1.3.0.]

## SEH gaps read (capstone): playpos + page setup
UpdatePagePlayPos 0x5b56a9: playpos advance = state.playpos += ctrl.dt
([ctrl+0x74]); per-slot rate = [slot+0x14] (m_nspeed) * dt + [slot+0x10]
offset; loop length from anim resource duration [res+0x130] (or getter
0x591920); wrap when normalized pos >= 1.0 (fld1;fcomp). Matches interpreter.
SetupNewPage 0x5b7788: allocates+zeroes a page struct (rep stosd), pushes it
(0x50030f), copies the entry state's slot set iterating [rec+0x14]/[rec+0x1c].
Matches interpreter's page stack.
=> Both SEH state-machine functions confirm anim_state_machine.py; no change.
[corrected 2026-10-02: this read was too coarse and the conclusion is
withdrawn. Page +0x14 is a RATE, rebuilt every frame from the first layer's
slots; playpos += min(rate, 6.6) x dt; wrap while playpos > 1.0 (strict).
SetupNewPage also handles same-state and re-entry, the ease-in rule, layer
variants and events. docs/re/pages.md lists 16 differences from the
interpreter of that time.]

## Format residue — CHARACTERIZED (low value, not blocking)
- EmbeddedJointNode joint types: clean parse_node_aux tiling across all 7
  skeletons yields ONLY type 7 (88 records, blob=0) = the jiggle/twist anchors
  (SOLVED). Types 4/5/6 seen only in a permissive raw scan that is dominated
  by false positives (the "blobs" decode to mesh material-binding "ObjectNN"
  records, i.e. tag collisions). Genuine type 4/5/6 are ragdoll constraint
  joints in a handful of props/models -> NOT part of clip playback (ragdoll =
  runtime PhysX death), NOT worth reversing for the file-only anim pipeline.
  [corrected 2026-10-02: there are no joints here. 7 = capsule, 6 = sphere, 5
  = box, 4 = convex mesh, 2 = concave mesh: collision volumes. Types 4 and 5
  are genuine (17 convex meshes, 123 boxes in the PC corpus), not false
  positives.]
- .sequence flags{0,1,4}: deserialize is a ctor chain (0x543729->0x550905->...)
  not a single readable header parse; flags select a runtime playback mode
  (loop/override), a RUNTIME concern. decode_sequence.py already keeps them raw
  + parses tracks losslessly. No decode blocker.
  [corrected 2026-10-02: the readers were read (asset FUN_0054558c, track
  FUN_005415bf, keys FUN_00547f4c / FUN_00547fdb). The old parser was not
  lossless: it missed 15 objects on Part 2 PC.]
- block_h_z magic 0x593F430A: NOT a literal immediate anywhere in the exe and
  no code ref -> stamped/computed at build, never compared at load (like the
  runtime-computed asset-type hashes). It is a version/format stamp, not a
  validated signature; nothing more to recover statically.

## STATIC-ANALYSIS STATUS: effectively CLOSED
Every reachable exe gap on the animation/jiggle/state-machine/format path has
been read. Remaining unknowns are either in closed NVIDIA DLLs (PhysX solver
exact response -> the jiggle amplitude factor) or genuinely absent from the exe
(build stamp). The only OPEN decidable item is data-side: the jiggle amplitude
factor, settled by raw-capture window comparison, not by more disassembly.
[corrected 2026-10-02: not closed. The 2026-10-02 pass re-read page setup,
play position, events, placement, the jiggle setup and every file loader, and
changed conclusions above in each of those areas.]

# 2026-07-12c — PhysX 2.8 DOC MINED (PhysXDocumentation.pdf, workspace root)
Text dump: pypdfium2 -> /tmp/physxdoc.txt (554 pp). Key confirmations + finds:
- "Joint springs are implicitly integrated within the solver" (Solver Accuracy
  Tips) => direct doc backing for jiggle_d6.solver_soften.
- setTiming(maxTimestep=1/60, maxIter=8, NX_TIMESTEP_FIXED) defaults; game
  sets rate 60 / maxIter 3. Substep = maxTimestep (doc); our empirical
  dts=1/120 softening fit stays an EFFECTIVE description.
  [corrected 2026-10-02: withdrawn, see the 07-12 note. The exe steps PhysX at
  1/60 s, up to 3 steps per frame, with 4 solver iterations per body.]
- NX_MAX_ANGULAR_VELOCITY = 7 rad/s body default (not binding at jiggle
  amplitudes ~1.8 rad/s peak). solverIterationCount default 4 per body.
- ANGULAR LIMIT GEOMETRY (the big one): swing1+swing2 limited = ELLIPTIC CONE
  around the parent-frame twist axis; doc explicitly warns that one angle <<
  the other gives a degenerate eccentric cone. Watchmen uses Swing1=45deg,
  Swing2=0 => planar WEDGE: deviation along swing2 axis is ALWAYS spring-
  restored (soft, k/d), deviation along swing1 is FREE up to 45deg.
  => ENGINE JIGGLE IS ANISOTROPIC. Corroboration in the capture-fit AR(2):
  C force-block MIDDLE ROW ~20x weaker than rows 0/2 (one axis barely
  force-driven) — previously unexplained.  NEW amplitude hypothesis: the
  isotropic spring in jiggle_d6 over-restrains the engine's free axis =>
  the x1.7 dynamic under-response. Anisotropic mode is now the top next step
  (spring K only on swing2 component, swing1 free within 45deg, distance
  clamp unchanged).

# 2026-07-12c — EmbeddedJointNode FIELD-ORDER FIX (parse_node_aux)
True joint record layout: [u32 type][u32 0][f32 pos x3][f32 a][f32 a']
[f32 quat x4 XYZW][u32 blobLen][blob] — the two scalars come BEFORE the quat
(old parser had them after => "non-unit quats"). Proof: |q|^2 = 1.0000 on all
24 female-skeleton joints after the swap. wlib/parse_model_nodes.py FIXED.
Breast pair on Spine2: SAME anchor pos (0.143,0.243,-0.189 model space),
mirrored frames: twist X = +-(0.939,0.331,-0.096) (outward along breast),
swing1 Y ~ (−0.342,±0.931,∓0.131), swing2 Z ~ (±0.046,0.156,0.987).
a scalar mirrored (−0.0953/+0.0963) — candidate: lateral anchor offset or
limit skew (OPEN, small).  These frames are the file-side swing axes needed
for the anisotropic jiggle mode.
[corrected 2026-10-02: this is a collision capsule: type, base, diameter,
height, pos x3, quat x4. The "breast pair on Spine2" is a capsule of diameter
0.1429, height 0.2428 at local position (-0.1887, -/+0.0953, 0.0237). The
quaternions are the capsules' orientations, not swing axes; the jiggle joint's
swing axes are the parent bone's Y and Z.]

# NEXT SESSION HANDOFF (2026-07-12c close, supersedes 07-12 close)
1. ANISOTROPIC jiggle_d6 mode: project deviation onto joint-frame swing axes
   (parse_node_aux type-7 quats, now correct); spring+damp K,D on swing2
   component only; swing1 free (limit 45deg, rarely hit under distance clamp);
   validate vs AR(2) + captures. This may close the x1.7 amplitude gap.
2. Raw-capture window compare (rebuild the alignment oracle) — final
   arbiter for amplitude + anisotropy.
3. Then: promote winner into variant_glb --jiggle; swap jiggle_pass fresh-
   install fallback to jiggle_d6.
4. Unchanged: overlay pages + capture validation for interpreter; PhysXCore
   DLL disasm only if 1+2 leave residue.

# 2026-07-12d — ANISOTROPIC WEDGE: TESTED AND REJECTED (validates iso model)
Implemented mode='aniso' in wlib/jiggle_d6.py (engine constants + spring only
on one swing axis, other free to 45deg, free_damp=0.05, axes from the fixed
EmbeddedJointNode frames).  RESULT: REJECTED — with the breast rest direction
pointing up-ish, ANY force-free swing axis is an inverted pendulum: idle
drifts to the distance clamp (~10deg) under gravity for BOTH possible axis
assignments (spring-on-Z AND spring-on-Y), vs capture 1.4deg.  Run/dance rms
vs AR2 also worse (10.6-13.2 vs iso 4.6-6.5).
INTERPRETATION (consistent with the PhysX doc's eccentric-cone warning): with
Swing2LimitValue=0 the elliptic swing cone degenerates such that the SINGLE
combined swing constraint is violated by any swing direction outside a
measure-zero sliver => restoring is effectively ISOTROPIC = 'engine' mode.
BONUS RESOLUTION: the capture-fit AR(2) C-matrix weak MIDDLE row is the
LOCKED TWIST DOF: parent-local rhat = t̂b = (-0.27, 0.94, 0.19) is Y-dominated,
so deviation component 1 ~ twist about the lever = locked/weak.  Anisotropy
anomaly explained WITHOUT a free swing axis.
MECHANICAL FINDS THAT STAND: parse_node_aux field-order fix (a,a' BEFORE
quat); mirrored-side joint frames = SAME record with CONJUGATED quat (matcher
in joint_frames() tries both); jointframes cache bumped to v2 (v1 file has
pre-fix frames and the mount won't delete it — ignore it).
AMPLITUDE x1.7: unchanged verdict — solver response scale / AR2 gain
provenance; decider = raw-capture window compare (handoff item 2 -> now 1).

# 2026-07-12e — RAW-CAPTURE VERDICT: jiggle_d6 AT CAPTURE PARITY, PROMOTED
Method (no oracle rebuild needed): dominatrix_capture/ALL_deduped_palettes.npy
(14587x48x3x4) is ~6 nightclub dancers INTERLEAVED (lag-6 anchor
autocorrelation); greedy nearest-neighbor anchor tracker (<0.06m/frame,
gap<=12) -> 26 tracks >=150 samples -> 46 uniform segments (stream-gap 3..9).
Slot order: palettes are BIND-BONE ORDER (direct; rot-by-one gives garbage).
Deviation extraction: bind cancels -> dev = angle(P_breast . P_parent^T);
baked clips have ZERO authored breast anim, so capture dev = pure engine
jiggle, like-for-like with model devs.

## Capture regression (x[t+1]=a x[t]+b x[t-1]+g_grav.. per-term, clamp-free,
## 37k rows pooled BreastL/R, one-step R2=0.88)
- h_alpha = 0.98 (pooled) — the -alpha_parent drive coupling is EXACTLY 1.
- g_grav = -0.01 — GRAVITY DOES NOT COUPLE. Box is anchored AT ITS CoM
  (translation-locked at CoM => no lever torque from gravity or anchor accel;
  the r x f coupling in jiggle_d6 'engine' mode is a small mis-model that
  mostly cancels — keep, harmless, but the true drive is rotational).
- g_acc = 0.4-0.5 residual inertial coupling (small anchor-CoM offset, cf.
  joint-record a' ~ 0.024).
- PER-AXIS: parent-X K~6 (FREE!), D~40; parent-Z K~146.5 D~10.7; parent-Y
  (r-hat/twist) locked/no signal.  THE WEDGE ANISOTROPY IS REAL — the
  2026-07-12d rejection was an artifact of the wrong (gravity-lever) drive:
  with g_grav=0 a free-but-damped axis does NOT topple.  The file joint-frame
  sw1 axis (0.939,+-0.34,..) = parent-X matches the free axis exactly.

## Amplitude verdict (dance segments, mean dev deg)
capture 3.1-3.8 | jiggle_d6 'engine' 2.60-2.70 (-22%) | AR2+gain 4.3-4.5 (+29%)
idle: engine-true ~1.4 | d6 1.64 | AR2 1.36.
=> The old "x1.7 gap" was measured against AR2+gain, NOT capture; AR2's
fitted gain=1.4 compensated its mis-modeled gravity drive and OVERSHOOTS
capture.  jiggle_d6 'engine' meets the success criterion ("matches capture
at least as well as AR(2)").
Free-run trace R2 (46 segments): aniso-empirical 0.23 > file-aniso 0.10 >
iso 0.06 — anisotropic + alpha-drive is the better MODEL SHAPE but needs
per-axis constants not yet derivable from file values; parked as optional
polish (constants recorded above).
[corrected 2026-10-02: re-measured for 1.3.0. ALL_deduped is the fight
capture, not nightclub dancers (the dancers do not jiggle at all: breast
palette == Spine2 palette). The capture runs at about 55 fps, not 30, which
scales K by (55/30)^2 and D by 55/30. Taken relative to the parent pose of the
PREVIOUS frame, X is the locked twist axis (0.45 deg rms) and the two swing
axes respond alike (breast K about 570, D about 37.5), so the per-axis figures
and the "wedge anisotropy" above are withdrawn. g_grav = 0 stands; the cause
is the per-frame anti-gravity force, not an anchor at the centre of mass.]

## PROMOTED (2026-07-12e)
- wlib/variant_glb.py --jiggle now uses jiggle_d6 (AR2 import kept in comment).
- wlib/jiggle_pass.py fresh-install fallback (no jiggle_params.npz) now
  delegates to jiggle_d6 (retires _engine_ar2 approximation path).
- Existing capture-fit npz path in jiggle_pass unchanged (legacy/comparison).

# NEXT SESSION HANDOFF (2026-07-12e close, supersedes 07-12c)
1. OPTIONAL polish: anisotropic capture-informed mode (axes file-side, per-axis
   K/D above, drive = -alpha + 0.45*r x (-acc), NO gravity) — improves trace
   R2 4x; decide if visual difference in glbs justifies non-file constants.
2. Belly validation: same tracker on gimp_captured_palettes_t2.npy (JiggleBelly).
3. Interpreter: overlay pages + capture validation (unchanged).
4. Rebake QA glbs if 1 lands.

# 2026-07-12f — DRIVE-VARIANT SWEEP + BELLY CHECK (closes the calibration loop)
Belly (gimp_captured_palettes_t2.npy, single-track, slot order = bind order,
zero offset): capture JiggleBelly dev overall 0.88deg, low-motion 0.31,
high-motion 1.18.  d6 'engine' on gimp clips: idle_fidget_J 3.18 /
strafe_left 2.53 / freight_train 3.91 => OVERSHOOTS belly ~2.5-3x (absolute
error ~1.5-2.7deg; visually minor on a lumbering gimp).
Capture-truth drive variant (-alpha + ga*r x (-acc), NO gravity; ga swept
0/0.45/1): breasts dance 1.9-2.1 (WORSE than engine 2.65 vs capture 3.4),
idle 0.5 (worse), belly ~unchanged 1.75/2.93.  ga has almost no effect at
clip levers.  INTERPRETATION: baked isolated clips lack the motion content
(state transitions, contacts, root translation) that drives capture jiggle;
the r x f term in 'engine' mode, while not the engine's true coupling
(capture: g_grav=0), acts as a serviceable proxy on isolated clips.
DECISION: keep 'engine' mode as the promoted default (best overall measured:
breasts -22%, idle close, belly +2.5x on small absolutes).  The truer
alpha-driven anisotropic model only pays off with full state-machine-driven
motion — revisit IF/WHEN interpreter-driven bakes exist (overlay pages task).
[corrected 2026-10-02: the model described here is jiggle_d6 model='pinned',
still the default; model='pivot' (mode='capture') follows the engine geometry
and is opt-in because its swing constants are capture-fitted.]
Scoreboard (mean dev deg, capture reference):
  breast dance : capture 3.1-3.8 | d6-engine 2.65 | AR2+gain 4.4 | alpha-drive 2.0
  breast idle  : engine ~1.4     | d6-engine 1.64 | AR2 1.36    | alpha-drive 0.5
  belly overall: capture 0.88    | d6-engine ~3   | (AR2 reuses breast params)

# 2026-07-13 — OVERLAY PAGES SOLVED + INTERPRETER SHIPPED

## EvaluateTransitions 0x5cbbc2 — READ (ghidra part_0021.c:19263, NOT a stub)
Signature: (ctx, args{out, flag, pagelist}). Called from Update 0x5b4613
(table off 0xac). Cmd hashes resolved: cmd6 0x499d201a=command_get_valid_state,
cmd9 0x7c02ebf4=command_get_valid_transition, cmd8 0x4fdde9d3=
command_Group_criteria_met, cmd11 0x3c01572e=command_get_fallback_state.
- pagelist EMPTY + flag=1: OVERLAY ENTRY. Gate AllowOverlayTransitions
  (0x5aa33d: !ctrl[0xf8] && ctrl[0x158] && (ctrl[0x15c] || classrec[0x70])),
  then scan candidate list: classid 7 (group) -> StateGroupCriteriaMet +
  command_get_valid_state -> SetupNewPage (scan CONTINUES); state ->
  StateCriteriaMet 0x5c647c -> SetupNewPage (scan BREAKS). This is the
  second page-push site the 07-12g handoff predicted.
- pagelist non-empty: top-page transition eval. Wait-for-anim-end gate
  ([top rec+0x58] && playpos<1 -> out=0), get_valid_transition; DEFER
  (out=1) while pagelist blend timer [listrec+0x14] > 0 (decremented in
  Update; writer of the initial value = native transit, unread — modeled as
  top-page ease window); execute = TransitionPlayPos [0xa8] +
  TransitToState [0xb0] + per-slot SendAnimationEvent [0xe0]; no-T path:
  Group_criteria_met/StateCriteriaMet -> stay, else retry w/ arg 1, else
  command_get_fallback_state.
  [corrected 2026-10-02: the timer at listrec+0x14 is a force-stay timer,
  loaded by SetupNewPage from the entered state's m_nforcestaytime and counted
  down only on ticks where a transition is wanted. It is 0 in every shipped
  state, so the engine never defers; the "ease window" model was wrong.]

## TWO page stacks (StateMain 0x5b417b)
StateMain calls Update(0, pagelist[0]) then Update(1, pagelist[ovidx]) —
body pass and OVERLAY pass run the same code. Update order: dt (speed
factors) -> EvaluateTransitions (LAST frame playpos) -> blend timer ->
UpdatePageBlendsFaster per page (slot-mask [rec+0x18] bitmask for slots>9
when [rec+0x14], confirmed) -> DeleteOldPages 0x5b9e4c (drop pages occluded
by a fully-blended page above; drop pages with blend<0) -> SynchronizePages
-> ClearAnimationPosEvents -> UpdatePagePlayPos per page -> CalculateVelocity.

## File-side overlay data
Candidates = class root's 'OverlayStates' folder. Only EN1/EN4 have one
(HeadTurn: additive look-at, MOTION_LAYER_1 3-slot vertical blend on value
18 over [-0.785,0.785]; ACTION_LAYER_1/2 left/right on value 17 over
0..±1.575 via m_ilayerweightctrlparam). Ctrl-param 0 = NONE (UI 'blend on
NONE'). Criteria 7/8 (OVERLAY_PLAY_POS/REVERSE) occur NOWHERE in shipped
fragments (all-data scan) — implemented anyway (read top overlay page
playpos, 09j semantics).
[corrected 2026-10-02: the candidates are the class's override list
(command_add_state 0x5a03a8): each override state, or the outermost state
group that owns it. The folder name plays no part.]

## Interpreter (wlib/anim_state_machine.py) — overlay pages SHIPPED
- Two stacks (pages/opages), tick = body pass then overlay pass (engine
  order: evaluate BEFORE playpos advance), overlay entry per 0x5cbbc2,
  DeleteOldPages occlusion, transition defer during top-page ease window.
- NEW engine-exact weight machinery (retires the layer-weight heuristic):
  blend-position split (m_iblendctrlparam over blend interval, slots at
  m_nparentblendposition, linear between neighbours) + layer weight drive
  (m_ilayerweightctrlparam -> inv_lerp_clamped 0..intervalend). CLI: --value
  idx=float; overlay shown in trace; overlay_weights() API.
- Verified: HeadTurn deadzone gating, look up/down interpolation, left/right
  additive weights (|v|/1.575), body-pass regression vs old interpreter.

## Capture validation (bounded)
- Nightclub dancers are CharacterSimple entities w/ raw AnimSlots — they do
  NOT run the state machine; dancer captures can't validate it. Player (rsh)
  capture is the vehicle.
- rsh clip-ID (parent-relative rotation NN vs all 293 baked clips, bind-bone
  order offset 0): blended frames dominate (median d~2, expected: multi-page
  + layers w/o the input stream); clean single-clip windows lock in tight
  (special_stomp d=0.05, kick 0.16, walk 0.26).
- Playpos advance on the stomp window: 0.3696 clip-frames/capture-frame,
  sub-frame residual, LINEAR -> implied 55Hz ~= 60Hz update minus capture
  drops; matches interpreter dt/dur with header-exact fps. No hidden speed
  multiplier (re-confirms SPEED_MULT retirement at palette level).
- Full env-driven replay (reproduce blended frames) needs the input stream:
  NOT derivable from capture; graph-consistency of observed clip sequences
  is the remaining cheap check if ever needed.

# 2026-07-13b — UNTESTED-SKELETON QA (medium/large/small/bs2/nto): PASSED
- Bind FK spot-check: tb == Rb[par]@tloc + tb[par] EXACT (0 err) all 5;
  Rb orthonormal to 1e-15. Caches complete (222/222/222/190/235 clips), all
  with header-exact fps fields, no NaN.
- Rigidity: world bone lengths constant (rel-std 0.0000) across sampled
  clips, all 5 skeletons.
- Shared EN1 clips give IDENTICAL world motion across medium/large/small
  (same lerp metric values) = retarget path consistent.
- nto vs raw capture (nto_captured_palettes_t1.npy, 63-bone, bind order
  offset 0): clip-ID locks tight windows down to d=0.01
  (NTO_COM_ATT_combo_super_B), jog/run cycles match — palette-level PASS.
  medium/large/small/bs2 have no captures (file-side only, as planned).
- Visual QA glbs in workspace root: QA_SKEL_{medium_Thug, large_ThugBig,
  small_ThugFast, bs2_TwilightLady, nto_NiteOwl}.glb (idle/walk/attack each,
  textured, valid glTF). Eyeball pass = user.
- NOTE (_lerp_err usage): applying it to STORED palettes measures halving
  the stored rate again — bake-time numbers are the valid ones; don't read
  36-51deg on stored 1x caches as failure.

# 2026-07-13c — REBAKE STATUS + SESSION GOTCHAS
- _bake caches from 07-09 verified CURRENT (fresh medium walk_cycle bake is
  bit-identical incl. fps) => full cache delete NOT needed; only glbs were
  stale. REBAKE COMPLETE: all 25 character glbs regenerated ('pending
  bakes: 0'), jiggle verified baked (dance clip breast palette delta 0.13
  vs raw). CORRECT INVOCATION: watchmen.py characters 20260708
  20260708/characters — outdir is the characters/ dir, NOT the extract root
  (wrong outdir silently creates a parallel empty 20260708/_bake and
  rebakes everything into it).
- Sandbox: background processes are reaped between tool calls (setsid/nohup
  do NOT survive) — long jobs must run as FOREGROUND timeout-chunked calls;
  export made chunk-safe: glb writes + bake npz writes now atomic
  (tmp+os.replace), jiggled palettes memoized to _bake/<key>_j/.
- characters_export.py now applies jiggle_d6 to the loaded anims per
  skeleton (per-clip try; skeletons without jiggle bones detected on first
  failure). Was previously CLI-only (variant_glb --jiggle).
- GOTCHAS (new): (1) `pgrep -f "watchmen.py"` SELF-MATCHES through the
  bash -c wrapper — got pids 1/2/5 and `kill $(pgrep ...)` SIGTERM'd the
  shell (exit 143). Use `ps aux | grep -v grep | grep watchmen` or
  pgrep -f "[w]atchmen". (2) rm on the mount fails 'Operation not
  permitted' until the cowork allow-file-delete permission is granted
  (tool: allow_cowork_file_delete) — a silent rm -rf failure left old
  caches in place; CHECK deletions happened. (3) run long jobs with
  setsid nohup python3 -u, poll /tmp/rebake.log.

# 2026-07-13d — USER EYEBALL QA: two mesh-palette bugs found + FIXED
User pass on QA_SKEL_*.glb: medium arms+head off, large arms off, small OK,
nto/bs2 headless (the last two = QA-script-only artifact: the quick QA
builder skipped _face_attach; real character glbs were fine).
ROOT CAUSE (char_lib.load_parts): model palette names absent from the bind
were SILENTLY DROPPED before the rotate-by-one, shifting every later skin
index. medium models say 'RUpArmTwist...' vs bind 'Bip02 RUpArmTwist...'
(4 bones dropped mid-list -> arms AND head mis-skinned; also Heavies);
large models say 'Bip01 Attach RHand' vs bind 'Attach RHand' (shift by 1
from the forearms on). small only dropped junk/trailing names -> looked OK.
FIX: 'BipNN '-prefix-insensitive palette matching (exact match always wins;
control-diff over ALL variants shows exactly Thug/Heavies/ThugBig change,
validated skeletons byte-identical). Thug/Heavies/ThugBig character glbs +
all QA_SKEL glbs regenerated (QA nto/bs2 now include face attach).
LESSON: any dropped MID-LIST palette name is a red flag — assert/log drops
that are not mesh-object junk or trailing 'Interact'.

# 2026-07-13e — EYEBALL ROUND 2: twist-bone bake + NTO cowl ride FIXED
1. Medium elbow twisting = SAME BipNN mismatch on the BAKE side: bake_v4
   matched clip tracks to bind names exactly, so 'RUpArmTwist' tracks never
   hit medium's 'Bip02 RUpArmTwist' slots -> twist locals FROZEN at bindloc
   (0.03deg range vs 71deg on large/small; world variance hid it because
   parents move — palette metrics can't catch a frozen mid-chain local).
   FIX: prefix-insensitive _track() in bake_v4 (exact wins). medium cache
   invalidated + rebaked (fast — caches rebuild in <1 chunk), twist locals
   now 71.45/16.06deg == large/small. Thug/Heavies glbs + QA regenerated.
2. NiteOwl head moving separately = rigid EXTRA_HEADS Head-ride of a cowl
   that carries real Bip01/Neck/clavicle/twist weights. Applied the
   NAME-PROXY RIDE (designed-but-unapplied):
   in _face_attach, when align_ref is None, face-rig slots NOT under Head
   whose names exist in the body bind (NAME_MAP Bip01->Bip) are re-slotted
   to per-body-slot proxy joints (same mechanism as the weight-transfer
   path; write_glb unchanged; proxy_slots now returned unconditionally).
   NTO rides Bip/Neck/2xClavicle/2xUpArmTwist; TwilightLady now also rides
   Bip/Neck (the findings doc predicted this is an improvement — re-eyeball).
   NiteOwl, NiteOwl_Dry, TwilightLady glbs + QA rebuilt; pending bakes: 0.

# 2026-07-13f — GIRAFFE NECK FIXED + FULL FROZEN-STATE AUDIT
User QA round 3: NTO neck stretched in some anims. Cause: name-proxy ride
mapped cowl 'Bip01' -> body 'Bip', but the cowl's Bip01 BIND is 0.34m/122deg
off the body root (the cowl is authored rest-coherent under the single
head-frame M4) — driving those 273 skirt-base verts with the body-root
palette slung them around the root whenever it moved vs the head = giraffe.
FIX: ALIGNMENT GATE in _face_attach — only proxy face bones whose bind
agrees with the body bind under M4 (2cm/5deg); misaligned ones keep the
anchor ride. Plus per-bone proxy_align (B_body@inv(B_face)) threaded through
write_glb (exact for aligned bones; degenerates to M4). TL's Bip01 (0.29m/
123deg, weightless) also gated. NTO/NTO_Dry/TL glbs + QA rebuilt.

## Frozen-state audit (glb pipeline, user request) — CLEAN
1. Bake track coverage: every bind bone of all 8 skeletons receives clip
   tracks (canon-matched) EXCEPT gimp JiggleBelly = by design (physics bone,
   driven by jiggle_d6 at glb time, verified active).
2. Mesh palettes: zero remaining mid-list drops across every character
   variant; all drops are leading mesh-object names (before 'Bip') +
   trailing 'Interact' — by design, on capture-validated skeletons.
3. Face rigs: HEAD_SWAPS heads' body weights (Bip01/Neck) are handled by the
   weight-transfer path; EXTRA_HEADS masks now proxy Neck/clavicles/twists.
   Residual RESOLVED same day (user QA round 4, 'dodgy lower cowl'): the
   Head-anchor ride pitched the skirt base 22.5deg with the head in idles.
   Data: cowl Bip01 = ZEROED mini-rig root (Head's grandparent, bind at
   origin), M4 = 90deg + 0.40m (cowl authored in model space, NOT body
   space) -> engine can't name-drive it (broken at rest) and it's not under
   Head. An unmatched rig ROOT keeps the model-instance transform = rides
   the CHARACTER ENTITY. body 'interact' palette IS the entity transform
   (0 rotation in ALL clips; walk carries 4.9m translation). FIX round 5
   (entity ride ALSO failed user QA: skirt stayed at rest height while the
   torso moved = giraffe again): three data points (head ride pitches with
   the head; entity ride lags the torso; the verts sit at chest height with
   clavicle weights already separate) => the skirt base rides the UPPER
   TORSO. Gated bones proxy to Spine2 (fallback Spine1/Spine) with align=M4
   (S = P_spine2@M4: exact at rest, follows the chest). File-only
   approximation chosen by geometry; true engine handling of mini-rig roots
   needs the attachment/remap decomp (parked). USER QA CONFIRMED on the
   21-clip spread (locomotion/attacks/knockdowns/climb/jump) 2026-07-13.

# 2026-07-13g — ATTACHMENT/REMAP DECOMP + LIVE WORN-COWL PALETTES (task 8)

## Name lookup = EXACT match (decomp)
Character bone lookup chain: GetBoneIndex MSG handler 0x4bca76 ->
FUN_004ba320 (char+0x190 skeleton container) -> FUN_004b6eb7 -> hash table at
container+0xc0 (hash FUN_0042c126 = h*2+c over bytes, compare FUN_00443545 =
exact strcmp, CASE-SENSITIVE, no prefix stripping). => The engine itself
cannot match 'Bip01'->'Bip' or 'Interact'->'interact'. (Clip-track binding
must therefore be by INDEX not name — consistent with medium's
'Bip02 *UpArmTwist' bones animating in-game and with our canon-name bake fix
reproducing large/small-identical motion. FUN_005936e2's short table at
[*obj]+0x10 = 16-bit PARENT indices (rest-world composer), NOT a name remap.)

## Worn-cowl palettes extracted from KapowMulti.1.trace (v7 parser, vc>=40)
Full trace: vc hist adds vc48 (16-bone rigs) + vc51 (17-bone) to the known
138/144/189. NiteOwl_Mask2 palette = 17 slots (vc51), order = ordered-names
filtered + rotate-by-one. Identified by rigid bone-length fingerprint
(Neck-Head 0.055 etc.); 159k live worn-cowl palettes across 5.8k frames.
MEASURED (446-frame sample, all orthonormal):
- 'Bip01' and 'Interact' slots are EXACTLY CONSTANT (identity in the draw's
  instance space) — the engine NEVER DRIVES the mini-rig root; its verts
  ride the model instance (entity-parented like body models).
- 'L/R Clavicle' + 'LUpArmTwist' are RIGID TO HEAD (relD rot_sd 0.014) —
  NOT driven from the body clavicles!  The whole cowl below Head rides the
  Head attach except Neck (independently driven, sd 0.18 vs Head 0.30) and
  Jaw/face bones (pose locals, Jaw rot_sd 0.04 = talking).
=> ENGINE TRUTH is CRUDER than our glb: engine = entity-ride skirt base
   (our round-4, which user QA rejected as the giraffe) + head-rigid
   clavicles. Our shipped model (Spine2 ride + body-driven clavicles/neck)
   is a deliberate fidelity IMPROVEMENT over the engine, user-approved.
   Keeping Spine2; engine-exact mode not worth a flag unless asked.

## Gotchas (this task)
- /tmp/palettes_c.bin records = [u32 frame][u32 vc][vc*4 floats]; offsets
  saved as f.tell()-8-vc*16 point at the HEADER — add 8 for data (a wrong
  offset makes rank-1 'palettes' that pass naive fingerprints CONSTANTLY;
  gate real palettes on orthonormal rotation blocks first).
- v7.c: vc gate was >=60 (missed vc48/51) — patched copy in /tmp used
  vc>=40; sreg==40 only. Budget 1.2GB/run, resumable state /tmp/pstate.bin.
- vc48 palettes (54k) = 16-bone rigs (weapons/other heads) still unmined.

# 2026-07-13h — FINAL QA CLOSE
User approved: Heavies (twist+palette fixes, NEW: Heavies_Head_1 face attach
— the Heavy variant is a headless wardrobe set, head was never wired; now in
EXTRA_HEADS + real Heavy.glb rebuilt) and TwilightLady v3 (Spine2 ride).
ALL character glbs current, pending bakes: 0. Every skeleton user-eyeballed.
Project state: no mandatory work left. Optional threads: grip/face heuristic
retirement via interpreter overlays, vc48 palette mining (weapons/heads),
aniso jiggle constants, clip-ID graph-consistency check.

# 2026-07-13i — WLIB PERF PASS (profiled, outputs verified)
Profiled the pipeline (stdlib+numpy only, unchanged): bake 29ms/clip,
jiggle 21ms/clip, write_glb 0.15s/30 anims, face attach 0.85s — already
fast; the wall-clock is MOUNT I/O + repeated per-variant work. Fixes:
1. char_lib._texdir index: os.walk instead of recursive glob+isdir
   (11k redundant scandirs, 2.2s -> ~0.2s per process).
2. char_lib._find_layers memoized per (mat,roots,flip) — shared materials
   repeat across ~25 variants; normal-map green-flip PNG re-encode was
   paid every time (find_textures repeat now 0.00s, was 0.6-3s).
3. characters_export anims load: npz members are LAZY — when a jiggle memo
   exists, pal is read from the memo only (raw npz opened just for fps),
   halving the big-array mount reads per skeleton.
4. REPRODUCIBILITY BUG found by the perf diffing: blink synth used
   hash(animname) (per-process randomized!) -> glbs were never
   byte-reproducible. Now zlib.crc32 -> same-code rebuilds byte-identical
   (verified on Dominatrix_1, 38.3MB). Blink phases shift once (cosmetic,
   synth-invented cadence).
Verified: texture index byte-identical old-vs-new (854 entries, 0 diffs),
layer cache self-consistent, rebuilt glb byte-stable across runs.
Left alone (measured cheap / risk>win): _icp_refine 0.45s, load_parts
vertex decode 0.5s, weight-transfer python loop (~1s worst head).

# NEXT SESSION HANDOFF (2026-07-13 FINAL close — read 07-13 a..i above)
PROJECT: NO MANDATORY WORK LEFT. Everything user-eyeballed and approved.
- Overlay pages SOLVED+shipped (two-stack interpreter, blend-tree weights).
- All 8 skeletons QA'd; 5 user-QA rounds fixed: BipNN palette+track matching
  (char_lib/bake_v4), NTO cowl ride saga (name-proxy + alignment gate +
  Spine2, 07-13d/e/f), Heavies_Head_1 attach wired (07-13h).
- Rebake COMPLETE: 25 glbs, header fps + dense bakes + d6 jiggle, atomic +
  resumable + BYTE-REPRODUCIBLE (07-13i crc32 blink fix).
- Decomp CLOSED (07-13g): exact-match name lookup, clip tracks bind by
  index, live worn-cowl palettes prove engine = entity-ride skirt +
  head-rigid clavicles (cruder than our shipped model, user prefers ours).
- Perf pass done (07-13i): I/O-bound; texture index/memos/lazy-npz landed;
  numbers recorded for what NOT to optimize.
- Docs synced: MASTER, PROJECT_INDEX, CLEANROOM, v7.c persisted.
OPTIONAL THREADS (in value order): Heavies/TL fresh QA passed; grip/face
heuristic retirement via interpreter overlay stack; vc48 palette mining
(54k weapon/head palettes in /tmp extraction recipe, 07-13g); aniso jiggle
(07-12e constants); clip-ID graph-consistency check (07-13 tooling).
Run: python3 -u -B watchmen.py characters 20260708 20260708/characters
(chunk with timeout 40 in sandbox; background procs get reaped).

# SUPERSEDED HANDOFF (2026-07-12g close — OVERLAY PAGES SESSION SETUP)
Supersedes all prior handoffs.  Jiggle thread CLOSED (07-12e/f: d6 promoted,
capture parity; aniso model parked pending interpreter-driven bakes).

## Task 1: interpreter OVERLAY PAGES (wlib/anim_state_machine.py)
Goal: implement overlay pages so OVERLAY_PLAY_POS/REVERSE_OVERLAY_PLAY_POS
criteria (enum 7/8) evaluate correctly, then capture-validate the interpreter
end-to-end; payoff = retire the 3 remaining heuristics (grip timing, face
pairing, layer weights).
Decomp anchors (all in this doc, sections 2026-07-09j/m/n + 07-12b):
- Criteria enum: OVERLAY_PLAY_POS=7, REVERSE_OVERLAY_PLAY_POS=8 (07-09j).
- Run loop addresses: StateMain 0x5b417b, Update 0x5b4613,
  EvaluateTransitions 0x5cbbc2 (2577B body STILL UNREAD — ghidra
  part_0021.c:19256; likely where overlay pages get ticked/selected),
  UpdatePageBlendsFaster 0x5b4bd6 (slot weight = m_nweight*pageblend; slots
  >#9 maskable by [rec+0x18] bitmask when [rec+0x14] set — the masking is
  probably HOW overlays coexist), SetAllSlotBlends 0x5b4ef7,
  TransitionPlayPos 0x5ac1aa, SynchronizePages 0x5ac387, CheckPlayPosEvents
  0x5b51f3.  SetupNewPage 0x5b7788 + UpdatePagePlayPos 0x5b56a9 already read
  (07-12b) — extend the same capstone approach (exe_dis.py) to
  EvaluateTransitions and any overlay-page creation path (look for a second
  page-push call site of 0x50030f).
- AnimLayer machinery (kernel/animation/animlayer.cpp, additive flag, ease
  in/out, ANIMATION_LAYER enum) is the likely overlay carrier (07-09d note).
- Interpreter file: load_tree/get_valid_state/transit/tick/slot_weights all
  engine-verified; page stack capped 8; overlay criteria currently stubbed.
Validation data: captures in dominatrix_capture/ (female EN4 dancers ALL_
deduped 6-dancer interleave — tracker recipe in 07-12e), rsh_captured_
palettes_t1.npy, nto_captured_palettes_t1.npy, gimp_captured_palettes_t2.npy.

## Task 2: QA the untested skeletons (user request)
Only female (Dominatrices), gimp, and partially rsh have been animation-QA'd.
Untested: medium, large, small, bs2, nto binds + their baked clips + glbs
(20260708/characters/_bake/{medium,large,small,bs2,nto}/, glbs in
20260708/characters/<Char>/).  Suggested pass per skeleton: (1) spot-check
bind FK vs skeleton_records, (2) bake or load 2-3 clips (idle/walk/attack),
(3) lerp-error metric (characters_export._lerp_err), (4) visual glb.  rsh/nto
have raw captures for palette-level validation (t1 files above); medium/
large/small have none — file-side checks only.

## Task 3 (end of session): FULL REBAKE
Delete 20260708/characters/_bake/* and characters/*.glb, rerun watchmen.py
characters — picks up header-exact fps, finger-shear fix, and d6-default
jiggle in one pass.  Machine-time heavy; run last.

## Standing notes
- Write wlib files via bash heredoc + ast check (Edit-tool truncation trap);
  pyc cache poisoning: run python -B or copy to /tmp; jointframes_v2_* is the
  live cache (v1 = pre-fix, undeletable on mount, ignore).
- Canonical extract = 20260708/. Fresh-install smoke test passed 07-09r.

## 2026-07-17 — data-table provenance closed + gen_data.py (shippable toolkit session)
`wlib/gen_data.py` (both copies; CLI `watchmen gendata`) regenerates the wlib
data tables from a game install and documents each table's provenance:
- prop_hash_dict.pkl: exe+naz string harvest + identifier tokenization
  (camelCase/underscore sub-tokens — names like 'Speed' only occur as
  substrings). FULLY de novo, works on retail DRM'd KapowMulti.exe: SecuROM
  encrypts .text in place (extra .bind section) but .rdata/.data are
  byte-identical to the unpacked exe. Functional check vs canonical 20260708
  pb-family JSONs (297 files): 202 byte-identical, 3 case-only, 92 strictly
  better (more hashes named), 0 regressions.
- reg_dump.json: reg_scan ported into wlib (Ghidra-free — .rdata string map
  replaces strings.tsv; capstone; refuses packed .text). Output byte-true;
  shipped json only differs by Ghidra's trailing-space trimming.
  [corrected 2026-10-02: reg_dump.json is format 2 since 1.3.0: a
  register-tracking sweep, 5090 props, the real classId, a handler slot per
  command.]
- prop_names_from_reg.json: PURE aggregation of reg_dump (first registration
  wins incl. Nones; one classes[] entry per registering class OBJECT —
  duplicate class names stay duplicated). engine_schema now derives it at
  runtime when the file is absent; dropped from the shipped toolkit.
- kapow_fragment_keys.pkl: NOT regenerable — names + inferred value types are
  the crack result itself (types drive parsing: NAMES[hash] selects decode
  path). gendata keys-export/-import round-trips it to readable JSON.
- jiggle_params.npz: dropped from the shipped toolkit (absent -> jiggle_pass
  delegates to file-only jiggle_d6, the promoted default). Root wlib keeps it.
Gotcha: a null-terminated-string REGEX ([\x20-\x7e]{3,}\x00) backtracks O(n^2)
on NUL-free printable stretches (hung on naz payloads) — gen_data._runs is the
linear split-scan replacement. Naz-wide string harvest ~21 s.
Shippable product folder: `watchmen-toolkit/` (PEP 517, `pip install .`,
console script `watchmen`, docs/ + provenance README).

## 2026-10-02 — dual (master/slave) animation placement

Full write-up with the consumer-facing rule: `docs/ANIMATION_META.md`.

- Trigger: `AnimationCtrlWM.SetupNewPage` 0x5b9afb–0x5b9b54. New state with a
  non-zero `Master of` (+0x30) and a partner → sends
  `request_me_as_dual_animation_partner` (0xb47fc836) and `goto_slave_mode`
  (0xa3a6f711, args MasterOf id) to the partner's CharacterRoot.
  `CharacterRoot.command_goto_slave_mode` 0x693b2e picks the slave state with
  `AnimationStateGroupWM.command_get_valid_state` (0x499d201a) and sends
  `command_goto_slave_mode_state` (0x4b150a3d).
- Placement: `CharacterRoot.StateActive` (0x6b367a; undefined in Ghidra, read as
  asm), block 0x6b9035–0x6b94e9, guarded by capsule `is_absolute_mode`, self
  `is_in_slave_mode`, partner non-null:
  `start_pos = M · (I0 − Δ)`, `start_orient = r * Q_M`, with M / Q_M the
  master node's current world matrix / orientation, I0 =
  `get_interact_initial_pos` (0xa591eb43), Δ = `get_slave_pos_offset`
  (0x90349206) = track0(t) − track0(0), r = (0, sin(−π/2), 0, cos(−π/2)) from
  the float at 0x9e8440. I0 == 0 → (0.11, 0.04, 1.12) from 0xa5f02c / 0x9e616c
  / 0xa5f028. Written to capsule +0x10 `m_vWorldStartPos` and +0x28
  `m_qWorldStartOrient`.
  [corrected 2026-10-02: (1) "undefined in Ghidra": defined by
  tools/ghidra/DefineKapowHandlers.java. (2) M / Q_M are the world transform
  of the master's CharacterVisual node (CharacterRoot data +0x24; +0x28 is the
  capsule). (3) The block runs every tick. (4) The two capsule properties take
  effect only while capsule +0xb8 is set: the frame actually used is a
  PivotNode "worldstartnode", refreshed from them by command_update_world_data
  0x6b201d.]
- Capsule property offsets (hash-matched): +0x10 m_vWorldStartPos, +0x1c
  m_vWorldEndPos, +0x28 m_qWorldStartOrient, +0x38 m_qWorldEndOrient, +0x4c
  m_vAbsInteractPos, +0x58 m_qAbsInteractOrient.
- Clip data: +0x48 = GamePivot track index, +0x4c = interact track index.
- Per frame: `CollisionCapsuleNode.command_absolute_update` 0x67f7b0:
  pos = start + R(start_orient)·(GP(t) + loopOffset − GP(0)); orient =
  q_GP(t) * start_orient; blended in from the entry pose when the mode flag is
  set. `StateAbsoluteAnimation` 0x6a1e1d stores −GP(0) at state init.
- `command_get_slave_alignment` 0x5b0ddf is a stub (identity quaternion);
  `get_slave_pos_at_time` 0x5b0698 has no caller by hash.
  [corrected 2026-10-02: it is called by hash 0xe873fd55 from
  CharacterRoot.StateActive (auto-align block).]
- Engine quaternion convention in this code: products are "child * parent",
  vector rotation is conj(q)·v·q.
- Open: the master's own start frame in combat (flag-1 branch of
  `command_goto_animation_mode` 0x67bd36 keeps the stored start when capsule
  +0x48 is 0); writers of m_vAbsInteractPos/Orient (use-trigger code,
  presumably); `CharacterRootLogic.command_animation_event_received` 0x6a525e
  (ABSOLUTE_GOTO_TARGET_POS, LOOK_AT_TARGET) not read.
  [corrected 2026-10-02: all three closed. No shipped master state is an
  absolute animation, so the master gets no start frame and is never snapped;
  in the flag-1 branch with capsule +0x48 == 0 the stored start is kept.
  m_vAbsInteractPos / Orient are written by scripted interactions
  (command_play_specific_anim 0x6af969, TriggerCharacter.StatePullSwitch
  0x896bb0), not by combat. ABSOLUTE_GOTO_TARGET_POS sets capsule +0xb8
  (0x6a9dca); LOOK_AT_TARGET is a camera event (0x6a86ae).]


## 2026-10-02 (later) — full decompilation pass

Nine research reports, shipped verbatim in `docs/re/` (index and known
corrections: `docs/re/README.md`), then implemented in 1.3.0. This section is
the summary with addresses; the reports have the detail and the evidence level
of every statement. Where an earlier section of this file said something
different it now carries an inline `[corrected 2026-10-02: …]` note. Items
marked "impl" were found while implementing and are not in the reports.

All addresses: `KapowMultiDEDRM.exe`, image base 0x400000.

### Tooling (`tools/ghidra/`)

- `__EH_prolog` is at 0x991850 and ends in `push eax; ret`; Ghidra took it as
  no-return and cut every caller at the call. `FixEHProlog.java` re-bodies
  2,000 functions.
- 1,191 of the 4,516 registered handler addresses were not functions at all
  (reached only through the registration table). `DefineKapowHandlers.java`
  creates and names them. SetupNewPage 0x5b7788, UpdatePagePlayPos 0x5b56a9,
  CharacterRoot.StateActive 0x6b367a and the CharacterAddonCtrl setup / update
  are of this kind — not SEH stubs, as earlier notes assumed.
- Functions 16,369 -> 17,225; functions of 12 bytes or less 2,473 -> 622.

### Name hash and command signatures (`re/names.md`)

- FUN_00423ce8: bit-CRC32, poly 0x04C11DB7, over every byte `& 0xDF`
  (`and cl,0xdf` @0x423cf7). FUN_00423d30 is the same, stopped at ':'.
  Not upper(): '0'..'9' -> 0x10..0x19, '(' -> 0x08, ')' -> 0x09, ',' -> 0x0C,
  ':' -> 0x1A, space -> 0x00. FUN_00423d7c / FUN_00423ca1 hash raw bytes with a
  length and no fold (block-version checksum, music cue points), not names.
- Asset names use the folding hash too: FUN_005511b8 stores it at asset+0x50,
  FUN_0054ba59 looks an asset up by it (impl). Bone names do not
  (FUN_0042c126, see 07-13g).
- Command hash = name_hash(cpp name incl. `command_`) for a parameterless
  command (866 distinct), else name_hash("name(type,type,...)") — no spaces,
  no return type (830 distinct). 0x6eed1060 =
  command_set_achievement_earned(integer). All 1,696 distinct hashes
  reproduce. Type vocabulary: entity, integer, number, truth, vector, string,
  quaternion, list(T) and struct names; case is not recoverable.
- A handler takes one 4-byte slot per parameter, except vector = 3 and
  quaternion = 4.
- Inferred: that the offline script compiler used this hasher on the
  signature string (no run-time code builds one).

### Registration functions (`re/names.md`; `watchmen gendata regdump`)

    0x47e126 create class      (name, classId, nativeBase, scriptParent|0, flag, flag)
    0x47fde4 register property (hash, defaultVA|0, uiVA, flags, typeIdx)     flags in {0,1,3}
    0x47eccc register command  (name, kind, arg3, hash|-1, cmdHandler, stateHandler,
                                methodHandler, typeIdx)  -> 0x38-byte record, hash at +0x18
    0x47f650 native script function (signature "Name(type,..):ret", handler, doc)

441 classes, 5,090 property registrations (3,695 distinct hashes), 6,630
command registrations. typeIdx indexes DAT_00c89ebc = the DECLARING CLASS
(equal to the class's own id at 4,262 / 5,090 property sites), not a value
type. No property name is pushed at a registration site; it exists only as
the hash.

Commands: the handler sits in one of three slots. cmdHandler (3,939, real
hash) / stateHandler (841: _root, StateActive, StateMain ...) / methodHandler
(1,850: Init, ...). State functions and script methods carry hash 0xFFFFFFFF
and cannot be sent by hash (FUN_004f99a4 refuses that value). `kind` is 1 or
3; its meaning and that of arg3 are not established.

Built-in node properties go through one typed wrapper per data type:
0x505514 integer, 0x505553 biginteger, 0x505592 number, 0x5055d1 string,
0x505610 truth, 0x50564f vector, 0x50568e quaternion, 0x5056cd netparticipant,
entity wrappers via 0xe151a0; type objects are created in FUN_00501f6a. That
is what types a built-in property (impl: 862 names typed this way);
biginteger is 8 bytes in a fragment.

### Enum registration (`re/enums.md`)

FUN_005052c9(family, "PREFIX___NAME", value) is the only writer of the enum
table (0xc8bd78); FUN_0050574a is a thin wrapper. 1,813 registrations in 65
functions, 186 families, 1,801 names. The family is the first argument, not
the text before `___` (CHARACTER_TYPE___X goes into CHARACTER_TYPES). Nothing
is loaded from game files. LANGUAGE names are built at run time
(0x47ffdd-0x48017d).

Animation families are registered in 0x809e94 and 0x5e50f7. ANIMATION_ENUM
(criteria enum variables): 0 ATTACK_DIR, 1 CHARACTER_MODE, 2 ATTACK_TYPE,
3 ATTACK_POSE, 4 DAMAGE_POSE, 5 WEAPON_ANIMATION_TYPE, 6 MODEL_ANIMATION_TYPE,
7 TARGET_MODE, 8 OVERRIDE_ATTACK_COMBO, 9 STATE_CHANGE_OVERRIDE, 10 TARGET_LOCK,
11 OPPONENT_MODEL_TYPE, 12 OPPONENT_WEAPON_TYPE, 13 KNEE, 14 SPECIFIC_MODEL,
15 SCENE_ID. OPPONENT_MODEL_TYPE: NONE 0, RORSCHACH 1, NITE_OWL 2, ENEMY_01 3,
ENEMY_02_BIG_GUY 4, UNDERBOSS 5, ENEMY_03 6, ENEMY_04 7.
ANIMATION_EVENT_TYPES: PLAY_POS 0, ENTER_STATE 1, LEAVE_STATE 2,
TOTAL_PLAY_TIME 3. ANIMATION_SYSTEM_NODE_TYPE (m_iAnimationSystemType):
BLEND 0, CRITERIA 1, SLOT 2, STATE 3, TRANSITION 4, CLASS 5, EVENT 6,
STATE_GROUP 7, PLAY_POS 8. The 30 families the toolkit uses are in
`wlib/engine_enums.json`; `re/enums.md` lists the animation ones in full.

An ENUM criterion reads only m_ianimationenum (rec+0x28) and
m_ianimationenumvalue (rec+0x2c) (AnimationCriteriaMet 0x5c5781, branch
kind == 2); m_ianimationvalue (rec+0x14) is read only by a VALUE criterion.

### Animation records (`re/pages.md`, `re/sync.md`)

Record offsets are 4 x registration index.

    AnimationState   +0x04 m_ecriterialist      +0x08 m_eanimstategroup (owner)
                     +0x14 m_toverridestate (overlay stack)
                     +0x18 m_tiswalkcycle ("Sync Playpos")   +0x1c absolute
                     +0x20 / +0x24 defines movement / rotation
                     +0x28 m_tdisallowoverridelayers  +0x2c m_tallowmultipleinstances
                     +0x30 m_imasterof          +0x34 m_tislooping
                     +0x38 m_nstartplaypos      +0x3c m_neaseinduration
                     +0x40 m_tusesoftblend      +0x44 / +0x48 curve hardness / offset
                     +0x4c m_efallbackstate     +0x50 m_nforcestaytime
                     +0x54 m_tholdblendvalues   +0x58 m_tnotransitiontests
                     +0x5c m_tforcemovementcalc +0x6c m_etransitionlist
                     +0x70 m_elayerlistlist (indexed by layer)  +0x74 m_eeventlist
                     +0x78 m_estoredtransitstate  +0x80 m_eplayposmapper
                     +0x9c m_ispecialhandling   +0x15c animation type
    Transition       +0x04 m_ecriterialist  +0x08 m_etostate  +0x0c m_tfallback
                     +0x10 m_toverrideeasein  +0x14 m_neaseinduration
                     +0x18 m_toverrideplaypos +0x1c m_nplaypos  +0x20 m_tsupersyncpos
                     +0x24.. 8 x (local, remote) markers, default -1.0
                     +0x64 / +0x68 sorted local / remote lists (built at init)
                     +0x6c / +0x70 m_nsupersyncmin / max   +0x74 m_eeventlist
    Event            +0x00 m_ieventtype  +0x04 m_nplaypos  +0x08 m_ianimationevent
                     +0x0c m_tforceupdateblends  +0x24 m_nvalue
    Page             +0x08 blend (linear)  +0x0c ease  +0x10 playpos
                     +0x14 rate (playpos / s)  +0x18 sync  +0x1c state
                     +0x30 looping  +0x34 time played  +0x38 playpos at last event check
    Page list        +0x14 force-stay timer  +0x18 end-of-animation flag

State +0x9c and +0x15c are inferred by counting properties in registration
order; the rest are read against their uses. The +0x54 / +0x40-bit0 tests in
TransitionMet are entity fields (enabled), not record offsets.

### Pages and play position (`re/pages.md`)

TransitToState 0x5b4a31 args = {state, ease, playpos}: ease < 0 = the state's
own, playpos < 0 = the state's start position. If the outgoing and the target
state are both walk cycles and no position was passed, the outgoing play
position is kept and the page is flagged sync.

SetupNewPage 0x5b7788 args = {state, playpos, sync, ease, pagelist}:

- nothing happens if the top page already plays the state and "Allow more
  than once" is off (0x5b780a);
- an override state goes on the overlay list, and is not created if the body
  top state disallows override layers;
- page list +0x14 = the state's m_nforcestaytime (0x5b7d49);
- re-entry (0x5b7da0-0x5b82dd): a page lower in the stack that plays the same
  state is removed, the pages above are renormalised, the new page starts at
  the old page's share and, for a walk cycle, at its play position;
- ease rule (0x5b83f8-0x5b8593): instant if the state's own ease-in <= 0 (a
  transition's override is then ignored), if it is the first page of the body
  list, or if the passed ease is exactly 0; else the passed value if > 0, else
  the state's;
- one blend node per inner list of m_elayerlistlist, picked with a
  Mersenne-Twister rand % n (FUN_0047aa2e); command_add_layer 0x5f773f files
  each blend node under its m_ilayerindex (impl);
- no page-count cap.

Update 0x5b4613 order, per stack: speed -> EvaluateTransitions -> force-stay
timer -> UpdatePageBlendsFaster per page -> DeleteOldPages ->
SynchronizePages -> ClearAnimationPosEvents -> UpdatePagePlayPos per page ->
CalculateVelocity.

Rate (SetAllSlotBlends 0x5b4ef7, 0x5b5175-0x5b51d0), over the slots of the
page's first populated layer:

    page.rate += ctrl.speed x slot.speed x slot.weight / clip.duration
    ctrl.speed = class m_nspeedfactor x GetGameSpecificSpeedFactor() x ctrl m_nspeedfactor

slot.speed is the slot's `speedFactor` property: +0x64 on an AnimSlot (getter
0x4b30b1), +0x84 on an AnimBlendSource (impl). 707 of 1,290 states run at a
speed other than 1; 214 of the 240 primary pair masters at 1.1. Not
established: that the objects in a page's slot list are the fragment's
AnimSlot nodes themselves and not sources created from them.

Advance (UpdatePagePlayPos 0x5b56a9): playpos += min(rate, 6.6) x dt (double
at 0xa45e90); when playpos > 1.0 (strict) a non-looping page clamps to 1.0, a
looping one subtracts 1.0 until <= 1.0. blend += dt / ease AFTER the frame's
weights were applied, so a new page has weight b(0) in its first frame.
Overlay pages fade out by dt / ease when finished or disallowed and are
removed below 0 (floor -0.01). SynchronizePages 0x5ac387: a run of pages with
the sync flag shares one rate, 1 / sum(w / rate).

Blend curve (0x5b4bd6): applied only if the state has m_tusesoftblend and
AnimationData "Force Linear Transitions" is off; otherwise linear.

"No Transition Tests" (0x5cbbc2): evaluated only when play position >= 1 or
ctrl.m_tforceupdate (+0x2c) is set; the engine sets that flag when a page is
added or blending, and it can be set from outside (impl).

Force-stay (0x5cbbc2, Update): a wanted transition is deferred while page
list +0x14 > 0. m_nforcestaytime is 0.0 in every shipped state.

Clip time -> key (0x591975): t = clamp(time, 0, duration); f = (keyCount-1) x
t / duration; floor / ceil; lerp for positions, sign-corrected nlerp for
quaternions. One index pair for all tracks. keyRate and frameRateScale are not
read by the sampler.

### Owners and criteria (impl; replaces what the 07-09 notes say about "member2")

Owner searches walk up the logical parents and look only at nodes that have
m_iAnimationSystemType; folders and plain nodes have none.

    state      -> first STATE_GROUP (m_eanimstategroup) and the CLASS   AddToClass 0x5ed37a
    group      -> first typed ancestor if it is a group                 AddToParentGroup
    transition -> first typed ancestor if it is a state or group        AddToClosestState
    criterion  -> the first typed ancestor; an owner transition (+0x34) or state
                  (+0x38) ends the walk, state groups are collected in +0x3c
                                                    FindClosestRelevantParent 0x5aaf49

Class command_add_state 0x5a03a8: override states (or their outermost group)
form the overlay candidate list; states with m_istateid form the slave-state
table. The class root owns no transitions.

MathLib.InsideInterval 0x77aa25 (x, min, max, type): 0 min <= x < max;
1 x < max; 2 x >= min. Entry-only (criterion +0x08): met without testing when
the top page's state is the owner state or inside the owner group, unless the
state's +0x68 is set (set only around the normal-pass get_valid_transition in
EvaluateTransitions).

StateGroupCriteriaMet 0x5c6002 = owner chain AND own list; StateCriteriaMet
0x5c647c = own list only; command_Group_criteria_met 0x5f781a = owner chain.

### Transitions and sync markers (`re/sync.md`)

- Selection: the normal pass skips m_tfallback transitions, the fallback pass
  takes only those (0x5f7873 / 0x5c6140); a target is tried once per
  evaluation. The fallback pass runs when the state's criteria or its owners'
  criteria fail; then m_efallbackstate, the class's m_edefaultanimstate, the
  class's m_esafetyfallbackanimstate.
- AnimationTransition.initialize_external 0x5f9b13: when the target is a
  state, its criteria are appended to the transition's list. A state target is
  therefore gated by the transition's criteria, the target's own criteria and
  StateGroupCriteriaMet(owner chain); a group target by
  StateGroupCriteriaMet(target) and get_valid_state (impl).
- UpdateSuperSync 0x5fa582 (called from Init 0x5fa96c): with "Sync PlayPos?"
  set, markers are taken in order until the first local < 0 (remote is not
  tested), bubble-sorted by local (0x5ed5a2); m_nsupersyncmin / max = first /
  last local.
- Gate, TransitionMet 0x5c5ea4: such a transition is met only while
  min <= top page playpos <= max.
- Start position, TransitionPlayPos 0x5ac1aa: override -> m_nplaypos; no sync
  -> -1 (no opinion); else i = first index with local >= p: i == 0 ->
  remote 0; i == n -> remote n-1; else MapIntervalToInterval 0x77a579
  (p, local i-1, local i, remote i-1, remote i). No implicit (0,0) / (1,1).
- Priority of the start position: transition override > sync markers >
  walk-cycle carry-over > the state's m_nstartplaypos; then, if the target is
  already on the stack and is a walk cycle, that page's position.
- It is a one-shot start position, not a time warp. The curve belongs to the
  target state; a transition can only override the duration.

### Events (`re/events.md`)

- Sender CheckPlayPosEvents 0x5b51f3. PLAY_POS: fires once per pass when
  m_nplaypos <= play position and not yet fired (0x5b55c4, `test ah,0x41 /
  jp`) — a latch; an event skipped by a wrap is marked pending and fires on
  the next check. The (previous, current] window is used only under the
  AnimationData debug play-position override (0x5b5399). TOTAL_PLAY_TIME:
  m_nplaypos is SECONDS, fires once when <= time played on the page
  (0x5b52c1). ENTER_STATE is sent by SetupNewPage, LEAVE_STATE by
  SetupNewPage / UpdatePagePlayPos.
- A PLAY_POS event with m_nplaypos <= the page's start position is created
  already fired (0x5b8f16).
- Delivery SendAnimationEvent 0x5ac4ef -> hash 0xf7c3b75f
  command_animation_event_received. Receivers: CharacterRootLogic 0x6a525e
  (37,665 bytes, four compare chains), CharacterCameraStateManager 0x64b304
  (id 18 only), TriggerCharacter 0x87d421 / 0x87e574 (ids 78, 79, 8).
- ABSOLUTE_GOTO_TARGET_POS (28), 0x6a9dca: capsule data +0xb8 = 1, nothing
  else.
- LEAVE_ABSOLUTE_MODE (19), 0x6ac8de: goto_phys_normal_mode (capsule ->
  StateOnGround, position kept), leave_slave_mode on both sides, break_joint.
- KILL_ANIMATION_PARTNER (20), 0x6ac5f6: give_damage of 100000 to the victim
  and the partner link cleared; no transform is written.
- LOOK_AT_TARGET (45), 0x6a86ae: a camera event (command_lookat_target_timed);
  no character field is written.
- No event case writes a partner's position or orientation. Ids with no
  receiver in the exe: 0, 1, 2, 3, 14, 43, 44, 50, 51, 90.
- Case map for every id: `re/events.md`, `re/events_table.json`,
  `wlib/engine_enums.json` (event_semantics).

### Paired animations: cadence and timeline (`re/placement.md`, `re/events.md`)

Supersedes the open points of the first 2026-10-02 section.

- The placement block (CharacterRoot.StateActive, 0x6b9035-0x6b94e9) runs
  EVERY tick, behind three tests: own capsule is_absolute_mode, own controller
  is_in_slave_mode (controller +0x60 != 0), partner (controller +4) != 0.
- M / Q_M are the world transform of the master's CharacterVisual node
  (CharacterRoot data +0x24). r = (0, sin c, 0, cos c), c = -pi/2 at 0x9e8440;
  the product is r (x) Q_M in Hamilton terms.
- The start frame the capsule uses is a PivotNode "worldstartnode" created at
  state init (StateAbsoluteAnimation 0x6a1e1d). It is refreshed from the
  properties +0x10 / +0x28 only by command_update_world_data 0x6b201d, which
  runs only while capsule +0xb8 != 0.
- Writers of capsule +0xb8: goto_animation_mode 0x67bd36 (= args 4, which
  command_goto_phys_absolute_mode 0x68a79f sets to 1 iff the state's special
  handling is 0); StateAbsoluteAnimation one tick after init (= 0 if the state
  has Master of); the ABSOLUTE_GOTO_TARGET_POS event (= 1).
- The master: no shipped master state is an absolute animation (data), so
  SetupNewPage sends it to normal physics mode. It gets no start frame and is
  never snapped.
- The partner: enters absolute mode at its own current pose (flag 0); the
  block's output is ignored until the event sets the flag; then
  absolute_update 0x67f7b0 blends from the ENTRY pose (captured at state init)
  to the anchored track: timer -= clamp(dt, 0, 0.1); w = timer / blend. The
  blend time is the partner state's own ease-in: goto_slave_mode 0x5b32a2 ->
  ForceToState 0x5b4933 with ease -1 -> SetupNewPage, whose tail passes page
  +0x0c to the absolute-mode message (impl).
- Slave lock (impl): goto_slave_mode stores the master's first animation
  source in the partner controller's _eslaveof (+0x60). UpdatePagePlayPos
  0x5b5756-0x5b57d0: body stack, top page, _eslaveof set -> page.playpos =
  the source's position (time / duration, 0x591920); cleared when that is
  >= 1. The pair is locked in play position and runs at the master's rate.
  On 145 of 240 primary pairs the two states have different slot speeds
  (master 1.1, partner 1.0).
- Once the flag is set the master's capsule drives the partner: DccUpdate
  0x680654 -> DccJoint 0x6a3d71 sends absolute_update(apply = 0) to the
  partner's capsule, sweeps to its predicted position, and drives an
  EmbeddedJointNode ("DualAnimationJoint") there; level geometry moves both.
- anchor_pos(t) = M(t) . (I0 - (GP_m(t) - GP_m(0))): the subtraction cancels
  the master's own translation, not a turn of its node.
- get_slave_pos_offset 0x5af879 uses track index 0 literally (0x5af938);
  get_slave_pos_at_time 0x5b0698 is called by hash 0xe873fd55 from the
  auto-align step of StateActive.
- The pair ends by the partner's LEAVE_ABSOLUTE_MODE event, by the partner's
  watchdog in StateActive (partner null or dead, or the master has left the
  paired state), or by the master changing state (SetupNewPage, DualAnimBroken
  0x675f4f). Position is kept; there is no snap.
- No mirroring and no per-character scale anywhere in these functions.
- Pairs do not loop (data).

Not established: whether a non-absolute master's visual node turns with its
GamePivot during the clip (matters on 39 of 240 primary pairs, 14 master
clips); the DCC joint's parameters; the quaternion tolerance at 0xd91bf8;
whether the visual node and the capsule share an origin.

### Clip tracks: constant position of type 1 / 3 — OPEN

`anim vtable+0x18` (0x593034) is true only for track types 0 and 2. For types
1 and 3, FUN_00594cac (0x594d38-0x594d49) adds `pose.local[bone].pos` to the
track's constant position, where `pose` is the pose object the layer evaluator
receives; FUN_00594392 shows it is a live local / world pose cache, not a
constant table. What it holds for these bones at that moment is not
established.

The data says the shipped non-zero constants are absolute values: the
constant `Bip` y of a prone pose clip equals the first keyed `Bip` y of its
continuation clip to 1 mm on twelve pairs checked (EN2 prone_back_pose -0.843
/ prone_back_start -0.843; RSH prone_back_Pose -0.867 / prone_back -0.866;
...). Adding the bind offset (rsh -0.073, nto +0.060, large +0.094) would
create a pop of that size at every pose -> start boundary, and would put a
weapon 14 cm past the wrist on the two `Attach RHand` tracks.

Scope: 577 of 64,567 type-1/3 tracks have a non-zero constant; 435 are
GamePivot / interact (rest local 0, no effect); 23 `Bip`, 2 `Attach RHand`,
the rest prop bones. No capture covers an affected track.

Decision: `bake_v4.py` is unchanged. Its rule (constant != 0 -> absolute,
constant == 0 -> bind local) reproduces the data in both regimes and is the
rule validated against captures for the zero case.

### Node collision volumes (`re/skeleton_blobs.md`)

Node::Deserialize 0x545927, lists at 0x545c7f-0x545d94, factory 0x524b23.
After `[u32 f1][i32 parent][u32 cnt34][cnt34 x u32][u32 cnt40][u8 flag]`:

    [u32 n0] n0 x volume     shapes for PhysX scene 0   (node+0x4c)
    [u32 n1] n1 x volume     shapes for PhysX scene 1   (node+0x58)
    [u32 n2] n2 x surface    (node+0x64)

    volume  = [u32 type][u32 base][type data][f32x3 pos][f32x4 quat xyzw][u32 blobLen][blob]
    surface = [u32 nT][nT x (f32x3, f32, i32)][u32 nV][nV x f32x3][u32 nI][nI x u32]

    type 2 concave mesh   u32 mode, u32 nV, verts, u32 nI, u32 indices   + cooked blob
    type 4 convex mesh    same; blob starts "NXS\x01CVXM"
    type 5 box            f32x3 FULL extents                (52 bytes)   reader 0x521396
    type 6 sphere         f32 radius                        (44 bytes)   reader 0x521c3f
    type 7 capsule        f32 diameter, f32 height along local Y (48 bytes)  reader 0x52213d

PC corpus (740 models): 934 volumes in 23 models — 743 capsules, 123 boxes,
51 spheres, 17 convex meshes; all 2,069 mesh-free node regions tile. The
third list is non-empty on one node (`ACUnit_Wall_02`, "splash emitter");
that it is a particle-emission surface is inferred. Which game purpose each
PhysX scene serves is not established. These are not joints.

### Jiggle (`re/jiggle.md`; capture re-measurement is impl)

Engine (CharacterAddonCtrl): setup 0x6574cd, joint 0x648858, update 0x6563a0.

- Addons: Spine2 -> BreastL, Spine2 -> BreastR, Spine -> JiggleBelly, Head ->
  Hair. Per addon two MockupBoxes: anchor 0.1 m (f32 @0x9e664c), kinematic,
  moved to the PARENT bone every frame; body 0.8 m (f32 @0xa06d84), mass 0.1,
  dynamic. RigidBody ctor 0x4fe311: 4 solver iterations, linear damping 0,
  angular damping 1.0.
- D6 joint in the anchor box's frame = the parent bone frame: X / Y / Z
  translation and twist (X) locked, Swing1 (Y) and Swing2 (Z) Limited with
  spring k and damping d verbatim, limit values 45 and 0 degrees. Nothing on
  the path scales k or d; only limit angles are converted (x 0.0174533).
- Step: h = 1 / physicsIntegrationRateInHz (FUN_004f4d20), up to
  maxPhysicsIntegrationTimesteps per frame. File values: 60 Hz, 3.
- Update per frame: anchor box -> parent bone world pose; p, q = body pose in
  the anchor's frame; ApplyForce(-m x gravity) (0x656fb4-0x65707c); p0, q0 =
  the bone's animated local pose; d = p - p0; if |d| > limit: t = limit / |d|,
  p = p0 + d t, q = slerp(q0, q, t) (FUN_0041fd54); SetBoneLocal(bone, p, q).
  Local position AND rotation are replaced, with no gain. Limits 0.08 / 0.10 /
  0.30 m (breast / belly / hair).
- The body pose read in a frame is the previous physics result: one frame of
  latency (order in 0x6563a0; measured on the captures).

Capture facts (dominatrix fight tracks 5,730 frames, gimp 1,621 frames;
capture rate about 55 fps by clip matching):

- relative to the previous frame's parent pose: twist 0.45 deg rms, lever
  rigid to 3.4 mm (breast) / 0.9 mm (belly);
- swing: breast K about 570 s^-2, D about 37.5 s^-1; belly K about 308, D
  about 19.2; parent angular-acceleration coupling 0.84-0.92; linear coupling
  consistent with m / I of the 0.8 m cube; no gravity term. K scales with
  fps^2 and D with fps, so both depend on the 55 fps estimate;
- capture maxima of the bone-origin displacement: 0.0800 m (breast);
- nightclub dancers do not jiggle (breast palette == Spine2 palette);
  ALL_deduped is the fight capture;
- the earlier K 166-170 / D 18-19 and the dts = 1/120 softening match assumed
  30 fps and are withdrawn.

Toolkit: `jiggle_d6.apply_jiggle(P, fps, bind, model='pivot'|'pinned',
mode=None|'capture'|'engine'|'ratio'|'absolute', latency=None)`;
DEFAULT_MODEL = 'pinned' (as 1.2.0); 'pivot' is opt-in (`--jiggle-model pivot`)
and its default mode is 'capture'. Jiggled palettes are cached per model in
_bake/<key>_j_<model>-<mode>-<hash>/. Capture-driven
traces, pinned -> pivot (BreastL / BreastR / JiggleBelly): rotation error rms 5.90
/ 5.64 / 4.09 deg -> 4.29 / 4.13 / 1.96; origin error 16.4 / 15.8 / 5.6 mm ->
8.0 / 7.7 / 3.5; fitted gain 0.34 / 0.35 / 0.16 -> 0.98 / 0.96 / 0.87;
mean-magnitude ratio 1.05 / 1.02 / 0.52 -> 1.57 / 1.47 / 1.58 (the capture
input has no root motion; the cause of that ratio is not established).

Open: K and D from the file constants (no expression in k, d, the cube
inertia and h reproduces both groups); hair (no capture); the force per
substep when a frame takes several physics steps; which characters get the
addon controller at all.

### Vertex declarations and ModelRes (`re/formats.md`)

Stride table 0x00C791B0 (u32 x 11): 28, 24, 68, 16, 56, 44, 56, 60, 48, 20, 32.
Declarations are created in FUN_0045544e. The format id is stored in the file:
it is the third u32 of the vertex-buffer descriptor (what earlier notes call
G; it is not an element count).

    5  rigid         44  pos f32x3 @0, normal half3 @12, colour D3DCOLOR @20 (bytes B,G,R,A),
                         uv half2 @24, tangent half3 @28, bitangent half3 @36
    6  skinned       56  format 5 + bone indices @44 (idx0..3 = bytes 46, 45, 44, 47),
                         weights half4 @48
    9  shadow hull   20  pos f32x3 @0, normal half3 @12
    10 skinned hull  32  format 9 + bone indices @20, weights half4 @24
    8  terrain       48  pos, half4 normal, colour, 3 x half4 texcoord
    3                16  FLOAT2 pos + FLOAT2 uv (2D / UI)

Positions are raw floats: no quantisation, scale or bias in any format, and no
declaration has a SHORT element. Indices are always u16 triangle lists; the
descriptor stores a byte count. Part 2 PC census (740 models, 3,118 buffers):
format 5 x2370, 6 x287, 9 x357, 10 x104, nothing else.

Header after the property bag: ModelRes::Read FUN_00547006 -> Part
FUN_00545927 -> Submesh FUN_00542541 -> MeshBuffer FUN_004336ec; layout in
`KAPOW_NAZ_FORMAT.md` §6b. Stream: for each MeshBuffer in header order,
vertices, indices, `[u32 n][n x 40 B]` cluster table, `[u32 n]` lists,
`[u8 has][vertexCount x 8 B]` (order of FUN_00433ef4). Reproduces the stream
length exactly on 740 / 740 models.

Measured while implementing: the file's triangles wind clockwise against
their normals (the counter-clockwise face normal agrees with the vertex
normals on 0.16 % of 244,791 triangles); stored tangents are geometric dP/du
and are not orthogonalised against the normal (|n.t| median 0.035, above 0.1
on 29 % of vertices).

StreamBuffer primitives: 0x4354a8 reads 12 bytes (a vec3), not a vec4; the
16-byte readers are 0x4354d1 and 0x43553c; 0x4353e9 is ReadBool, 0x435403
ReadU8.

### Block header and directory (`re/formats.md`)

Loader FUN_004a36d8 (loadblock.cpp), directory walker FUN_004a3525, header
consumer FUN_0049dd0e. The fixed header is exactly 400 bytes, read in one call
(`push 0x190` @0x4ae315).

    @0    f32 x8   bounds (two vec4)                -> LoadBlock+0x180
    @32   u32      not established (no reader found)
    @36   char[36] GUID text (no reader found)
    @72   char[255] fingerprint: C string, 3-LFSR stream cipher, key
                   "1E564E3B-D243-4ec5-AFB7"; shipped blocks decrypt to
                   "THIS IS THE DEFAULT FINGERPRINT KEY, PLEASE CHANGE IT!"
    @327  u8       2 (meaning not established)
    @328  u32      0x593F430A, never read by the loader; inferred: version signature
    @332  u32      tablesSize        directory bytes, starting at 400
    @336  u32      entry0Size        header-blob size of entry 0
    @340  u32      ioBufferSize      max(tablesSize, largest header blob)
    @344  u32      fragmentOffset    = 400 + tablesSize + sum of blob sizes
    @348  u32      fragmentSize      8
    @352  u32      numEntries
    @356  u32      numLocalized      records behind the per-language seek
    @360  u32      numStreams        records with hasStream = 1
    @364  u32 x6   languageHeaderOffset
    @388  u8       flag (meaning not established); 389-399 zero

Directory record, from 400:

    6 x u32 headerBlobSize   one per LANGUAGE slot (FUN_0045c762), not per platform
    u32 typeHash             name_hash(asset type name)
    u32 nameLen; name
    u8 hasStream
    if hasStream: 6 x { u32 offset, u32 size }   the record's OWN stream

The earlier "+1 shift" came from starting the walk at 399, a zero pad byte
that parsed as flag = 0. Type hashes named in this pass: 0x41764525
ModelEffects(ModelRes), 0x96ea413f TextureEffects(Texture), 0x6532e9b4
terrain, 0xd8c06967 pivotbook, 0x48d86c33 aipathdata. Script (TNT) classes
are read by their native base class's loader (FUN_0047e126 stores the base at
desc+0x5c; FUN_00511f96 re-types the entity).

Asset header blob: `[u32 typeNameLen][typeName][u32 bagDwords][bag]`, body at
4 + typeNameLen + 4 + 4 x bagDwords. The u32 is the property bag's length in
dwords (FUN_00511f96), not a class id: 45 Texture, 91 ModelRes, 55
TextureEffects, 96 ModelEffects.

Texture header (FUN_005382aa, descriptor FUN_00429e77): `u32 nFrames, u8
hasAnim`, then per frame 8 slots — slot 0 always, slots 1-7 each behind a
presence byte — and the source path. Descriptor 29 bytes: width, height,
format enum, 0, type (1 = 2D, 2 = cube), u8 hasAlpha, mipCount, 0. Linear
formats store every mip row padded to 4 bytes. Per-platform format table at
0x009E8F78 confirms normal maps PC 9 -> X360 10 -> PS3 7.

`.sequence` (asset FUN_0054558c, track FUN_005415bf, keys FUN_00547f4c /
FUN_00547fdb, evaluation FUN_0053aa43): grammar in `FORMATS_MISC.md`. The
first float is the duration in seconds. A track uses spline keys iff its
property type is number, vector or quaternion (FUN_00539dd9). Quaternion
properties are keyed as Euler degrees and converted q = qx.qy.qz
(FUN_00499733).

Not answerable from the PC executable: the PS3 cube-map framing and the X360
2D mip-tail offsets (the tiling code is in XBox360LibraryWrapper.dll; the 2D
bake path is compiled out).

### Still open after this pass

- Whether a non-absolute master's node turns with its GamePivot (pairs).
- The pose term added to type 1 / 3 constant track positions.
- K, D of the jiggle swing from file constants; hair; which characters
  jiggle.
- Slot role of texture slots 3 and 4; which language each of the six slots
  is; the engine role of the per-part proxy buffer; whether vertices are
  part-local; the header and object flags of `.sequence`.
- `kind` / `arg3` of command records; the block header fields at @32, @327,
  @388.
- Who sets m_tforceupdate in the game; how the engine picks a class's first
  state.
- What the engine does with the vertex colour.
