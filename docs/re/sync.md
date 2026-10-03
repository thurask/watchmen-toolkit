# Transition sync markers and the start play position of a target state

Target: `KapowMultiDEDRM.exe`. Status words: **read** = traced in code (decompilation, with the instructions or
constants named checked in the exe bytes), **inferred**, **not established**.

## Summary

- A transition has 8 (local, remote) marker pairs. Both are **normalized play positions 0..1** (not seconds or frames).
  *local* = play position in the state being left; *remote* = play position in the state being entered.
- "Sync PlayPos?" does two things, both **read**:
  1. it **gates** the transition: it can only fire while the outgoing play position is inside
     [smallest local marker, largest local marker];
  2. it **chooses the target's start play position** by piecewise-linear mapping local -> remote, clamped to the
     first/last remote marker outside the marker range.
- It is a one-shot start-position choice, not a time warp. Nothing re-reads the markers after the new page is created.
  Continuous phase locking is a different feature: the *state* flag `m_tiswalkcycle` (caption "Sync Playpos"), handled by
  `SynchronizePages`.
- The toolkit's `sync_remap` differs from the engine in three ways (section 6).

## 1. Properties of AnimationTransition(WM) — read

Registration: `AnimationTransitionWM` 0x60d524, runtime `AnimationTransition` 0x60dcb5 (class id 0x15a, class object global
0xe16f18). Each property is `FUN_0047fde4(hash, default, uiString, 3, classId)`; the instance record holds one 4-byte slot per
property in registration order (confirmed by every offset used below).

| rec | hash | name | type | default | UI caption | meaning |
|---|---|---|---|---|---|---|
| +0x00 | 0x294067e5 | `m_ianimationsystemtype` | integer | "4" | hidden | node kind; 4 = `ANIMATION_SYSTEM_NODE_TYPE___ANIMATION_TRANSITION` |
| +0x04 | 0xb17ad901 | `m_ecriterialist` | list(Entity) | "" | hidden | criteria, all must pass (`TransitionMet`) |
| +0x08 | 0xd8beb470 | `m_etostate` | Entity | — | Transition to state | target state or state group |
| +0x0c | 0x6ed6aa4d | `m_tfallback` | truth | false | Fallback transition? | considered only in the fallback pass (section 5) |
| +0x10 | 0x1a6a9fce | `m_toverrideeasein` | truth | false | Override Ease In? | use +0x14 instead of the target state's ease-in |
| +0x14 | 0xc457385c | `m_neaseinduration` | number | 0.0 | Ease In Duration (slider 0..2) | blend duration, seconds |
| +0x18 | 0x48ea1c56 | `m_toverrideplaypos` | truth | false | Override Start PlayPos? | use +0x1c as the start position |
| +0x1c | 0x02865508 | `m_nplaypos` | number | 0.0 | Start PlayPos (slider 0..1) | start play position, 0..1 |
| +0x20 | 0xa59f1057 | `m_tsupersyncpos` | truth | false | Sync PlayPos? | enable the markers |
| +0x24 + 8(n-1) | 0xee2a40a0, ..60, ..e0, ..00, ..80, ..40, ..c0, ..30 | `m_nsupersynclocal1` .. `8` | number | -1.0 | Sync marker n (local), slider 0..1 | play position in the outgoing state |
| +0x28 + 8(n-1) | 0x4cadfb2b, ..eb, ..6b, ..8b, ..0b, ..cb, ..4b, ..bb | `m_nsupersyncremote1` .. `8` | number | -1.0 | Sync marker n (remote), slider 0..1 | play position in the target state |
| +0x64 | 0x381c10c0 | `m_nsupersynclocal` | list(number) | "" | hidden | sorted local markers, built at init |
| +0x68 | 0x1d3171a6 | `m_nsupersyncremote` | list(number) | "" | hidden | remote markers in the same order |
| +0x6c | 0x52340773 | `m_nsupersyncmin` | number | "" | hidden | smallest local marker, set at init |
| +0x70 | 0x5234171b | `m_nsupersyncmax` | number | "" | hidden | largest local marker, set at init |
| +0x74 | 0xdfc5d866 | `m_eeventlist` | list(Entity) | "" | hidden | events sent when the transition fires (`SendAnimationEvent`, EvaluateTransitions 0x5cbbc2) |
| (WM only) | 0xc7052c19 | `_bdebugpanel` | button | — | Animation Panel | editor |

Marker names: the eight local hashes differ only in the last byte in exactly the pattern of a trailing digit 1..8, and
`m_nsupersynclocal1..8` / `m_nsupersyncremote1..8` reproduce all 16 hashes with the engine's hash rule (`& 0xDF` on every byte,
`FUN_00423ce8`; see enums.md). The marker default string is "-1.000000" (0xa48690).
The five hidden properties are the "from-filter" candidates of `ENGINE_CONSTANTS.md`; they are not a from-filter, they are the
runtime cache of the markers. They are never stored in shipped fragments because they are rebuilt at init.

There is **no blend-curve property on a transition**. The curve belongs to the target state (`m_tusesoftblend` "Soft Blend To",
`m_nblendpower` "Curve Hardness", `m_nblendinitialpower` "Curve offset"); `AnimationData.m_tdisallowpowersmooth`
("Force Linear Transitions") overrides it globally. A transition can only override the duration.

Other methods of the class: `UpdateSuperSync` 0x5fa582, `BubbleSort` 0x5ed5a2, `Init` 0x5fa96c, `AddToClosestState` 0x5ed6dc,
`command_add_criteria` 0x5f9c49, `command_add_event` 0x5f9abe, `initialize_external` 0x5f9b13.

## 2. UpdateSuperSync 0x5fa582 — read

Called from `Init` (0x5fa96c: `AddToClosestState`, then `UpdateSuperSync`). It takes no part in the per-frame update.

```
clear list +0x64 ; clear list +0x68
if m_tsupersyncpos:
    for n = 1..8:
        if local_n < 0: break            # markers must be filled contiguously from 1; remote_n is not tested
        append local_n to +0x64 ; append remote_n to +0x68
for n = count+1 .. 8: local_n = remote_n = -1.0      # constant at 0x9e6a8c = -1.0f
if count > 0:
    BubbleSort(+0x64, +0x68)             # ascending by local, remote swapped in step (0x5ed5a2)
    m_nsupersyncmin = local[0] ; m_nsupersyncmax = local[count-1]
```

So the authored order of the markers does not matter (shipped data is often unsorted, e.g. `(0.33->0.57),(0.17->0.42)`).
The `(ctx+0x3c)==0 || (ctx+0x44)!=0` test around the last step is the engine's "no script error pending" check that follows
every nested call; it is not a mode switch.

## 3. Where the markers are used — read

### 3a. Gate: `AnimationLib.TransitionMet` 0x5c5ea4

```
transition enabled, target (rec+8) enabled, else fail
if m_tsupersyncpos (rec+0x20):
    p = play position of the top page of the current stack (page+0x10)
    if p < m_nsupersyncmin (rec+0x6c) or p > m_nsupersyncmax (rec+0x70): fail
every criterion in m_ecriterialist must pass
```

`ENGINE_CONSTANTS.md` describes this as an "optional PLAY_POS window check ([+0x6c]/[+0x70])" without saying where the window
comes from. It is the marker range.

### 3b. Start position: `AnimationCtrl.TransitionPlayPos` 0x5ac1aa

Arguments: (node, current play position of the top page). Returns a play position, or -1.0 for "no opinion".

```
node is AnimationTransition (class 0x15a):
    if m_toverrideplaypos (rec+0x18): return m_nplaypos (rec+0x1c)          # 0x5ac205
    if not m_tsupersyncpos (rec+0x20): return -1.0                          # 0x5ac24b, 0x5ac377
    L = rec+0x64 (sorted), R = rec+0x68, n = len(L), p = current play position
    i = first index with L[i] >= p                                          # loop 0x5ac285-0x5ac2bb
    if i == 0 (or n == 0):  return R[0]                                     # 0x5ac2e0
    if i == n:              return R[n-1]                                   # 0x5ac2c6
    return MapIntervalToInterval(p, L[i-1], L[i], R[i-1], R[i])             # 0x5ac2f2-0x5ac36b
node is AnimationData (class 0x124): if its debug "PLAY_POS" override (rec+0x34) is on, return rec+0x38
node is AnimationEvent (class 0x123): return its m_nplaypos (rec+4)
```

`MathLib.MapIntervalToInterval` 0x77a579: `c + (d - c) * clamp((x - a) / (b - a), 0, 1)` (clamp constants 0.0 and 1.0 at
0xc3cc18 / 0xc3cc48).

Formula, with sorted markers (l_0, r_0) .. (l_{n-1}, r_{n-1}) and outgoing play position p (the gate guarantees l_0 <= p <= l_{n-1}):

```
start = r_{i-1} + (r_i - r_{i-1}) * (p - l_{i-1}) / (l_i - l_{i-1})     for l_{i-1} < p <= l_i
start = r_0                                                             for p <= l_0
```

Remote values need not increase (shipped: `(0,1.0),(1.0,0)` maps p to 1 - p).

Not established: behaviour with "Sync PlayPos?" set and no marker filled (the lists are empty and `R[0]` is read anyway).
It does not occur in shipped data: all 145 sync transitions in Part 2 PC have at least two markers.

## 4. How a transition picks the target's start play position — read

`EvaluateTransitions` 0x5cbbc2, when a transition T has been selected for the top page:

```
pp   = TransitionPlayPos(T, top.playpos)                 # method +0xa8; -1 if T neither overrides nor syncs
ease = T.m_toverrideeasein ? T.m_neaseinduration : -1    # rec+0x10, rec+0x14
target = T.m_etostate; if it is a group: the state get_valid_state stored in m_estoredtransitstate
TransitToState(target, ease, pp)                         # method +0xb0
send every event in T.m_eeventlist
```

The transition is deferred (result 1, nothing happens this frame) while the stack header's timer at +0x14 is > 0
(`0.0 < [stack+4]+0x14`). `SetupNewPage` loads that field from the entered state's `m_nforcestaytime` ("Force Stay Time",
state rec+0x50). `ENGINE_CONSTANTS.md` and the toolkit describe this deferral as "during the top page's ease window"; the code
reads a force-stay timer on the stack, not the page's ease. Where the timer counts down was not traced (**not established**).

`TransitToState` 0x5b4a31 (state record: +0x14 `m_toverridestate`, +0x18 `m_tiswalkcycle`, +0x38 `m_nstartplaypos`):

```
if target.m_toverridestate:                      # overlay stack
    start = pp >= 0 ? pp : target.m_nstartplaypos ; sync = 0
elif top.state.m_tiswalkcycle and target.m_tiswalkcycle:
    start = pp >= 0 ? pp : top.playpos ; sync = 1          # carry the phase over
else:
    start = pp >= 0 ? pp : target.m_nstartplaypos ; sync = 0
SetupNewPage(target, start, sync, ease, stack)             # method +0xfc
```

`SetupNewPage` 0x5b7788 (read from the decompilation; individual instructions not re-checked):

- Does nothing if the top page already plays `target` and `m_tallowmultipleinstances` ("Allow more than once", +0x2c) is off.
- If an older page of the stack already plays `target` (and multiple instances are off) and `target.m_tiswalkcycle` is set,
  the start position is taken from **that page's current play position** instead.
- Ease-in: the page starts fully blended in (blend 1, ease 0) if the target state's own `m_neaseinduration` <= 0, or the
  body stack is empty, or the passed ease is exactly 0. Otherwise the ease is the passed value, or the state's
  `m_neaseinduration` when the passed value is negative (no override). So **a transition's ease-in override is ignored when
  the target state's own ease-in is 0**; the toolkit applies it regardless.
- Writes page+0x10 = start, page+0x18 = sync, page+0x0c = ease, page+0x08 = initial blend.

Start position in one line, in priority order:

```
1. transition "Override Start PlayPos?"      -> m_nplaypos
2. transition "Sync PlayPos?"                -> marker map of the outgoing play position
3. both states "Sync Playpos" (walk cycle)   -> the outgoing play position unchanged
4. otherwise                                 -> target state's "Start Play Pos" (m_nstartplaypos)
then: target already on the stack + walk cycle -> that page's play position
```

Entries that do not come from a transition (overlay entry, fallback/default state in `EvaluateTransitions`) pass pp = -1 and
ease = -1, i.e. rules 3-4 and the state's own ease-in.

### The walk-cycle flag afterwards: `SynchronizePages` 0x5ac387 — read; field meaning inferred

For each run of pages whose sync flag (page+0x18) is set, down to and including the page under the run, it sets one common
value in page+0x14:

```
rate = sum_i w_i / T_i     (w = blend weights cascaded from the top page down: b_top, (1-b_top)*b_next, ..., remainder to the base page)
T_common = 1 / rate        written to page+0x14 of every page in the run
```

page+0x14 is the page's cycle length in seconds (inferred from this weighted harmonic mean; its writer in `UpdatePagePlayPos`
was not traced). The effect is that synced walk cycles advance at one blended rate and stay in phase during the crossfade.

## 5. Fallback flag — read

`GetValidStateGroupTransition` 0x5c6140 walks the owner's transition list and skips a transition unless
`m_tfallback == pass` (`local_14 != puVar2[4]`): the normal pass (arg 0) sees only non-fallback transitions, the retry
(arg 1, issued by `EvaluateTransitions` when the current state's criteria no longer hold) sees only fallback ones.
It also skips a target already tested in this evaluation (list `_etestedstates`), so each target is tried once.

## 6. Differences from `anim_state_machine.py`

| | toolkit | engine |
|---|---|---|
| gate | none | sync transition can fire only for l_min <= p <= l_max (`TransitionMet`) |
| end points | adds (0,0) and (1,1) to the marker list | no implicit points; clamps to r_first / r_last |
| unset test | pair dropped if local < 0 **or** remote < 0 | list stops at the first local < 0; remote is not tested |
| walk cycle | not modelled | both states `m_tiswalkcycle` -> start at the outgoing play position; pages then share one cycle length |
| ease override | always applied | ignored if the target state's own ease-in is 0 |
| deferral | while the top page eases in | while the stack's force-stay timer > 0 (from the state's "Force Stay Time") |
| fallback | fallback transitions tried in a separate step | same idea, but the normal pass also *excludes* fallback transitions |
| marker keys | `key_ee2a40XX` / `key_4cadfbXX` | `m_nsupersynclocalN` / `m_nsupersyncremoteN` (key table has them under the wrong hash) |

With the engine's rules the padding makes no difference inside the marker range only when the markers already start at
(0, ·) and end at (1, ·); for a typical shipped transition such as `(0.83->0.23),(1.0->0.35)` the toolkit maps p = 0.9 to 0.28
(same as the engine) but also lets the transition fire at p = 0.5 and maps it to 0.14, where the engine does not fire at all.

## 7. Data check (Part 2 PC, all 906 `.fragment.json`, read-only)

2,636 decoded transition nodes (a further 1,901 nodes of the class come out of our fragment parser with unnamed keys and
were not examined): 145 with "Sync PlayPos?", 42 with "Override Start PlayPos?" (never both), 572 with "Override Ease In?",
42 fallback. Every sync transition has 2-6 markers, values in 0..1, often stored unsorted; no transition without the flag has
a marker set. 98 states have the walk-cycle flag, 5 are override states. The `[-1, 9.1e7, -1]` value on marker 8 (local) in our
JSON is the known 3-float misread of the last record, not data.
