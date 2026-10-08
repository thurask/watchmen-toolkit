# Topic A — SetupNewPage / UpdatePagePlayPos (AnimationCtrl / AnimationCtrlWM)

Sources: `dump/decomp` (`fn.py`), capstone on the exe for every branch/constant quoted, registry
(`hh.py`, `reg_dump.json`), and a read-only scan of the 8 shipped `AnimationClass*.fragment` files
and 1185 `.animation` clips on the PC (device tool) for the "does it matter" counts.
Evidence tags: **[code]** read from code, **[inferred]**, **[not established]**, **[data]** corpus scan.
Machine-readable offsets: `findings/pages_offsets.json`. Scratch: `work/pages/`.

## 0. Corrections to our docs (needed to read the two functions)

Native record offsets are simply `4 × registration index` (reg_dump order) **[code]** — confirmed by a
dozen independent uses (looping, MasterOf, movement/rotation flags, events list, transitions list).
AnimationState record (`node+0x10`):

| off | prop (hash) | UI caption |
|---|---|---|
| +0x14 | m_toverridestate 0x8414609b | Is an override state (= goes on the OVERLAY stack) |
| +0x18 | m_tiswalkcycle 0x4714a2a4 | "Sync Playpos" |
| +0x1c | m_tisabsoluteanimation | |
| +0x20 / +0x24 | m_tanimationdefinesmovement / rotation | |
| +0x28 | m_tdisallowoverridelayers 0xc184ef83 | Disallow overlays |
| +0x2c | m_tallowmultipleinstances 0xe193bdf1 | Allow more than once |
| +0x30 | m_imasterof | |
| +0x34 | m_tislooping | |
| +0x38 | m_nstartplaypos | **(docs said "+0x38 = ease-in" — wrong)** |
| +0x3c | m_neaseinduration | |
| +0x40 | m_tusesoftblend 0x45bfd107 | Soft Blend To |
| +0x44 / +0x48 | m_nblendpower / m_nblendinitialpower | Curve hardness / offset |
| +0x4c | m_efallbackstate | **(docs said +0x78)** |
| +0x50 | m_nforcestaytime 0x64b5339c | Force Stay Time (0..0.3 s) |
| +0x54 | m_tholdblendvalues | |
| +0x58 | m_tnotransitiontests | |
| +0x5c | m_tforcemovementcalc | |
| +0x6c | m_etransitionlist | |
| +0x70 | m_elayerlistlist (list of lists of blend nodes) | |
| +0x74 | m_eeventlist | |
| +0x78 | m_estoredtransitstate (0x761caa4e) | |
| +0x7c | m_eanimationbehaviorlist | |
| +0x80 | m_eplayposmapper 0x96a7cade | |

Transition record: +0x08 m_eToState, +0x10 m_toverrideeasein, +0x14 m_neaseinduration, +0x18 m_toverrideplaypos,
+0x1c m_nplaypos, +0x20 m_tsupersyncpos, +0x24..+0x60 the 8 (local, remote) marker pairs, +0x64 / +0x68 runtime
lists of local / remote markers (the "unnamed" props 0x381c10c0 / 0x1d3171a6), +0x6c / +0x70 first / last local marker.
Slot record: +0x28 m_nweight, +0x2c m_nParentBlendPosition, +0x30 m_noffset ("Playpos offset"), +0x38 m_nforcestaytime.
Blend record: +0x04 m_iLayerIndex, +0x14 m_ilayerweightctrlparam, +0x18/+0x1c layer-weight interval, +0x20 m_tlayeradditive,
+0x24 m_tforcedpos ("Force Playpos=1.0"), +0x50 child slot list.
The `+0x54` / `+0x40 bit0` tests in TransitionMet (0x5c5ea4) are **entity** fields (enabled / flags), not record offsets.

`TransitToState` 0x5b4a31 **[code]**: `args = {state, ease, playpos}`; it passes
`{state, playpos, syncFlag, ease, pagelist}` to SetupNewPage. `playpos = args[2] if >= 0 else state.m_nstartplaypos`.
(Docs had args[2] as ease-in; it is the start play position. EvaluateTransitions 0x5cbbc2 passes
`ease = T.m_neaseinduration if T.m_toverrideeasein else -1`, `playpos = TransitionPlayPos(T, cur)`.)

Controller fields used below (`ctrl = [ctx+0x10]`): +0x08 m_nspeedfactor (ctrl), +0x0c page-list array (0 = body, 1 = overlay),
+0x10 AnimationData node, +0x2c "blends dirty" flag (cleared at end of StateMain 0x5b4540), +0x60 forced AnimSlot,
+0x6c per-stack event-entry lists, +0x70 speed, +0x74 dt, +0x84/+0x88/+0x8c last playpos / time played / debug-override flag.

## 1. What a page is

A page is one entry of a controller page list (body list or overlay list), created by SetupNewPage for one state.
Page struct **[code]** (written at 0x5b82e3–0x5b85e0, read throughout 0x5b56a9):

| off | meaning |
|---|---|
| +0x00 | per-layer table: for each ANIMATION_LAYER index `{AnimLayer object, slot-object list, blend node (+8), node list (+0xc)}` |
| +0x04 | list of layer indices that are populated |
| +0x08 | blend, linear 0..1 (may go to −0.01 on overlay fade-out) |
| +0x0c | ease duration in seconds (0 = instant) |
| +0x10 | playpos, normalised 0..1 |
| +0x14 | rate, playpos units per second (rebuilt every frame) |
| +0x18 | sync flag (TransitToState: both states are "Sync Playpos") |
| +0x1c | state node |
| +0x20..+0x2c | this frame's root-motion delta (vec3) and delta heading |
| +0x30 | looping (copy of state.m_tislooping) |
| +0x34 | time played, seconds |
| +0x38 | playpos at the previous event check |
| +0x3c.. | behaviour lists |

Page-list record: +0x14 force-stay timer, +0x18 "end of animation reached" flag.

### SetupNewPage 0x5b7788 (args `{state, playpos, sync, ease, pagelist}`) — **[code]** unless noted

1. `0x5b780a–0x5b783b`: if the list is non-empty, the top page already plays `state`, and `!m_tallowmultipleinstances` → return, nothing happens.
2. Body state (`m_toverridestate == 0`): if ctrl+0x98 set, ctrl+0x2c = 1 and `UpdatePageBlendsFaster(topPage, 1)` (refresh the outgoing page once);
   partner gets `command_leave_slave_mode` (0x3919f5f7) if ctrl+4; body pagelist+0x18 = 0.
   Override state: goes on the overlay list; if the **body** top page's state has `m_tdisallowoverridelayers` → return.
3. If an old top page exists: `SendEndAnimationState(oldState)` (method +0xe8), then every LEAVE_STATE (type 2) event of the old
   state and of the blend nodes of its layers is sent (`SendAnimationEvent(ev, 1.0)`, method +0xe0) and time-stamped
   (event rec+0x10 = `QueryPerformanceCounter` ms / 1000, `FUN_0041e568`, 0x9e5a60 = 1000.0).
4. `0x5b7d49–0x5b7d8f`: `pagelist+0x14 = state.m_nforcestaytime` (slot class: +0x38).
5. Re-entry (`0x5b7da0–0x5b82dd`, body states without allow-multiple): search the list for a page already playing this state.
   If found at index i: `W = blend_i × Π_{k>i}(1 − blend_k)` (blend = the AnimLayer weight, i.e. the curved value);
   if `m_tiswalkcycle` the new page inherits that page's playpos; if `W < 1` the pages above are renormalised
   (walking down from the top with `s = 1/(1−W)`: `blend_k ← b_k·s`, passed through `MathLib.InversePowerSmooth(hardness, offset)` when that
   page's state uses soft blend and AnimationData "Force Linear Transitions" (+0x20) is off; then `s ← 1` if the new value is 1 or
   `1−b_k > 0.9999` (0xa45e98), else `s ← min(1, (1−b_k)·s / b_k)`), the old page's layers/slots are destroyed and it is removed.
   The new page then starts at `blend = W` (also inverse-curved under the same condition) instead of 0.
6. New page appended: `+0x1c = state`, `+0x30 = m_tislooping`, `+0x10 = playpos`, `+0x18 = sync`, `+0x34 = 0`.
   Ease rule (`0x5b83f8–0x5b8593`, verified in asm):
   - `state.m_neaseinduration <= 0` → blend 1, ease 0 (instant) **even if the transition overrides the ease-in**;
   - first page of the body list (list empty and not an override state) → instant;
   - `ease arg == 0` → instant;
   - else `blend = W` (re-entry) or 0, `ease = arg if arg > 0 else state.m_neaseinduration`.
7. Layers (`0x5b86c8–0x5b8b5f`): for **each inner list** of `m_elayerlistlist` with n > 0 entries, **one** blend node is picked with
   `FUN_0047b025` → `FUN_0047aa2e(n)` = Mersenne-Twister `rand % n` (generator at [0xe12df8]); an `AnimLayer` object is created
   for it at layer index `blend.m_iLayerIndex`, additive if `m_tlayeradditive`, AnimLayer weight = page blend; for each child slot of
   the blend node an AnimSlot (class string 0xa418a0) is created, its clip set (`FUN_00593ac3`) and its playpos property
   (0x67f02746) set to the raw `playpos` argument.
8. Events (`0x5b8cbf–0x5b9475`): for the state's `m_eeventlist` and each layer blend node's event list:
   type 0 PLAY_POS and type 3 TOTAL_PLAY_TIME → appended to ctrl+0x6c[stack] as `{event, fired, pending}`, with `fired = 1`
   when type 0 and `event.playpos < page.playpos`; type 1 ENTER_STATE → sent immediately (`SendAnimationEvent(ev, 0)`) and time-stamped.
   Enum values from the registration at 0x5e54e0–0x5e5516: PLAY_POS 0, ENTER_STATE 1, LEAVE_STATE 2, TOTAL_PLAY_TIME 3.
9. Tail: behaviours, absolute/physical mode messages, dual-animation partner messages (0x5b9afb, already documented),
   first body page forced to blend 1; if the new top state has `m_tholdblendvalues` → one `UpdatePageBlendsFaster(top, 1)`; ctrl+0x2c = 1.

No page-count cap exists in SetupNewPage. **[code]** (The interpreter's cap of 8 has no counterpart here; neither `DeleteOldPages` 0x5b9e4c nor `DeleteOneOldPage` 0x5ac8a6 tests a count. **[code]**)

## 2. How play position advances

Frame order (Update 0x5b4613, per stack) **[code]**: speed → EvaluateTransitions → force-stay timer → UpdatePageBlendsFaster per page →
DeleteOldPages → SynchronizePages → ClearAnimationPosEvents → UpdatePagePlayPos per page → CalculateVelocity.

**dt and speed.** `ctrl+0x74 = [0xe14304]` (frame dt; `[0xe14300]` when ctrl+0x14 is set) — StateMain 0x5b417b.
`ctrl+0x70 = class.m_nspeedfactor (prop idx 2 of the class entity) × GetGameSpecificSpeedFactor() × ctrl.m_nspeedfactor`
(0x5b4636–0x5b4680; GetGameSpecificSpeedFactor 0x5ab837 = `ctrl.m_ncharacterspecificspeedfactor` (+0x10c, default 1.0) × a combo/character factor).
All six shipped classes that carry the prop have m_nspeedfactor = 1.0 **[data]**.

**Rate.** `UpdatePageBlendsFaster` 0x5b4bd6 zeroes `page+0x14`; `SetAllSlotBlends` 0x5b4ef7 (called per layer whose weight is > 0) adds, **only for
the first populated layer of the page** (arg[2] == 0), for each slot:

    page.rate += ctrl.speed × slot.speed × slot.weight / clip.duration        (0x5b5193–0x5b51d0)

`slot.weight` = AnimSlot+0x80, `slot.speed` = AnimSlot+0x84 (or +0x134 / +0x64 for the two other slot kinds),
`clip.duration` = `[slot+0x94]+0xa0` = clip header f32 at offset 4. So the rate is the **weight-blended sum of 1/duration**, not 1/first-duration.
Where AnimSlot+0x84 is written (per-slot speed, default) is **[not established]**.

**Advance** (UpdatePagePlayPos 0x5b56a9):
- `page.timePlayed += dt` (0x5b5710–0x5b5719).
- Forced-slot case (body list, top page, ctrl+0x60 set): `playpos = slot.time / slot.duration` (`FUN_00591920`); the forced slot is dropped once that is ≥ 1.
- AnimationData debugger override (`rec+0x34` "PLAY_POS" flag): `playpos = rec+0x38` (editor scrubbing).
- Normal (0x5b5876–0x5b58a4): `playpos += min(page.rate, 6.6) × dt`. The clamp is the double at **0xa45e90 = 6.599999904632568**.
- If `playpos > 1.0` (strict):
  - non-looping: `playpos = 1.0`. If top page — body stack: when `blend >= 1`, no behaviours and character[+0x1f0] == 0, ctrl+0x30 = 0;
    overlay stack: once (pagelist+0x18 == 0) `SendEndAnimationState` and the LEAVE_STATE events. Then `pagelist+0x18 = 1`.
  - looping: if the state is absolute, `SendAbsoluteAnimationLooped` (method +0xe4); if top page, each type-0 event entry that has **not** fired this
    lap gets `pending = 1` and all `fired` flags are cleared; then `while (playpos > 1.0) playpos -= 1.0` (double 0xc3cc48).
- Events (top page only): `CheckPlayPosEvents(entry, page)` for every entry, then `page+0x38 = playpos`.
- Effective playpos `e = playpos`, or `mapper.command_get_playpos(playpos, timePlayed)` (0xdcc67d69) when `state.m_eplayposmapper` is set:
  `AnimationPlayPosReverse` 0x5ca657 returns `−playpos`; `AnimationPlayPosSequencer` 0x5ca6c7 evaluates a property sequence.
- Per layer, per slot with weight > 0: `slotPlaypos = slot.m_noffset + e`, wrapped into [0,1] by ±1.0 loops; if the layer's blend node has
  `m_tlayeradditive && m_tforcedpos` → 1.0. Written with property 0x67f02746. For layers 0..9 with weight > 0 the same block also extracts
  root-motion delta and heading from the GamePivot track between the current and the next-tick time (the ~1 kB of quaternion code).
- Page blend (tail, 0x5b7560–0x5b7690): `ctrl+0x2c = 1` while blend < 1. Normally `blend += dt/ease` while `blend < 1 && ease > 0`, else 1.
  Overlay top page that is non-looping and has reached playpos ≥ 1: `blend −= dt/ease`, floored at −0.01 (0xa45e88 / 0x9fd4cc).
  Overlay page while the body top state has `m_tdisallowoverridelayers` or AnimationData "No Override Layer" (+0x1c): `blend −= dt/ease`
  (or 0 if ease ≤ 0). Finally `blend = min(blend, 1)`. DeleteOldPages 0x5b9e4c always deletes index 0: once per page below the highest page with blend ≥ 1; and a page with blend < 0 at index k removes pages 0..k−1 and then itself (the last consequence is inferred from the decompiled loop).

**Event firing** (CheckPlayPosEvents 0x5b51f3) **[code]**: TOTAL_PLAY_TIME (3): compares `event.m_nplaypos` with `page.timePlayed` and fires once (the comparison direction is garbled in the decompilation; "fires when the time is passed" is **[inferred]**).
PLAY_POS (0), normal play: fires when `event.m_nplaypos < page.playpos` and not yet fired this lap — a latch, not a `(last, cur]` window;
together with the loop rule above an event skipped by a wrap still fires (as `pending`) on the next check. Only in the debugger-override
mode is a window used: `lo = min(cur, last)`, `hi = max(cur, last)` (`lo = −0.0` if `lo == 0 < hi`, 0xa3eba4), fire if `lo < p < hi`.
Every fire calls `SendAnimationEvent(event, page.blend)` and stamps event rec+0x10.

**Force-stay timer** (Update 0x5b46xx + EvaluateTransitions 0x5cbbc2) **[code]**: a wanted transition is deferred while `pagelist+0x14 > 0`;
Update sets `pagelist+0x14 = (EvaluateTransitions returned non-zero) ? timer − dt : 0`. The timer is `m_nforcestaytime` of the entered state.
It is 0.0 in every shipped state (1207 states) **[data]**, so the engine never defers.

**No-transition-tests** (0x5cbbc2, `ctrl+0x2c == 0 && state.m_tnotransitiontests`): transitions are not evaluated while `playpos < 1.0`
and **are** evaluated once it reaches 1.0.

## 3. How blends between pages are weighted

- Per page, `UpdatePageBlendsFaster` sets the weight of the page's AnimLayer child object (`[layer+0x48]`) to `b`, where
  `b = PowerSmooth(blend, m_nblendpower, m_nblendinitialpower)` **only if** `state.m_tusesoftblend && blend > 0 && !AnimationData.ForceLinearTransitions`,
  else `b = blend` (0x5b4c20–0x5b4c98). Layers ≥ 10 are zeroed when AnimationData "No Action Layers" (+0x14) is set and the bit `1 << (layer−10)` is clear in +0x18.
- Layer weight = `MapToInterval(values[blend.m_ilayerweightctrlparam], start, end)` (FUN_0077a4d8) × 1.0; slot weights come from
  `AnimationBlend.command_evaluate_blends` (0x23194f11, handler 0x59e905) and are written with `FUN_00593d98`; they are only recomputed for the
  top page and only if `ctrl+0x2c || blend < 1 || !m_tnotransitiontests`, and never when the state holds blend values.
- Stack composition `share_i = b_i × Π_{k>i}(1 − b_k)` is what the re-entry code computes explicitly (SetupNewPage step 5) **[code]**; that this is also
  what the kernel AnimLayer stack does is **[inferred]** from it.
- Within one layer the kernel normalises by the sum of slot weights and blends with hemisphere-corrected nlerp
  (`FUN_0059124d` accumulate with sign flip, `FUN_00591333` / `FUN_005951c2` divide and renormalise) **[code]**.
- Blend is advanced **after** the weights of the frame were applied (UpdatePageBlendsFaster precedes UpdatePagePlayPos), so a page created in frame N
  has weight `b(0)` in frame N and `b(dt/ease)` in frame N+1, while its playpos has already advanced once in frame N.
- Sync pages (`SynchronizePages` 0x5ac387): walking down from the top, a run of pages with `+0x18` set (plus the page under the run) gets one common
  rate `1 / Σ_j (w_j / rate_j)` with `w_top = blend_top`, `w_next = blend_next × (1 − blend_top)`, …, remainder to the bottom page — a weight-blended **period**.
- TransitionPlayPos 0x5ac1aa: override → `T.m_nplaypos`; else if `!m_tsupersyncpos` → −1 (use the state's start playpos); else with the marker lists
  built by `UpdateSuperSync` 0x5fa582 (markers taken in order, **stopping at the first negative local marker**, only the local value is tested, then
  bubble-sorted): `i` = first index with `local[i] >= playpos`; `i == 0` → `remote[0]`; `i == n` → `remote[n−1]`; else
  `MapIntervalToInterval(playpos, local[i−1], local[i], remote[i−1], remote[i])`. TransitionMet additionally requires
  `local[0] <= playpos <= local[n−1]` (rec+0x6c / +0x70) for a super-sync transition.

## 4. Clip time → key index / interpolation

**[code]** `FUN_00593d74`: `slot.time = clip.duration × slotPlaypos`. `FUN_00591975` (0x591975, asm read):

    t    = clamp(time, 0, duration)                 # [anim+0xa0]
    f    = (keyCount − 1) × t / duration            # [anim+0xa8], float32
    k0   = floor(f);  k1 = ceil(f);  frac = f − k0

`FUN_00592f93` / track vtable slot 1: `frac < 1e-5` (0xa40400) → key k0; `frac > 0.99999` (0xa406b8) → key k1; else interpolate.
Track classes (factory `FUN_00592e87`, vtables 0xa404b0 / 0xa40450 / 0xa40514): type 0 = const quat + int16×3/1000 positions (linear);
type 1 = const position + int16×4/10000 quats (lerp, `q1 ← −q1` if dot < 0, renormalise; identity if |q|² < 1e-5);
type 2 = 7×int16 (`FUN_004b26ef`: position lerp + the same nlerp); type 3 = constant. Divisors read from the exe: 0x9e5a60 = 1000.0, 0x9eb358 = 10000.0.
One key index pair is used for all tracks; `keyRate` and `frameRateScale` are not read by the sampler.
`anim vtable+0x18` (0x593034) returns true only for track types 0 and 2; for types 1 and 3 `FUN_00594cac` (0x594d33–0x594d49) **adds** the
position of the pose object passed down by the layer evaluator to the track's constant position (`FUN_00591225`). That pose object being the
skeleton's reference local pose is **[inferred]**.

## 5. Comparison with our Python

### bake_v4.py

| # | item | engine | ours | verdict |
|---|---|---|---|---|
| B1 | time → key | `f = (keyCount−1)·t/dur`, floor/ceil, lerp | `t = linspace(0, nf−1, F)`, floor / +1, lerp | **agree** |
| B2 | key count per track | header keyCount for every keyed track | `nf = max(track lengths)`, nearest-index resample if a track differs | **agree in practice**: 0 of 56,360 keyed tracks in 1185 clips differ from the header count **[data]**; the resample path is dead code |
| B3 | quaternion interpolation | pairwise sign flip, lerp, normalise | cumulative sign continuity, lerp, normalise | **agree** (same rotation) |
| B4 | snap at frac < 1e-5 / > 0.99999 | yes | no | negligible, no change |
| B5 | duration / fps | time = playpos × header duration | `fps = (F−1)/dur` | **agree**; frameRateScale unused by both |
| B6 | type 1 / type 3 constant position | `pos = const + reference local pos` | `const` alone if \|const\| > 1e-6, else `tloc` | **differs** when const ≠ 0 and the bone's rest local position ≠ 0 |

B6 scope **[data]**: const ≠ 0 on 577 of 64,567 type-1/3 tracks; 435 of them are GamePivot / interact (rest local = 0, no effect).
Affected character bones: `Bip` (23 tracks, rest local offset up to 0.094 m depending on skeleton) and `Attach RHand`; the rest are prop bones.
Proposed fix (`bake_v4.walk` + `bake`): have `walk` return whether the track carries position keys (`t in (0, 2)`); in `bake`, for a track
without position keys use `POS[k] = tloc[k] + const` (broadcast), keeping today's `tloc` when const is zero. Because the identity of the added
pose is inferred, check one clip first (`BS2_COM_DMG_roof`, bone `Bip`, const (0, −0.8647, 0)) against a capture.

### anim_state_machine.py

| # | function | engine | ours | fix |
|---|---|---|---|---|
| S1 | `tick` playpos rate | `speed × Σ w_i·speed_i/dur_i` over the slots of the first populated layer, clamped to 6.6 /s | `dt / duration` of the first slot found | compute `rate` per tick from `_slot_pos_weights` of the first blend node in layer order; `pg.playpos += min(rate * env.speed, 6.6) * dt`; add `Env.speed = 1.0`. 249 states have slots with different durations **[data]** |
| S2 | `tick` / `transit` walk-cycle sync | start playpos inherited from the top page and common rate `1/Σ(w/rate)` when both states are `m_tiswalkcycle` | not modelled | in `transit`: if `cur` and both states have `m_tiswalkcycle` and no playpos override → `pp = cur.playpos`, `page.sync = True`; in `tick` after S1 apply the SynchronizePages formula to the run of sync pages. 62 states **[data]** |
| S3 | `tick` loop wrap | `while playpos > 1.0: playpos -= 1.0`; non-loop clamps when `> 1.0` | `>= 1.0` and `%= 1.0` | use strict `>` and subtraction (playpos 1.0 must stay 1.0) |
| S4 | `tick` transition defer | deferred while the force-stay timer (`m_nforcestaytime`, 0 in all shipped data) is > 0 | deferred while `0 < top.age < top.ease_in` | delete the ease-window test; keep a per-stack `stay` timer set in `transit` to `state.p('m_nforcestaytime', 0)` and decremented only on ticks where a transition was wanted |
| S5 | `tick` `m_tnotransitiontests` | no evaluation while playpos < 1, evaluation at playpos ≥ 1 | never evaluated | condition becomes `not notests or top.playpos >= 1.0`. 192 states **[data]** |
| S6 | `transit` same state on top | no new page unless `m_tallowmultipleinstances` | always pushes | early return when `stack and stack[-1].state is state and not state.p('m_tallowmultipleinstances')` |
| S7 | `transit` state already lower in the stack (body, not allow-multiple) | old page removed, pages above renormalised, new page starts at the old page's share `W`, playpos inherited if walk cycle | pushes a second page from 0 | implement step 5 of §1 (a `Page.blend0` start value plus removal); at minimum start the new page at `W` and drop the old one |
| S8 | `transit` ease-in | instant if `state.m_neaseinduration <= 0` (transition override ignored), if first body page, or if override == 0 | override always wins | `ease = 0 if state_ease <= 0 or first_body_page else (t_ease if override and t_ease > 0 else (0 if override else state_ease))`. 35 zero-ease states, 572 overriding transitions **[data]** |
| S9 | `Page.blend` curve | curve only when `m_tusesoftblend` | always applies hardness/offset | return the linear value unless `state.p('m_tusesoftblend')`. 17 states have a non-unit curve with soft blend off **[data]** |
| S10 | weights vs. advance order | weights use the blend from before this frame's advance | `slot_weights()` after `tick` sees the advanced age | in `tick` store `pg.applied_age = pg.age` before `pg.age += dt` and let `blend` use it (one-frame lag, playpos unchanged) |
| S11 | `sync_remap` | stop at first negative local marker; clamp to `remote[0]` / `remote[n−1]` outside; valid only for `local[0] <= pp <= local[n−1]` | all pairs with both ≥ 0, extended with (0,0) and (1,1), no gating | rewrite per §3; in `get_valid_transition` skip a `m_tsupersyncpos` transition whose window does not contain the top playpos. 145 transitions **[data]**; e.g. markers (0.75→0.24, 1.0→0.48): ours maps 0.5 → 0.16, the engine refuses the transition |
| S12 | `Page.slots` layer variants | one random blend node per inner layer list | all blend nodes summed | group blend nodes by `m_ilayerindex`, pick one per group at page creation (seedable RNG). 16 states, e.g. EnemyBig "Dead" has 5 × MOTION_LAYER_1 **[data]** — that inner lists are grouped by layer index is **[inferred]** |
| S13 | overlay pages | not created if the body top state disallows overlays; fade out (`blend −= dt/ease`, removed below 0) when finished or disallowed | pushed and kept | add the two fade-out branches of §2 and the creation gate |
| S14 | slot play position | `wrap01(m_noffset + mapper(playpos))`; 1.0 for additive blend with `m_tforcedpos` | only `page.playpos` exposed | add `Page.slot_playpos(blend, slot)`; 20 slots have a non-zero offset **[data]**; no shipped state uses a playpos mapper |
| S15 | events | latch semantics of §2 | not implemented | optional `Page.events(dt)` following §2 if event output is wanted |
| S16 | stack cap | none in SetupNewPage | cap 8 | harmless once S6/S7 and DeleteOldPages are in; can be removed |

Agreeing parts: DeleteOldPages rule (highest fully blended page occludes the ones below), stack share formula, criteria/transition ordering, linear blend timer `dt/ease`, blend curve function itself.
