#!/usr/bin/env python3
"""Engine-faithful interpreter for Watchmen AnimationClass state machines.

Sources (all reversed from the game executable, see
docs/ENGINE_CONSTANTS.md section 2026-07-09m):
  command_get_valid_state   0x5f076f  round-robin state choice in a group
  StateGroupCriteriaMet     0x5c6002  single criteria AND criteria-list
  GetValidStateGroupTrans.  0x5c6140  transition selection order + fallback
  TransitToState            0x5b4a31  ease-in pick (override else state)
  page blend curve          0x77ab7b  engine-exact (powf, float32)
  AnimationCriteriaMet      0x5c5781  criteria semantics (2026-07-09j)
  EvaluateTransitions       0x5cbbc2  per-stack transition tick + overlay entry
  StateMain/Update          0x5b417b/0x5b4613  TWO page stacks: body pass
                            (flag 0) then overlay pass (flag 1) per frame
  AllowOverlayTransitions   0x5aa33d  runtime gate -> env.allow_overlays
  DeleteOldPages            0x5b9e4c  occluded (blend>=1 above) page removal

Overlay pages (2026-07-13): candidates live in the class root's
'OverlayStates' folder (e.g. HeadTurn additive look-at layers). When the
overlay stack is empty, EvaluateTransitions scans the candidates and pushes
the first state whose criteria pass (groups: criteria + get_valid_state,
scan continues; states: criteria only, scan breaks) via SetupNewPage.
OVERLAY_PLAY_POS/REVERSE (criteria 7/8) read the TOP OVERLAY page playpos;
they never occur in shipped fragments (all-data scan 2026-07-13).

Input: extractor fragment JSON (kapow_fragment/kapow_json output), e.g.
20260708/extracted/.../AnimationClassEnemy01.fragment.json. Nested
StateGroup fragments (assetName refs) are resolved relative to the
extracted tree.

ANIMATION_CRITERIA enum (exe): VALUE=0 ACTION=1 ENUM=2 EVENT=3 PLAY_TIME=4
PLAY_POS=5 REVERSE_PLAY_POS=6 OVERLAY_PLAY_POS=7 REVERSE_OVERLAY_PLAY_POS=8
ANIMATION_PLAY_DONE=9 FORCE_ANIMATION=10 ANY_OF=11 ALL_OF=12
Interval test m_iintervaltype: 0=INTERVAL(min..max) 1=LESS(<=min?) 2=GREATER(>=min)
"""

import json, math, os, struct

# ---------------------------------------------------------------- tree

CLS_CLASS = "AnimationClassWM"
CLS_GROUP = "AnimationStateGroupWM"
CLS_STATE = "AnimationStateWM"
CLS_BLEND = "AnimationBlendWM"
CLS_SLOT = "AnimationSlotWM"
CLS_CRIT = "AnimationCriteriaWM"
CLS_TRANS = "AnimationTransitionWM"
CLS_EVENT = "AnimationEventWM"

# transition sync markers registered without m_* names in the exe;
# hashes from reg_dump.json (captions "Sync marker N (local/remote)")
SYNC_LOCAL = [
    "key_ee2a40a0",
    "key_ee2a4060",
    "key_ee2a40e0",
    "key_ee2a4000",
    "key_ee2a4080",
    "key_ee2a4040",
    "key_ee2a40c0",
    "key_ee2a4030",
]
SYNC_REMOTE = [
    "key_4cadfb2b",
    "key_4cadfbeb",
    "key_4cadfb6b",
    "key_4cadfb8b",
    "key_4cadfb0b",
    "key_4cadfbcb",
    "key_4cadfb4b",
    "key_4cadfbbb",
]


class Node:
    __slots__ = ("id", "cls", "name", "props", "children", "parent")

    def __init__(self, nid, cls, name):
        self.id, self.cls, self.name = nid, cls, name
        self.props, self.children, self.parent = {}, [], None

    def p(self, key, default=None):
        return self.props.get(key, default)

    def kids(self, cls=None):
        return [c for c in self.children if cls is None or c.cls == cls]

    def folder(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def descend(self, cls):
        out = []
        stack = [self]
        while stack:
            n = stack.pop()
            for c in n.children:
                if c.cls == cls:
                    out.append(c)
                stack.append(c)
        return out

    def __repr__(self):
        return f"<{self.cls} {self.name!r}>"


def _base_cls(s):
    return s.split("(")[0] if s else s


def load_tree(path, resolve_fragments=True, _seen=None):
    """Build the node tree of one fragment JSON; splice nested fragments."""
    j = json.load(open(path))
    pre = j["instances"][0]
    cls = {k[4:]: _base_cls(v[0]) for k, v in pre.items() if k.startswith("str_")}
    nodes = {}
    for nf in j["nodes_full"]:
        d = {k: v for k, t, v in nf["props"]}
        n = Node(nf["id"], cls.get(nf["id"], "?"), d.get("name", ""))
        n.props = d
        nodes[nf["id"]] = n
    roots = []
    for n in nodes.values():
        lp = n.p("logicalParent")
        ref = lp.get("ref") if isinstance(lp, dict) else None
        if ref in nodes:
            n.parent = nodes[ref]
            nodes[ref].children.append(n)
        else:
            roots.append(n)
    for n in nodes.values():
        n.children.sort(key=lambda c: c.p("siblingOrder", 0))
    if resolve_fragments:
        _seen = _seen or set()
        base = path
        while "/extracted/" in base:
            base = os.path.dirname(base)
        for n in list(nodes.values()):
            asset = n.p("assetName")
            if n.cls == CLS_GROUP and asset and asset not in _seen:
                _seen.add(asset)
                sub = os.path.join(base, asset.lstrip("/") + ".json")
                if os.path.exists(sub):
                    for r in load_tree(sub, True, _seen):
                        for c in r.children:  # splice sub-fragment content
                            c.parent = n
                            n.children.append(c)
    return roots


def find_class_root(roots):
    for r in roots:
        stack = [r]
        while stack:
            n = stack.pop()
            if n.cls == CLS_CLASS:
                return n
            stack.extend(n.children)
    return roots[0]


# ------------------------------------------------------- engine math


def page_blend_curve(t, hardness=1.0, offset=1.0):
    """FUN_0077ab7b, engine-exact incl. float32 pow truncation."""
    f32 = lambda x: struct.unpack("<f", struct.pack("<f", x))[0]
    t = min(1.0, max(0.0, t))
    v = f32(math.pow(t, offset))
    if v <= 0.5:
        return f32(math.pow(2.0 * v, hardness) * 0.5)
    return 1.0 - f32(math.pow(2.0 - 2.0 * v, hardness) * 0.5)


def inv_lerp_clamped(x, a, b):
    """FUN_0077a4d8."""
    lo, hi = min(a, b), max(a, b)
    x = min(hi, max(lo, x))
    return (x - a) / (b - a) if b != a else 0.0


def sync_remap(playpos, trans):
    """Piecewise playpos remap over up-to-8 (local, remote) marker pairs.
    Markers with value < 0 are unset. (2026-07-09j semantics.)"""
    pairs = []
    for lk, rk in zip(SYNC_LOCAL, SYNC_REMOTE):
        l, r = trans.p(lk, -1.0), trans.p(rk, -1.0)
        if isinstance(l, list):
            l = l[0]
        if isinstance(r, list):
            r = r[0]
        if isinstance(l, (int, float)) and isinstance(r, (int, float)) and l >= 0.0 and r >= 0.0:
            pairs.append((float(l), float(r)))
    if not pairs:
        return playpos
    pairs.sort()
    pts = [(0.0, 0.0)] + pairs + [(1.0, 1.0)]
    for (l0, r0), (l1, r1) in zip(pts, pts[1:]):
        if l0 <= playpos <= l1:
            u = (playpos - l0) / (l1 - l0) if l1 > l0 else 0.0
            return r0 + u * (r1 - r0)
    return playpos


# ------------------------------------------------------- criteria

CRIT_VALUE, CRIT_ACTION, CRIT_ENUM, CRIT_EVENT = 0, 1, 2, 3
CRIT_PLAY_TIME, CRIT_PLAY_POS = 4, 5
CRIT_REV_PP, CRIT_OVERLAY_PP, CRIT_REV_OVERLAY_PP = 6, 7, 8
CRIT_PLAY_DONE, CRIT_FORCE_ANIM, CRIT_ANY_OF, CRIT_ALL_OF = 9, 10, 11, 12


def interval_met(x, itype, lo, hi):
    if itype == 0:
        return lo <= x <= hi
    if itype == 1:
        return x <= lo
    return x >= lo  # 2 = GREATER (uses min)


class Env:
    """Criteria inputs. values: param index -> float; enums: idx -> int;
    actions/events: sets of ints currently fired."""

    def __init__(self):
        self.values, self.enums = {}, {}
        self.actions, self.events = set(), set()
        self.force_anim = None
        self.allow_overlays = True  # AllowOverlayTransitions 0x5aa33d
        self.overlay_page = None  # top overlay page (set by Interpreter)


def criteria_met(c, env, page, entry):
    """AnimationCriteriaMet 0x5c5781 semantics."""
    if not c.p("enabled", True):
        return True
    if c.p("m_tentryonly", False) and not entry:
        return True
    kind = c.p("m_ianimationcriteria", 0)
    it = c.p("m_iintervaltype", 0)
    lo, hi = c.p("m_nintervalmin", 0.0), c.p("m_nintervalmax", 0.0)
    if kind == CRIT_VALUE:
        x = env.values.get(c.p("m_ianimationvalue", 0), 0.0)
        r = interval_met(x, it, lo, hi)
    elif kind == CRIT_ACTION:
        r = c.p("m_ianimationaction", 0) in env.actions
    elif kind == CRIT_ENUM:
        r = env.enums.get(c.p("m_ianimationenum", 0)) == c.p("m_ianimationenumvalue", 0)
    elif kind == CRIT_EVENT:
        r = c.p("m_ianimationevent", 0) in env.events
    elif kind == CRIT_PLAY_TIME:
        r = interval_met(page.time_played if page else 0.0, it, lo, hi)
    elif kind == CRIT_PLAY_POS:
        r = interval_met(page.playpos if page else 0.0, it, lo, hi)
    elif kind == CRIT_REV_PP:
        r = interval_met(1.0 - (page.playpos if page else 0.0), it, lo, hi)
    elif kind == CRIT_PLAY_DONE:
        r = bool(page and page.done)
    elif kind == CRIT_FORCE_ANIM:
        r = env.force_anim is not None
    elif kind == CRIT_ANY_OF:
        r = (
            any(criteria_met(k, env, page, entry) for k in c.kids(CLS_CRIT))
            if c.kids(CLS_CRIT)
            else False
        )
    elif kind == CRIT_ALL_OF:
        r = all(criteria_met(k, env, page, entry) for k in c.kids(CLS_CRIT))
    elif kind == CRIT_OVERLAY_PP:  # 7: top OVERLAY page playpos (09j)
        op = env.overlay_page
        r = interval_met(op.playpos if op else 0.0, it, lo, hi)
    elif kind == CRIT_REV_OVERLAY_PP:  # 8: 1 - overlay playpos
        op = env.overlay_page
        r = interval_met(1.0 - (op.playpos if op else 0.0), it, lo, hi)
    else:
        r = False
    return (not r) if c.p("m_tnot", False) else r


def _crit_nodes(node):
    f = node.folder("Criterias")
    return f.kids(CLS_CRIT) if f else node.kids(CLS_CRIT)


def group_criteria_met(node, env, page, entry):
    """StateGroupCriteriaMet 0x5c6002: AND over the criteria list."""
    return all(criteria_met(c, env, page, entry) for c in _crit_nodes(node))


# ------------------------------------------------------- interpreter


class Page:
    def __init__(self, state, ease_in, playpos):
        self.state, self.ease_in = state, ease_in
        self.playpos, self.time_played = playpos, 0.0
        self.age, self.done = 0.0, False
        self.duration = _state_duration(state)

    @property
    def blend(self):
        if self.ease_in <= 0.0:
            return 1.0
        t = inv_lerp_clamped(self.age, 0.0, self.ease_in)
        return page_blend_curve(
            t, self.state.p("m_nblendpower", 1.0), self.state.p("m_nblendinitialpower", 1.0)
        )

    def slots(self):
        out = []
        lay = self.state.folder("Layers") or self.state
        for blend in lay.descend(CLS_BLEND):
            for s in blend.kids(CLS_SLOT):
                out.append((blend, s))
        return out


def _state_duration(state):
    lay = state.folder("Layers") or state
    for b in lay.descend(CLS_BLEND):
        for s in b.kids(CLS_SLOT):
            d = s.p("m_sduration", "")
            try:
                return float(str(d).split()[0])
            except (ValueError, IndexError):
                pass
    return 1.0


def _trans_nodes(node):
    f = node.folder("Transitions")
    return f.kids(CLS_TRANS) if f else node.kids(CLS_TRANS)


class Interpreter:
    """Replicates state choice + slot start params (goal of task-3)."""

    def __init__(self, class_root, log=None):
        self.root = class_root
        self.env = Env()
        self.pages = []  # body page stack (Update flag 0), newest last
        self.opages = []  # OVERLAY page stack (Update flag 1)
        self._act_overlay = False  # which stack the current pass evaluates
        self.rr_index = {}  # group id -> round-robin cursor
        self.log = log if log is not None else []

    def _cur(self):
        """Top page of the stack the current pass evaluates (criteria ctx)."""
        st = self.opages if self._act_overlay else self.pages
        return st[-1] if st else None

    # ---- engine: command_get_valid_state 0x5f076f
    def get_valid_state(self, group, entry=True):
        kids = [k for k in group.children if k.cls in (CLS_STATE, CLS_GROUP)]
        if not kids:
            return None
        n = len(kids)
        start = (self.rr_index.get(group.id, -1) + 1) % n
        for i in range(n):
            k = kids[(start + i) % n]
            if not k.p("enabled", True):
                continue
            if not group_criteria_met(k, self.env, self._cur(), entry):
                continue
            if k.cls == CLS_GROUP:
                s = self.get_valid_state(k, entry)
                if s is not None:
                    self.rr_index[group.id] = (start + i) % n
                    return s
            else:
                self.rr_index[group.id] = (start + i) % n
                return k
        return None

    # ---- engine: GetValidStateGroupTransition 0x5c6140
    def get_valid_transition(self, node, entry=False):
        for t in _trans_nodes(node):
            if not t.p("enabled", True):
                continue
            if not all(criteria_met(c, self.env, self._cur(), entry) for c in t.kids(CLS_CRIT)):
                continue
            target = self._resolve_target(t)
            if target is None:
                continue
            if target.cls == CLS_GROUP:
                if not group_criteria_met(target, self.env, self._cur(), entry):
                    continue
                s = self.get_valid_state(target, True)
                if s is None:
                    continue
                return t, s
            if not group_criteria_met(target, self.env, self._cur(), entry):
                continue
            return t, target
        return None

    def _resolve_target(self, trans):
        ref = trans.p("m_etostate")
        if not isinstance(ref, dict):
            return None
        ids = ref.get("xref") or [ref.get("ref")]
        byid = self._index()
        for i in reversed(ids or []):
            if i in byid:
                return byid[i]
        return None

    def _index(self):
        if not hasattr(self, "_byid"):
            self._byid = {}
            stack = [self.root]
            while stack:
                n = stack.pop()
                self._byid[n.id] = n
                stack.extend(n.children)
        return self._byid

    # ---- engine: TransitToState 0x5b4a31 + transition apply 09j
    def transit(self, state, trans=None, overlay=False):
        ease = state.p("m_neaseinduration", 0.0)
        pp = state.p("m_nstartplaypos", 0.0)
        cur = self._cur()
        if trans is not None:
            if trans.p("m_toverrideeasein", False):
                ease = trans.p("m_neaseinduration", 0.0)
            if trans.p("m_toverrideplaypos", False):
                pp = trans.p("m_nplaypos", 0.0)
            elif trans.p("m_tsupersyncpos", False) and cur:
                pp = sync_remap(cur.playpos, trans)
        stack = self.opages if overlay else self.pages
        stack.append(Page(state, ease, pp))
        if len(stack) > 8:
            stack.pop(0)
        self.log.append(
            ("otransit" if overlay else "transit", state.name, round(ease, 4), round(pp, 4))
        )

    def _fallback(self, state):
        """Fallback path (0x5c6140 tail): fallback-flagged transitions first,
        then the state's m_efallbackstate / group default."""
        for t in _trans_nodes(state):
            if t.p("m_tfallback", False) and t.p("enabled", True):
                target = self._resolve_target(t)
                if target is None:
                    continue
                if target.cls == CLS_GROUP:
                    s = self.get_valid_state(target, True)
                    if s is not None:
                        return t, s
                else:
                    return t, target
        ref = state.p("m_efallbackstate")
        if isinstance(ref, dict):
            ids = ref.get("xref") or [ref.get("ref")]
            byid = self._index()
            for i in reversed(ids or []):
                n = byid.get(i)
                if n is not None and n.cls in (CLS_STATE, CLS_GROUP):
                    if n.cls == CLS_GROUP:
                        s = self.get_valid_state(n, True)
                        return (None, s) if s is not None else None
                    return None, n
        return None

    @property
    def page(self):
        return self.pages[-1] if self.pages else None

    @property
    def opage(self):
        return self.opages[-1] if self.opages else None

    # ---- engine: EvaluateTransitions 0x5cbbc2, empty-overlay-stack branch
    def _overlay_candidates(self):
        f = self.root.folder("OverlayStates")
        return [c for c in (f.children if f else []) if c.cls in (CLS_STATE, CLS_GROUP)]

    def _try_overlay_entry(self):
        if not self.env.allow_overlays:  # AllowOverlayTransitions 0x5aa33d
            return
        for cand in self._overlay_candidates():
            if not cand.p("enabled", True):
                continue
            if not group_criteria_met(cand, self.env, None, True):
                continue
            if cand.cls == CLS_GROUP:
                s = self.get_valid_state(cand, entry=True)
                if s is not None:
                    self.transit(s, None, overlay=True)
                # engine keeps scanning after a group hit (0x5cbbc2)
            else:
                self.transit(cand, None, overlay=True)
                break  # engine breaks on a state hit

    def start(self, group=None):
        g = group or self.root
        s = self.get_valid_state(g, entry=True)
        if s is not None:
            self.transit(s, None)
        return s

    # ---- engine: StateMain 0x5b417b = Update(0, body) then Update(1, overlay);
    # Update 0x5b4613 order: EvaluateTransitions FIRST (last frame's playpos),
    # page blends, DeleteOldPages, then UpdatePagePlayPos advances.
    def tick(self, dt):
        for overlay in (False, True):
            self._act_overlay = overlay
            pages = self.opages if overlay else self.pages
            self.env.overlay_page = self.opages[-1] if self.opages else None
            # EvaluateTransitions 0x5cbbc2
            if not pages:
                if overlay:
                    self._try_overlay_entry()
            else:
                top = pages[-1]
                if not top.state.p("m_tnotransitiontests", False):
                    hit, node = None, top.state
                    while hit is None and node is not None:  # state, ancestors
                        hit = self.get_valid_transition(node)
                        node = node.parent if node.cls in (CLS_STATE, CLS_GROUP) else None
                    if hit is None and top.done:
                        hit = self._fallback(top.state)
                    if hit is not None:
                        if 0.0 < top.age < top.ease_in:
                            pass  # defer: crossfade running (0x5cbbc2 out=1)
                        else:
                            self.transit(hit[1], hit[0], overlay=overlay)
            # UpdatePagePlayPos 0x5b56a9 (after evaluation)
            for pg in pages:
                pg.age += dt
                pg.time_played += dt
                if pg.duration > 0:
                    pg.playpos += dt / pg.duration
                if pg.playpos >= 1.0:
                    if pg.state.p("m_tislooping", False):
                        pg.playpos %= 1.0
                    else:
                        pg.playpos, pg.done = 1.0, True
            # DeleteOldPages 0x5b9e4c: drop pages occluded by a fully
            # blended-in page above them
            i = len(pages) - 1
            while i > 0 and pages[i].blend < 1.0:
                i -= 1
            if i > 0:
                del pages[:i]
        self._act_overlay = False
        self.env.events.clear()  # one-frame events (ClearOneFrameEvents)

    def _layer_weight(self, blend):
        """Blend-node layer weight driven by an ANIMATION_VALUE ctrl param
        (m_ilayerweightctrlparam mapped over 0..m_nlayerweightintervalend;
        the overlay look-at layers use it). 1.0 when absent."""
        p = blend.p("m_ilayerweightctrlparam")
        end = blend.p("m_nlayerweightintervalend", 0.0)
        if not p or end == 0.0:  # ctrl param 0 = NONE (UI: 'blend on NONE')
            return 1.0
        start = blend.p("m_nlayerweightintervalstart", 0.0)
        return inv_lerp_clamped(self.env.values.get(p, 0.0), start, end)

    def _slot_pos_weights(self, blend, slots):
        """Blend-position split inside one blend node: ctrl param
        m_iblendctrlparam mapped over the blend interval, slots placed at
        m_nparentblendposition, linear between neighbours (09j blend trees)."""
        p = blend.p("m_iblendctrlparam")
        if not p or len(slots) < 2:  # 0 = NONE
            return {i: 1.0 for i in range(len(slots))}
        pos = inv_lerp_clamped(
            self.env.values.get(p, 0.0),
            blend.p("m_nblendintervalstart", 0.0),
            blend.p("m_nblendintervalend", 1.0),
        )
        pts = sorted(((float(s.p("m_nparentblendposition", 0.0)), i) for i, s in enumerate(slots)))
        w = {i: 0.0 for i in range(len(slots))}
        if pos <= pts[0][0]:
            w[pts[0][1]] = 1.0
        elif pos >= pts[-1][0]:
            w[pts[-1][1]] = 1.0
        else:
            for (p0, i0), (p1, i1) in zip(pts, pts[1:]):
                if p0 <= pos <= p1:
                    u = (pos - p0) / (p1 - p0) if p1 > p0 else 0.0
                    w[i0], w[i1] = 1.0 - u, u
                    break
        return w

    def _stack_weights(self, pages, out):
        blends = [pg.blend for pg in pages]
        share = [1.0] * len(pages)
        for i in range(len(pages)):
            for jn in range(i + 1, len(pages)):
                share[i] *= 1.0 - blends[jn]
            share[i] *= blends[i]
        for pg, sh in zip(pages, share):
            if sh <= 1e-6:
                continue
            byblend = {}
            for blend, slot in pg.slots():
                byblend.setdefault(id(blend), (blend, []))[1].append(slot)
            for blend, slots in byblend.values():
                posw = self._slot_pos_weights(blend, slots)
                lw = self._layer_weight(blend)
                for i, slot in enumerate(slots):
                    w = (
                        sh
                        * posw[i]
                        * lw
                        * float(slot.p("m_nweight", 1.0))
                        * float(blend.p("m_nweight", 1.0))
                    )
                    if w <= 1e-6:
                        continue
                    anim = slot.p("targetAnimation", slot.name)
                    out[anim] = out.get(anim, 0.0) + w
        return out

    def slot_weights(self, include_overlay=True):
        """anim -> weight; body crossfade shares + overlay stack. Overlay
        layers are ADDITIVE (m_tlayeradditive) - callers that need them
        separated use overlay_weights()."""
        out = {}
        self._stack_weights(self.pages, out)
        if include_overlay:
            self._stack_weights(self.opages, out)
        return out

    def overlay_weights(self):
        return self._stack_weights(self.opages, {})


# ------------------------------------------------------- CLI


def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fragment_json")
    ap.add_argument("--list", action="store_true", help="dump groups/states/transitions and exit")
    ap.add_argument("--ticks", type=int, default=120)
    ap.add_argument("--dt", type=float, default=1 / 30)
    ap.add_argument("--enum", action="append", default=[], help="idx=value criteria enum input")
    ap.add_argument(
        "--value",
        action="append",
        default=[],
        help="idx=float ANIMATION_VALUE input (criteria + blends)",
    )
    args = ap.parse_args()
    roots = load_tree(args.fragment_json)
    root = find_class_root(roots)
    if args.list:

        def walk(n, d=0):
            if n.cls in (CLS_CLASS, CLS_GROUP, CLS_STATE):
                print("  " * d + f"{n.cls[9:] or n.cls} {n.name}")
            for t in _trans_nodes(n):
                print("  " * (d + 1) + f"-> trans {t.name}")
            for c in n.children:
                walk(c, d + 1 if n.cls in (CLS_CLASS, CLS_GROUP, CLS_STATE) else d)

        walk(root)
        return
    it = Interpreter(root)
    for spec in args.enum:
        k, v = spec.split("=")
        it.env.enums[int(k)] = int(v)
    for spec in args.value:
        k, v = spec.split("=")
        it.env.values[int(k)] = float(v)
    s = it.start()
    print("start state:", s.name if s else None)
    last = None
    for i in range(args.ticks):
        it.tick(args.dt)
        w = it.slot_weights()
        top = sorted(w.items(), key=lambda kv: -kv[1])[:3]
        cur = it.page.state.name if it.page else None
        ov = it.opage.state.name if it.opage else "-"
        if cur != last or i % 30 == 0:
            print(
                f"t={i*args.dt:7.3f} state={cur:32s} ov={ov:12s} "
                + "  ".join(f"{os.path.basename(a)}:{x:.3f}" for a, x in top)
            )
            last = cur
    for e in it.log:
        print("LOG", e)


if __name__ == "__main__":
    main()
