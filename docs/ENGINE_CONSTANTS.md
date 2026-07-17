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
viable recovery source. Snapshot: claude/work_E/wlib_snap_20260709_engineconstants.tgz.
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
jiggle_pass.py: now falls back to engine-derived AR(2) coeffs when
jiggle_params.npz is absent (fresh-install bug fixed: the npz lived only in
claude/work_B; now also in wlib/). Capture-fit npz stays preferred when present.

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
Raw capstone disasm of KapowMultiDEDRM.exe was required. Caption strings are
pushed as code immediates (PUSH imm32), findable by scanning .text for the
string VAs — grep of decomp .c files misses them.

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
- m_ttestonentryonly: if set and not entering, returns cached/true early ([esi]=1 path
  @0x5c58a3 keyed on state-entry flag [ctx+0x38] compare).
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

# Session notes (2026-07-09 decomp session)
- Workflow that works: scan exe bytes for string-VA immediates / prop-hash
  immediates with Python+capstone; Ghidra decomp is unreliable for any fn with
  the SEH prologue (14,910 fns but MANY key ctors/handlers are 10-byte stubs).
- kapow_hash confirmed for engine PROPERTY hashes too (m_nbreast* etc.), not
  just asset records: hash = bit-CRC32(UPPERCASE name).
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
Semantics (2026-07-09i/j, sections above + jiggle-physx memory):
- NxD6Joint: Y/Z translation LOCKED -> angular pendulum. k -> Swing1+Swing2
  LimitSpring ([d6+0x100]/[+0x120]); d -> LimitDamping ([+0x108]/[+0x128]).
  Swing1LimitValue=45deg, Swing2=0deg (always-engaged restoring spring).
  Damping is ABSOLUTE torque-domain (NxJointLimitSoftDesc), NOT a ratio.
- m_n*distancelimit = GAME-side position clamp (CharacterAddonCtrl update
  0x6563a0); setup 0x6574cd. Both are decomp GAPS -> use exe_dis.py.
- PhysX 2.x soft-limit: tau = spring*err + damping*vel while limit engaged;
  gravity + parent-bone acceleration drive the pendulum; dt = frame tick.
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

## Tooling
claude/work_E/exe_dis.py (capstone CLI; pip install capstone
--break-system-packages) — ALWAYS use it over Ghidra for SEH-prologue fns
(CharacterAddonCtrl setup/update are such gaps). reg_scan.py = registration
scanner (regenerates wlib/reg_dump.json).

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

## Registration scan (claude/work_E/reg_scan.py -> reg_dump.json)
Scans exe for call sites of:
  0x47e126 create class (name, classId, ?, baseName)
  0x47fde4 register prop (hash, defaultVA, uiCaptionVA, 3, X)
  0x47eccc register command (nameVA, argc, ?, hash, handlerVA)
441 classes, 4976 props, 6630 commands. Prop hash = kapow_hash(UPPER(m_name))
(verified: m_neaseinduration=0xc457385c, m_nstartplaypos=0x125d3ff7).
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
Execution model = PAGES: each state entry pushes a new page (its slot set);
pages cross-fade by page blend; slot weight = m_nweight * pageblend
(UpdatePageBlendsFaster: FUN_0059397a(slot, w); slots >#9 maskable by
[rec+0x18] bitmask when [rec+0x14] set).

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
StateGroupCriteriaMet 0x5c6002: member2 (single criteria) evaluated if
present, then member1 = criteria LIST — ALL must pass (AND). Each criteria
evaluated by its class-method [criteria class rec + 0xc]+0x24 via thunk
0x479874(handlerVA, ctx, args) which sets script ctx global 0xe12d9c.

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

## TransitToState FUN_005b4a31 (ghidra part_0021.c:11791)
ease_in = args[2] if args[2] >= 0 else state_rec+0x38 (m_neaseinduration);
soft-blend variant flag from target-state rec (+0x18/+0x10 chain) selects
mode 1 w/ easein from top page state when overriding. Then invokes class
method [class rec+0xfc]+0x24 (native transit) with
{state, args[1], ease_in, softflag, page}.

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
.fragment: reg_dump prop hashes resolve 250 distinct key_XXXX (=56% of all
  339,574 unresolved prop instances; mapping written to
  claude/work_E/prop_names_from_reg.json — feed into kapow_fragment key
  dict). Remaining unresolved keys are mostly small-int creation-record
  keys (key_00000000/2/6/7), different keyspace. Type guesses 'raw4?' etc.
  remain heuristic (seen: sync marker 8 local misread as vector?).
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

## .pb (kapow_props) — CLOSED
File prefix (the nskip dwords) = [u32 bankId (sequential 0x16269ef8..fa)]
[u32 0x2964 version][u32 nblocks-1]. Zero trailing bytes on all 3 files.

## .sequence — header CLOSED
[f32 DURATION seconds (was mislabeled version; 0.3..60.0)][u32 flags 0/1/4]
[u32 nobjects (verified vs parse on 193/194 files)]. Object header pad
between path and classname = always 8 zero bytes. OPEN: flags semantics,
key tangent dwords (kept raw), parser misses 1 object in 15 files (resync).

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

## fragment key dict — no merge needed
All 429 caption-recoverable m_* names were ALREADY in kapow_fragment_keys
keytable (4564 entries). Sync-marker true names NOT brute-recoverable
(hash pairs 0xee2a40XX/0x4cadfbXX differ per digit); keep key_XXXX +
claude/work_E/prop_names_from_reg.json side lookup (hash->class/caption/
default for all 3602 registered props).

## FORMAT SCOREBOARD after this session
CLOSED: .animation, .pb, block_h_z, block_s_z, .naz (modified ZIP,
round-trips), .sequence header/object framing.
NEAR: .fragment (lossless, 56% unknown-key instances explainable via reg
dump), .model nodes (exact for joint-only; mesh tails identified).
OPEN (bounded): joint type4/5 blobs, meshbuffer internals, .sequence flags +
tangent dwords, 2 asset-type hash names, block_h_z magic 0x593F430A meaning.

# 2026-07-09q — exe constants promoted into wlib
Policy (user): exe-derived constants are legitimate library data. Added
wlib/engine_schema.py + wlib/reg_dump.json + wlib/prop_names_from_reg.json:
defaults(class) (fragments omit default-valued props!), prop_info/caption
for unresolved key_XXXX hashes, BASE_FPS. reg_scan.py stays in work_E as the
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

## Deliverable
wlib/jiggle_d6.py — apply_jiggle(P,fps,bind, mode='engine'|'ratio'|'absolute',
props=, extract_root=), same interface as jiggle_pass; reads PhysicsWorld
props from GameEssentials.fragment.json, geometry from bind npz (r=tb[bone]),
sim at 60Hz, engine radial clamp (replaces tanh).  Validation:
claude/work_E/validate_jiggle_d6.py.
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
+ clip alignment (work_B/which_clip.py needs its /tmp/oracle.npz rebuilt via
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

## TransitionMet FUN_005c5ea4 — READ
Confirms method: gates on target-state flags (rec+0x54 enabled, rec+0x40 bit0),
optional PLAY_POS window check ([edi+0x6c]/[edi+0x70] = lo/hi play-pos bounds
vs current normalized pos [state+0x10]), then evaluates the criteria LIST via
per-criterion method [class+0xc]+0x24 through thunk 0x479874 (ctx global
0xe12d9c). Returns 1 only if all pass. Matches interpreter's transit_met.

## SEH gaps read (capstone): playpos + page setup
UpdatePagePlayPos 0x5b56a9: playpos advance = state.playpos += ctrl.dt
([ctrl+0x74]); per-slot rate = [slot+0x14] (m_nspeed) * dt + [slot+0x10]
offset; loop length from anim resource duration [res+0x130] (or getter
0x591920); wrap when normalized pos >= 1.0 (fld1;fcomp). Matches interpreter.
SetupNewPage 0x5b7788: allocates+zeroes a page struct (rep stosd), pushes it
(0x50030f), copies the entry state's slot set iterating [rec+0x14]/[rec+0x1c].
Matches interpreter's page stack.
=> Both SEH state-machine functions confirm anim_state_machine.py; no change.

## Format residue — CHARACTERIZED (low value, not blocking)
- EmbeddedJointNode joint types: clean parse_node_aux tiling across all 7
  skeletons yields ONLY type 7 (88 records, blob=0) = the jiggle/twist anchors
  (SOLVED). Types 4/5/6 seen only in a permissive raw scan that is dominated
  by false positives (the "blobs" decode to mesh material-binding "ObjectNN"
  records, i.e. tag collisions). Genuine type 4/5/6 are ragdoll constraint
  joints in a handful of props/models -> NOT part of clip playback (ragdoll =
  runtime PhysX death), NOT worth reversing for the file-only anim pipeline.
- .sequence flags{0,1,4}: deserialize is a ctor chain (0x543729->0x550905->...)
  not a single readable header parse; flags select a runtime playback mode
  (loop/override), a RUNTIME concern. decode_sequence.py already keeps them raw
  + parses tracks losslessly. No decode blocker.
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

# 2026-07-12c — PhysX 2.8 DOC MINED (PhysXDocumentation.pdf, workspace root)
Text dump: pypdfium2 -> /tmp/physxdoc.txt (554 pp). Key confirmations + finds:
- "Joint springs are implicitly integrated within the solver" (Solver Accuracy
  Tips) => direct doc backing for jiggle_d6.solver_soften.
- setTiming(maxTimestep=1/60, maxIter=8, NX_TIMESTEP_FIXED) defaults; game
  sets rate 60 / maxIter 3. Substep = maxTimestep (doc); our empirical
  dts=1/120 softening fit stays an EFFECTIVE description.
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

# NEXT SESSION HANDOFF (2026-07-12c close, supersedes 07-12 close)
1. ANISOTROPIC jiggle_d6 mode: project deviation onto joint-frame swing axes
   (parse_node_aux type-7 quats, now correct); spring+damp K,D on swing2
   component only; swing1 free (limit 45deg, rarely hit under distance clamp);
   validate vs AR(2) + captures. This may close the x1.7 amplitude gap.
2. Raw-capture window compare (rebuild work_B alignment oracle) — final
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
   NAME-PROXY RIDE designed-but-unapplied in work_D/NTO_FACE_FINDINGS.md:
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
  byte-identical to the DEDRM exe. Functional check vs canonical 20260708
  pb-family JSONs (297 files): 202 byte-identical, 3 case-only, 92 strictly
  better (more hashes named), 0 regressions.
- reg_dump.json: reg_scan ported into wlib (Ghidra-free — .rdata string map
  replaces strings.tsv; capstone; refuses packed .text). Output byte-true;
  shipped json only differs by Ghidra's trailing-space trimming.
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
