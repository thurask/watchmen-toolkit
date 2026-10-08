#!/usr/bin/env python3
"""Engine-faithful interpreter for Watchmen AnimationClass state machines.

Sources (all read from the game executable; docs/ENGINE_CONSTANTS.md):
  command_get_valid_state   0x5f076f  state choice in a group: scan from member 0,
                                      or from a random member when the group has
                                      "Choose Random State"; members already in the
                                      evaluation's tested list are skipped
  StateGroupCriteriaMet     0x5c6002  owning groups' criteria AND own criteria list
  State.get_valid_transition 0x5f7873 / GetValidStateGroupTransition 0x5c6140
                                      own transitions, then the owning groups';
                                      m_tfallback must equal the pass
  TransitionMet             0x5c5ea4  enabled, super-sync window, criteria
  TransitionPlayPos         0x5ac1aa  override / sync-marker start position
  TransitToState            0x5b4a31  (state, ease, playpos); walk-cycle carry-over
  SetupNewPage              0x5b7788  page creation, re-entry, ease rule, one
                                      random blend node per layer list, events
  UpdatePageBlendsFaster    0x5b4bd6 / SetAllSlotBlends 0x5b4ef7  weights, page rate
  SynchronizePages          0x5ac387  common rate of "Sync Playpos" pages
  UpdatePagePlayPos         0x5b56a9  playpos advance (clamp 6.6/s), loop, blend
  CheckPlayPosEvents        0x5b51f3  PLAY_POS latch / TOTAL_PLAY_TIME
  page blend curve          0x77ab7b  engine-exact (powf, float32)
  AnimationCriteriaMet      0x5c5781  criteria semantics
  EvaluateTransitions       0x5cbbc2  per-stack transition tick + overlay entry
  StateMain/Update          0x5b417b/0x5b4613  TWO page stacks: body pass
                            (flag 0) then overlay pass (flag 1) per frame
  AllowOverlayTransitions   0x5aa33d  runtime gate -> env.allow_overlays
  DeleteOldPages            0x5b9e4c  occluded (blend>=1 above) page removal
  MathLib.InsideInterval    0x77aa25  INTERVAL [min, max[, LESS_THAN x < max,
                                      GREATER_THAN_OR_EQUAL x >= min
  owner searches            AddToClass 0x5ed37a (state -> nearest state group,
                            class), AddToParentGroup, AddToClosestState
                            (transition -> state / group),
                            FindClosestRelevantParent 0x5aaf49 (criteria): the
                            nearest ancestor that has m_iAnimationSystemType;
                            folders are passed over, whatever their name
  Transition.initialize_external 0x5f9b13  a transition to a STATE also carries
                                      that state's own criteria
  AnimSlot speedFactor      0x4b30b1  per-slot factor of the page rate (0x5b5175)

This module is the ONE implementation of these rules; anim_meta.py turns them
into records (criteria_of, transitions_of, members, transition_criteria,
criteria_partial, marker_pairs / map_markers / start_playpos, event_timing /
event_due / event_prelatched, state_speed, resolve_ref).

Not modelled: the slave lock of a dual animation (goto_slave_mode 0x5b32a2
stores the master's first animation source in the controller's _eslaveof and
UpdatePagePlayPos 0x5b5756 copies its play position into the partner's top
page every frame) -- the interpreter runs one character. anim_meta's pair
timeline uses it.

Overlay pages: the candidates are the class's override list (command_add_state
0x5a03a8): each "Override State", or the outermost state group that owns it
(e.g. HeadTurn additive look-at layers). When the
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
ANIM_PLAY_DONE=9 FORCE_ANIM=10 ANY_OF=11 ALL_OF=12
Interval test m_iintervaltype: 0=INTERVAL [min,max[  1=LESS_THAN (x < max)
2=GREATER_THAN_OR_EQUAL (x >= min)
"""

import math, os, random, struct

# ---------------------------------------------------------------- tree

CLS_CLASS = "AnimationClassWM"
CLS_GROUP = "AnimationStateGroupWM"
CLS_STATE = "AnimationStateWM"
CLS_BLEND = "AnimationBlendWM"
CLS_SLOT = "AnimationSlotWM"
CLS_CRIT = "AnimationCriteriaWM"
CLS_TRANS = "AnimationTransitionWM"
CLS_EVENT = "AnimationEventWM"
CLS_FOLDER = "Folder"

# AnimationStateGroup "Choose Random State" (+0x0c, read by command_get_valid_state)
RANDOM_STATE = "_trandomizetransitiontostate"

# transition sync markers: "Sync marker N (local/remote)", record +0x24.. (0x60d619)
SYNC_LOCAL = ["m_nsupersynclocal%d" % i for i in range(1, 9)]
SYNC_REMOTE = ["m_nsupersyncremote%d" % i for i in range(1, 9)]


class Instance:
    """One loaded instance of a fragment file (a fragment used by two hosts is two
    instances).  `host` is the node it was spliced under (None for the file
    load_tree was called with), `header` the file header fields when the JSON has
    them, `ctx` the dict shared by every instance of one load_tree call:
    {"top": Instance, "singletons": {name hash: [Instance, ...]}}."""

    __slots__ = ("asset", "path", "header", "host", "roots", "ctx")

    def __init__(self, asset, path, header, host, ctx):
        self.asset, self.path, self.header, self.host, self.ctx = asset, path, header, host, ctx
        self.roots = []

    def singleton_hash(self):
        """The id a singleton fragment is registered under: the name hash of its
        header name, or of the file's base name when that is empty (engine
        0x4a1d63 / 0x540afd); None for a fragment that is not a singleton."""
        h = self.header
        if not h or not h.get("singleton"):
            return None
        import kapow_props

        stem = os.path.basename(self.path or self.asset or "").replace("\\", "/")
        stem = stem[:-5] if stem.endswith(".json") else stem
        name = h.get("name") or os.path.splitext(stem)[0]
        return "%08x" % kapow_props.name_hash(name)


class Node:
    __slots__ = (
        "id",
        "cls",
        "name",
        "props",
        "children",
        "parent",
        "frag",
        "type",
        "inst",
        "spliced",
    )

    def __init__(self, nid, cls, name):
        self.id, self.cls, self.name = nid, cls, name
        self.props, self.children, self.parent = {}, [], None
        self.frag = None  # asset path, set on the top-level nodes of a spliced fragment
        self.type = None  # the type record's name as stored: "Class(Native)" or "Native"
        self.inst = None  # the Instance this node was loaded with (load_tree)
        self.spliced = False  # load_tree found the fragment this node names (assetName)

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


def _load_fragment_json(path):
    """Fragment JSON for `path` (a `.fragment.json` or a `.fragment`).

    Prefers parsing the binary `.fragment` next to it: JSON written by an older
    extractor carries `key_xxxxxxxx` names where the current key table has
    `m_...` names, and every lookup in this module is by the current names.
    Falls back to the JSON on disk when the binary is not there.
    """
    import kapow_json as _kj

    return _kj.load_fragment(path)


def tree_from_json(j):
    """(roots, nodes-by-id) of one fragment JSON dict; no sub-fragment splicing."""
    if not j.get("instances"):
        # an empty or non-lossless fragment (several SoundEvents fragments are):
        # nothing to build, and it must not take the whole class tree down.
        return [], {}
    pre = j["instances"][0]
    cls = {k[4:]: _base_cls(v[0]) for k, v in pre.items() if k.startswith("str_")}
    nodes = {}
    for nf in j["nodes_full"]:
        d = {k: v for k, t, v in nf["props"]}
        # the node's own type first: the preamble table misses a node whose id
        # collides with another preamble key (one per shipped class fragment)
        c = _base_cls(nf.get("type")) or cls.get(nf["id"], "?")
        n = Node(nf["id"], c, d.get("name", ""))
        n.type = nf.get("type")
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
    return roots, nodes


HOSTS_GROUPS, HOSTS_ALL = "groups", "all"


def _find_ci(base, rel):
    """`base/rel` with every path part matched case-insensitively: the engine
    finds an asset by a case-folding hash and compare (0x54ba59), so
    "/tnt/Production/x.fragment" names the file extracted as "TNT/Production/...".
    A file that exists only as `<name>.json` is returned without the suffix."""
    p = base
    for part in rel.replace("\\", "/").strip("/").split("/"):
        try:
            names = os.listdir(p)
        except OSError:
            return None
        low = part.lower()
        hit = sorted(x for x in names if x.lower() == low)
        if not hit:
            hit = sorted(x[:-5] for x in names if x.lower() == low + ".json")
        if not hit:
            return None
        p = os.path.join(p, hit[0])
    return p


def load_tree(path, resolve_fragments=True, _seen=None, hosts=HOSTS_GROUPS, _host=None):
    """Build the node tree of one fragment; splice nested fragments.

    `path` may name the `.fragment` or its `.fragment.json`.

    A state group that instances a fragment (`assetName`) gets that fragment's
    top-level nodes as its own children, WHOLE: they are the group's states,
    sub-groups, transitions and folders (their logicalParent is the fragment's
    external slot). Each instance is loaded separately, so a fragment used by
    two groups appears twice; node ids are therefore unique only inside one
    fragment instance -- resolve references with resolve_ref(). `_seen` is the
    chain of fragments currently being loaded (cycle guard).

    hosts: "groups" (default) splices under AnimationStateGroup nodes only, which
    is all an animation class needs; "all" splices under every node that names a
    fragment in `assetName`, as the engine does (FragmentNode::SetFragmentAssetByName
    0x498db7 applies the fragment the moment the property is set); a callable
    `hosts(node, asset) -> bool` is "all" with a filter.

    Every node gets `.inst`, the Instance (file, header, host) it was loaded with.
    """
    j = _load_fragment_json(path)
    roots, nodes = tree_from_json(j)
    ctx = _host.inst.ctx if _host is not None and _host.inst is not None else None
    inst = Instance(None, path, j.get("header"), _host, ctx)
    if ctx is None:
        inst.ctx = ctx = {"top": inst, "singletons": {}}
    inst.roots = roots
    for n in nodes.values():
        n.inst = inst
    sh = inst.singleton_hash()
    if sh is not None:
        ctx["singletons"].setdefault(sh, []).append(inst)
    if resolve_fragments:
        _seen = tuple(_seen or ())
        base = path.replace(os.sep, "/")
        while "/extracted/" in base:
            base = os.path.dirname(base)
        for n in list(nodes.values()):
            asset = n.p("assetName")
            if not asset or not isinstance(asset, str) or asset in _seen:
                continue
            if hosts == HOSTS_GROUPS:
                if n.cls != CLS_GROUP:
                    continue
            elif not asset.lower().endswith((".fragment", ".scene")):
                continue
            elif callable(hosts) and not hosts(n, asset):
                continue
            sub = os.path.join(base, asset.lstrip("/"))
            if not (os.path.exists(sub) or os.path.exists(sub + ".json")):
                sub = _find_ci(base, asset)
            if sub and (os.path.exists(sub) or os.path.exists(sub + ".json")):
                n.spliced = True  # the fragment exists (it may hold no node)
                for r in load_tree(sub, True, _seen + (asset,), hosts, n):
                    r.parent, r.frag = n, asset
                    r.inst.asset = asset
                    n.children.append(r)
    return roots


def walk(roots):
    """Every node under `roots` (a node or a list of nodes), parents first."""
    out, stack = [], list(reversed(roots)) if isinstance(roots, (list, tuple)) else [roots]
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(reversed(n.children))
    return out


def node_index(roots, nodes=None):
    """{node id: [nodes]} -- a list because ids repeat across fragment instances.
    `nodes`: an already flattened node list to index instead of walking `roots`."""
    out = {}
    for n in walk(roots) if nodes is None else nodes:
        out.setdefault(n.id, []).append(n)
    return out


def _chain(n):
    out = []
    while n is not None:
        out.append(n)
        n = n.parent
    return out


def _nearest(node, cands):
    """Of several nodes with one id, the one sharing the deepest ancestor with `node`."""
    mine = _chain(node)
    best, depth = None, None
    for c in cands:
        theirs = set(id(x) for x in _chain(c))
        d = next((i for i, a in enumerate(mine) if id(a) in theirs), len(mine))
        if depth is None or d < depth:
            best, depth = c, d
    return best


def fragment_host(node):
    """The state group that instances the fragment `node` belongs to (None for a
    node of the top-level fragment)."""
    for n in _chain(node):
        if n.frag is not None:
            return n.parent
    return None


def _native_of(node):
    ty = node.type or ""
    return ty[ty.index("(") + 1 : -1] if ty.endswith(")") and "(" in ty else ty


def is_fragment_host(node):
    """True for a node that instances a fragment: its native class is FragmentNode
    or a subclass (type record), or a fragment was spliced under it."""
    return _native_of(node) in ("FragmentNode", "LoadBlock", "SceneNode", "StreamBlockNode") or any(
        c.frag is not None for c in node.children
    )


def find_in_scope(children, nid):
    """The engine's search for a fragment id below a node (0x53a5ff): depth-first
    in child order; a nested fragment host can match but is not entered."""
    stack = list(reversed(children))
    while stack:
        c = stack.pop()
        if c.id == nid:
            return c
        if not is_fragment_host(c):
            stack.extend(reversed(c.children))
    return None


def _walk_path(children, ids):
    cur = None
    for i in ids:
        cur = find_in_scope(children, i)
        if cur is None:
            return None
        children = cur.children
    return cur


def _legacy_path(node, ids, index):
    """Resolution without fragment headers (JSON written before the header was
    exported, or a path whose singleton is not in the loaded tree): the first id
    that exists, nearest instance first, every further id inside it."""

    def at(i):  # a plain {id: node} index is accepted too
        hit = index.get(i)
        return hit if isinstance(hit, list) else ([hit] if hit is not None else [])

    cur, ok = None, bool(ids)
    for i in ids:
        cands = at(i)
        if cur is None:
            cur = _nearest(node, cands) if cands else None
            continue
        inside = [c for c in cands if any(a is cur for a in _chain(c)[1:])]
        if not inside:
            ok = False
            break
        cur = min(inside, key=lambda c: len(_chain(c)))
    if ok and cur is not None and ids[-1] == cur.id:
        return cur
    for i in reversed(ids):
        if at(i):
            return _nearest(node, at(i))
    return None


def resolve_ref(node, ref, index):
    """Target node of an Entity reference stored on `node` (e.g. m_etostate),
    resolved as the engine's reader does (EntityType 0x500b81 / 0x505d84).

    {'etag': 1}: none.  {'etag': 2}: the node the fragment is applied to, i.e.
    the host that instances it.  {'ref': id} (tag 3): a node of the same fragment
    instance.  {'xref4': ids, 'a': a} (tag 4): a path that starts at the scene
    (a = 0) or at the fragment host enclosing `node`, a - 1 hosts further up; each
    id is searched depth-first below the node found so far without entering a
    nested fragment (find_in_scope).  {'xref': ids} (tag 5): ids[0] is the name
    hash of a singleton fragment, the rest a path below its host.

    Trees without fragment headers, and tag-5 paths whose singleton is not part
    of the loaded tree, fall back to the nearest-instance rule (_legacy_path).
    None when nothing matches (the reference leaves the loaded tree).
    """
    if not isinstance(ref, dict):
        return None
    if ref.get("etag") == 2:  # the fragment's own external slot = the node instancing it
        return fragment_host(node)
    inst = getattr(node, "inst", None)
    ctx = inst.ctx if inst is not None else None
    if ref.get("xref4") is not None:
        ids = list(ref["xref4"])
        if ctx is None or not ids:
            return _legacy_path(node, ids, index)
        a = ref.get("a") or 0
        if a == 0:  # from the scene: below the SceneNode when the loaded file is a scene
            top = []
            for r in ctx["top"].roots:
                top.extend(r.children if _native_of(r) == "SceneNode" else [r])
            return _walk_path(top, ids)
        # nearest host at or above the node (0x48e4fe), then a - 1 hosts up (0x48e4e2);
        # the file load_tree was called with hangs from a host outside the tree
        hosts = [n for n in _chain(node) if is_fragment_host(n)]
        if a - 1 < len(hosts):
            return _walk_path(hosts[a - 1].children, ids)
        if a - 1 == len(hosts):
            return _walk_path(ctx["top"].roots, ids)
        return None
    if ref.get("xref") is not None:
        ids = list(ref["xref"])
        insts = ctx["singletons"].get(ids[0]) if (ctx is not None and ids) else None
        if not insts:
            return _legacy_path(node, ids, index)
        first = insts[0]  # the engine keeps the first FragmentNode registered (0x49aadf)
        kids = first.host.children if first.host is not None else first.roots
        return _walk_path(kids, ids[1:]) if len(ids) > 1 else None
    if ref.get("ref") is None:
        return None
    if inst is not None:
        hit = index.get(ref["ref"])
        cands = hit if isinstance(hit, list) else ([hit] if hit is not None else [])
        for c in cands:  # the load map of the fragment being read (0x53cb0d)
            if c.inst is inst:
                return c
    return _legacy_path(node, [ref["ref"]], index)


def find_class_root(roots):
    """The AnimationClassWM node. The hero class fragments have none (their
    class node lives in the character's own fragment): they get a synthetic,
    nameless one holding every root, so that all top-level groups are reachable.
    The roots keep parent None (paths and owner chains are unchanged)."""
    for r in roots:
        stack = [r]
        while stack:
            n = stack.pop()
            if n.cls == CLS_CLASS:
                return n
            stack.extend(n.children)
    if len(roots) == 1:
        return roots[0]
    top = Node(None, CLS_CLASS, "")
    top.children = list(roots)
    return top


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


# keys an extractor older than the corrected name hash wrote for the markers
_SYNC_LOCAL_OLD = ["key_ee2a40" + x for x in ("a0", "60", "e0", "00", "80", "40", "c0", "30")]
_SYNC_REMOTE_OLD = ["key_4cadfb" + x for x in ("2b", "eb", "6b", "8b", "0b", "cb", "4b", "bb")]


def _marker(trans, i, local):
    v = trans.p((SYNC_LOCAL if local else SYNC_REMOTE)[i])
    if v is None:
        v = trans.p((_SYNC_LOCAL_OLD if local else _SYNC_REMOTE_OLD)[i])
    if isinstance(v, (list, tuple)):  # pre-v1.3 JSON carried some markers as a mistyped list
        v = v[0] if v else None
    return float(v) if isinstance(v, (int, float)) else -1.0


def marker_pairs(trans):
    """(local, remote) markers of a transition whatever its "Sync PlayPos?" flag
    says, as UpdateSuperSync 0x5fa582 builds them: taken in order 1..8, the list
    STOPS at the first negative local marker (remote is not tested), then it is
    sorted by local."""
    pairs = []
    for i in range(8):
        l = _marker(trans, i, True)
        if l < 0.0:
            break
        pairs.append((l, _marker(trans, i, False)))
    pairs.sort(key=lambda lr: lr[0])
    return pairs


def sync_markers(trans):
    """marker_pairs() of a "Sync PlayPos?" transition; [] when the flag is off."""
    return marker_pairs(trans) if trans.p("m_tsupersyncpos", False) else []


def markers_window(markers):
    """(min, max) local marker: the play-position window in which a sync
    transition may fire (TransitionMet 0x5c5ea4, record +0x6c / +0x70)."""
    return (markers[0][0], markers[-1][0]) if markers else None


def sync_window(trans):
    """markers_window() of a transition; None when it has no markers."""
    return markers_window(sync_markers(trans))


def map_markers(markers, playpos):
    """Outgoing play position -> start play position of the target over sorted
    (local, remote) markers (TransitionPlayPos 0x5ac1aa): piecewise linear
    between neighbouring markers, CLAMPED to the first / last remote marker
    outside them (no implicit (0,0) / (1,1) points)."""
    m = markers
    i = 0
    while i < len(m) and m[i][0] < playpos:
        i += 1
    if i == 0:
        return m[0][1]
    if i == len(m):
        return m[-1][1]
    (l0, r0), (l1, r1) = m[i - 1], m[i]
    u = (playpos - l0) / (l1 - l0) if l1 != l0 else 0.0
    return r0 + (r1 - r0) * min(1.0, max(0.0, u))  # MapIntervalToInterval 0x77a579


def sync_remap(playpos, trans):
    """map_markers() over a transition's markers; playpos unchanged without markers."""
    m = sync_markers(trans)
    return map_markers(m, playpos) if m else playpos


def transition_playpos(trans, playpos):
    """TransitionPlayPos 0x5ac1aa: "Override Start PlayPos?" wins, then the sync
    markers; -1.0 = no opinion (the target's own start position applies)."""
    if trans.p("m_toverrideplaypos", False):
        return float(trans.p("m_nplaypos", 0.0) or 0.0)
    if not trans.p("m_tsupersyncpos", False):
        return -1.0
    # "Sync PlayPos?" set but no valid marker: the engine then reads the first
    # remote marker of an EMPTY list (0x5ac24b) and gates on record +0x6c / +0x70,
    # which UpdateSuperSync leaves untouched -- not defined.  No shipped
    # transition is in that state; here it has no opinion and no gate.
    m = sync_markers(trans)
    return map_markers(m, playpos) if m else -1.0


# Where a state starts, first match wins (TransitToState 0x5b4a31), then the
# re-entry rule of SetupNewPage 0x5b7788. start_playpos() implements it.
TRANSITION_START_PRIORITY = [
    {
        "rule": "override_playpos",
        "when": "transition.start.rule == 'override_playpos'",
        "start": "transition.start.playpos",
    },
    {
        "rule": "sync_markers",
        "when": "transition.start.rule == 'sync_markers' (and the transition may only fire "
        "while gate[0] <= outgoing playpos <= gate[1])",
        "start": "piecewise-linear map local -> remote of the outgoing playpos, clamped to "
        "the first / last remote marker",
    },
    {
        "rule": "walk_cycle_carry_over",
        "when": "outgoing state and target state both have walk_cycle",
        "start": "the outgoing playpos",
    },
    {"rule": "target_default", "when": "otherwise", "start": "target state's start_playpos"},
    {
        "rule": "reentry",
        "when": "afterwards: the target is already on the page stack and is a walk_cycle",
        "start": "that page's current playpos (replaces the value chosen above)",
    },
]


def start_playpos(state, trans=None, outgoing=None, outgoing_playpos=0.0):
    """(start play position, sync flag, rule) for entering `state` through
    `trans` from `outgoing` (the top body state, None when there is none or the
    target is an overlay state). Rule names are those of
    TRANSITION_START_PRIORITY; the re-entry rule is applied by SetupNewPage."""
    start, sync, rule = float(state.p("m_nstartplaypos", 0.0) or 0.0), False, "target_default"
    if (
        outgoing is not None
        and outgoing.p("m_tiswalkcycle", False)
        and state.p("m_tiswalkcycle", False)
    ):
        start, sync, rule = outgoing_playpos, True, "walk_cycle_carry_over"
    if trans is not None:
        pp = transition_playpos(trans, outgoing_playpos)
        if pp >= 0.0:
            start = pp
            rule = "override_playpos" if trans.p("m_toverrideplaypos", False) else "sync_markers"
    return start, sync, rule


# ------------------------------------------------------- criteria

CRIT_VALUE, CRIT_ACTION, CRIT_ENUM, CRIT_EVENT = 0, 1, 2, 3
CRIT_PLAY_TIME, CRIT_PLAY_POS = 4, 5
CRIT_REV_PP, CRIT_OVERLAY_PP, CRIT_REV_OVERLAY_PP = 6, 7, 8
CRIT_PLAY_DONE, CRIT_FORCE_ANIM, CRIT_ANY_OF, CRIT_ALL_OF = 9, 10, 11, 12


def interval_met(x, itype, lo, hi):
    """MathLib.InsideInterval 0x77aa25: INTERVAL 0 = [min, max[ ; LESS_THAN 1 =
    x < MAX (min is not read); GREATER_THAN_OR_EQUAL 2 = x >= min; else False."""
    if itype == 0:
        return lo <= x < hi
    if itype == 1:
        return x < hi
    if itype == 2:
        return x >= lo
    return False


def s32(v):
    """Enum values are int32; fragments store -1 as 4294967295."""
    if not isinstance(v, int) or isinstance(v, bool):
        return v
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= (1 << 31) else v


class Env:
    """Criteria inputs. values: param index -> float; enums: idx -> int;
    actions/events: sets of ints currently fired."""

    def __init__(self):
        self.values, self.enums = {}, {}
        self.actions, self.events = set(), set()
        self.force_anim = None
        self.allow_overlays = True  # AllowOverlayTransitions 0x5aa33d
        self.overlay_page = None  # top overlay page (set by Interpreter)
        self.speed = 1.0  # class * character * controller speed factors (Update 0x5b4613)
        self.force_linear = False  # AnimationData "Force Linear Transitions"
        self.no_override_layer = False  # AnimationData "No Override Layer"
        # controller m_tforceupdate (+0x2c): while set, "No Transition Tests" states
        # are evaluated every frame. The engine also sets it itself when a page is
        # added or still blending; the game sets it from outside (not modelled).
        self.force_update = False


def typed(node):
    """Does the node carry m_iAnimationSystemType (ANIMATION_SYSTEM_NODE_TYPE:
    blend, criteria, slot, state, transition, class, event, state group)?
    Folders and plain nodes do not; the engine's owner searches walk past them."""
    return bool(node.cls) and node.cls.startswith("Animation")


def criterion_owner(c):
    """(state, group, transition) that an AnimationCriteria belongs to, as
    FindClosestRelevantParent 0x5aaf49 records them: walking up the typed
    ancestors, a transition (+0x34) or a state (+0x38) ends the search, the first
    state group is the owning group (+0x3c[0]). At most one of the three is set."""
    n = c.parent
    while n is not None:
        if n.cls == CLS_TRANS:
            return None, None, n
        if n.cls == CLS_STATE:
            return n, None, None
        if n.cls == CLS_GROUP:
            return None, n, None
        n = n.parent
    return None, None, None


def entry_only_skipped(c, page):
    """Prologue of AnimationCriteriaMet 0x5c5781: an "entry only" criterion is
    not tested (counts as met) while the top page's state is the state that owns
    it or lies inside the state group that owns it. A transition's own criteria
    have neither owner, so they are always tested."""
    if page is None or not c.p("m_tentryonly", False):
        return False
    st, grp, _tr = criterion_owner(c)
    if st is not None:
        return page.state is st
    if grp is None:
        return False
    g = _parent_group(page.state)
    while g is not None:
        if g is grp:
            return True
        g = _parent_group(g)
    return False


def criteria_met(c, env, page, entry):
    """AnimationCriteriaMet 0x5c5781 semantics. entry=True tests "entry only"
    criteria unconditionally (the engine does so while it evaluates the current
    state's transitions, state record +0x68); entry=False applies
    entry_only_skipped()."""
    if not c.p("enabled", True):
        return True
    if not entry and entry_only_skipped(c, page):
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
        # reads only m_ianimationenum (+0x28) and m_ianimationenumvalue (+0x2c)
        r = s32(env.enums.get(c.p("m_ianimationenum", 0))) == s32(c.p("m_ianimationenumvalue", 0))
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
        r = any(criteria_met(k, env, page, entry) for k in c.kids(CLS_CRIT))
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


def criteria_partial(c, enums):
    """Three-valued AnimationCriteriaMet for a known subset of the enum
    variables (`enums`: {variable: value}) and nothing else known: True / False
    when the criterion is decided by them, None when it depends on anything
    else (another variable, a value, an input, the page). Tested as on entry."""
    if not c.p("enabled", True):
        return True
    kind = c.p("m_ianimationcriteria", 0) or 0
    if kind in (CRIT_ANY_OF, CRIT_ALL_OF):
        r = [criteria_partial(k, enums) for k in c.kids(CLS_CRIT)]
        if kind == CRIT_ANY_OF:
            v = True if True in r else (None if None in r else False)
        else:
            v = False if False in r else (None if None in r else True)
        if v is None:
            return None
    elif kind == CRIT_ENUM and (c.p("m_ianimationenum", 0) or 0) in enums:
        v = s32(enums[c.p("m_ianimationenum", 0) or 0]) == s32(c.p("m_ianimationenumvalue", 0))
    else:
        return None
    return (not v) if c.p("m_tnot", False) else v


def owned(node, classes):
    """Nodes of class `classes` (a name or a tuple) that register with `node`:
    filed directly under it or under untyped nodes (folders) of it. Criteria,
    transitions, states and groups all look for their owner by walking up to the
    nearest ancestor that has m_iAnimationSystemType (FindClosestRelevantParent
    0x5aaf49, AddToClosestState 0x5ed6xx, AddToClass 0x5ed37a, AddToParentGroup),
    so a folder's name is irrelevant ("Criterias", "Group Criteria",
    "GroupTransistions", "TransitionStates", ... all ship)."""
    if isinstance(classes, str):
        classes = (classes,)
    out = []
    for c in node.children:
        if c.cls in classes:
            out.append(c)
        elif not typed(c):
            out.extend(owned(c, classes))
    return out


def members(group):
    """m_estatesandgroupslist of a state group: the states and groups whose
    nearest state-group ancestor it is. For the class root only its direct
    children.  (The engine starts a class in its m_edefaultanimstate; when that
    is a group it asks the group for a valid state, command_get_valid_state
    0x5f076f -- Interpreter.start() does the same.)"""
    if group.cls == CLS_CLASS:
        return [k for k in group.children if k.cls in (CLS_STATE, CLS_GROUP)]
    return owned(group, (CLS_STATE, CLS_GROUP))


def _crit_nodes(node):
    return owned(node, CLS_CRIT)


criteria_of = _crit_nodes  # the criteria list of a state / group / transition


# ANIMATION_TYPE the game derives when a state is initialised
# (AnimationStateWM.initialize_external 0x5f0e63 -> DetermineAnimationType 0x5f277a)
#: control action of an ACTION criterion -> ANIMATION_TYPE (0x5ebeb0)
TYPE_BY_ACTION = {
    7: 5,
    0: 4,
    2: 11,
    20: 6,
    11: 7,
    12: 8,
    3: 9,
    4: 10,
    6: 13,
    17: 15,
    18: 16,
    13: 19,
}
#: damage poses for which initialize_external sets m_tupperattack (0x5f0e63)
UPPER_DAMAGE_POSES = frozenset((1, 2, 3, 7, 8, 9, 13, 14, 15, 19, 21, 23, 25, 27))


def _int32(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0
    return v - (1 << 32) if v >= (1 << 31) else v


def criterion_animation_type(k):
    """ANIMATION_TYPE one criterion gives (0 = none): a mapped ACTION, or ENUM
    CHARACTER_MODE (variable 1) == STUNNED (3) -> 12 (0x5ebe9b).  An ANY_OF takes
    the kind of its first child and the values of the ANY_OF node itself
    (0x5f27d3-0x5f282e)."""
    kind = k.p("m_ianimationcriteria") or 0
    if kind == CRIT_ANY_OF:
        kids = _crit_nodes(k) or [x for x in k.children if x.cls == CLS_CRIT]
        if not kids:
            return 0
        kind = kids[0].p("m_ianimationcriteria") or 0
    if kind == CRIT_ACTION:
        return TYPE_BY_ACTION.get(_int32(k.p("m_ianimationaction") or 0), 0)
    if kind == CRIT_ENUM and (k.p("m_ianimationenum") or 0) == 1:
        return 12 if _int32(k.p("m_ianimationenumvalue") or 0) == 3 else 0
    return 0


def state_groups_innermost_first(state):
    out, n = [], state.parent
    while n is not None:
        if n.cls == CLS_GROUP:
            out.append(n)
        n = n.parent
    return out


def determine_animation_type(state):
    """The ANIMATION_TYPE DetermineAnimationType 0x5f277a computes for a state: the
    first criterion with a non-zero result among the state's own criteria, then
    those of each enclosing group, innermost first.  The game writes it over the
    stored m_ianimationtype in initialize_external 0x5f0e63 (read from code; that
    the handler runs for every state in the running game is inferred)."""
    for owner in [state] + state_groups_innermost_first(state):
        for k in _crit_nodes(owner):
            t = criterion_animation_type(k)
            if t:
                return t
    return 0


def own_and_group_actions(state):
    """m_ianimationaction of every top-level ACTION criterion of a state and of its
    groups (negation ignored, ANY_OF not entered: as 0x5f0e63 tests HEAVY_PUNCH)."""
    out = []
    for owner in [state] + state_groups_innermost_first(state):
        for k in _crit_nodes(owner):
            if (k.p("m_ianimationcriteria") or 0) == CRIT_ACTION:
                out.append(_int32(k.p("m_ianimationaction") or 0))
    return out


def group_criteria_met(node, env, page, entry):
    """StateGroupCriteriaMet 0x5c6002: AND over the criteria list."""
    return all(criteria_met(c, env, page, entry) for c in _crit_nodes(node))


# ------------------------------------------------------- interpreter

MAX_RATE = 6.599999904632568  # double @0xa45e90: playpos units per second (UpdatePagePlayPos)
FADE_FLOOR = -0.009999999776482582  # double @0xa45e88: overlay fade-out floor

# ANIMATION_EVENT_TYPES (registration 0x5e54e0): the "Trigger" of an event
EV_PLAY_POS, EV_ENTER_STATE, EV_LEAVE_STATE, EV_TOTAL_PLAY_TIME = 0, 1, 2, 3


def event_trigger(ev):
    return int(ev.p("m_ieventtype", 0) or 0)


def event_at(ev):
    """m_nplaypos: a play position for PLAY_POS, SECONDS of play time for
    TOTAL_PLAY_TIME, not read for ENTER_STATE / LEAVE_STATE."""
    return float(ev.p("m_nplaypos", 0.0) or 0.0)


def event_prelatched(ev, start):
    """SetupNewPage 0x5b8f16-0x5b8f31: a PLAY_POS event whose position is <= the
    play position the page starts at is created already fired; it fires only
    after a loop wrap (never, on a non-looping state)."""
    return event_trigger(ev) == EV_PLAY_POS and event_at(ev) <= start


def event_due(ev, playpos, time_played):
    """CheckPlayPosEvents 0x5b51f3: an unfired PLAY_POS event fires when its
    position <= the page's play position (0x5b55c4), a TOTAL_PLAY_TIME event when
    its seconds <= the page's time played (0x5b52c1). Both compare with <=."""
    now = time_played if event_trigger(ev) == EV_TOTAL_PLAY_TIME else playpos
    return event_at(ev) <= now


def event_timing(kind, raw, duration=None, speed=1.0, start=0.0, loop=False):
    """(playpos, clip_time_s, play_time_s) at which an event of trigger `kind`
    and stored value `raw` first fires in a state entered at play position
    `start` (TransitToState 0x5b4a31: the state's m_nstartplaypos unless the
    transition says otherwise).

    duration  seconds of the state's clip (None = unknown)
    speed     the state's rate factor: its play position advances by
              speed / duration per second of play time (slot speedFactor,
              SetAllSlotBlends 0x5b5193; controller speed factors taken as 1)
    loop      the state loops (m_tislooping)
    clip_time_s is the position on the clip's own timeline (playpos * duration),
    play_time_s the seconds since the state was entered (page +0x34).
      ENTER_STATE      (start, start * duration, 0)
      LEAVE_STATE      (None, None, None)
      PLAY_POS at r    (r, r * duration, (r - start) * duration / speed).  When
                       r <= start the event is created already fired
                       (event_prelatched): on a looping state it fires after the
                       wrap, (1 - start + r) * duration / speed; on a
                       non-looping state never (play_time_s None)
      TOTAL_PLAY_TIME  after t seconds: play position start + t * speed /
                       duration (wrapped on a looping state, None when past the
                       end of a non-looping one), play_time_s = t"""
    speed = float(speed) if speed else 1.0
    start = float(start or 0.0)
    if kind == EV_ENTER_STATE:
        return start, (start * duration if duration else None), 0.0
    if kind == EV_LEAVE_STATE:
        return None, None, None
    if kind == EV_TOTAL_PLAY_TIME:
        if not duration:  # no play position; the clip time only for a start at 0
            return None, (raw * speed if start == 0.0 else None), raw
        pp = start + raw * speed / duration
        if pp > 1.0 + 1e-6:
            if not loop:
                return None, None, raw
            pp = pp % 1.0 or 1.0
        pp = min(pp, 1.0)
        return pp, pp * duration, raw
    clip_t = raw * duration if duration else None
    if clip_t is None:
        return raw, None, None
    if raw > start:
        return raw, clip_t, (raw - start) * duration / speed
    if loop:  # pre-latched: fires once the next lap reaches it
        return raw, clip_t, (1.0 - start + raw) * duration / speed
    return raw, clip_t, None


def _parent_group(node):
    """m_eanimstategroup: the nearest state-group ancestor of a state / group
    (AddToClass 0x5ed37a, AddToParentGroup), None when the class is reached
    first. Folders in between do not matter."""
    n = node.parent
    while n is not None:
        if n.cls == CLS_GROUP:
            return n
        if n.cls == CLS_CLASS:
            return None
        n = n.parent
    return None


def transition_criteria(t, target=None):
    """m_ecriterialist of a transition as the engine holds it: its own criteria
    plus, when the target is a STATE, that state's own criteria -- appended by
    AnimationTransition.initialize_external 0x5f9b13 (this is what gates the
    many criteria-less "trans to Dead" transitions)."""
    out = list(_crit_nodes(t))
    if target is not None and target.cls == CLS_STATE:
        out.extend(c for c in _crit_nodes(target) if not any(c is x for x in out))
    return out


def chain_criteria_met(node, env, page, entry):
    """StateGroupCriteriaMet 0x5c6002 with its recurse flag set: the owning
    groups' criteria (outermost first) AND the node's own criteria list."""
    g = _parent_group(node)
    if g is not None and not chain_criteria_met(g, env, page, entry):
        return False
    return group_criteria_met(node, env, page, entry)


def _top_blends(state):
    """Blend nodes that registered themselves with the state (command_add_layer
    0x5f773f), i.e. not nested inside another blend node."""
    out = []
    stack = list((state.folder("Layers") or state).children)
    while stack:
        n = stack.pop(0)
        if n.cls == CLS_BLEND:
            out.append(n)
        elif n.cls not in (CLS_STATE, CLS_TRANS, CLS_SLOT):
            stack[0:0] = n.children
    return out


def layer_lists(state):
    """m_elayerlistlist: {layer index: [blend nodes]} (command_add_layer appends
    each blend to the inner list numbered by its m_ilayerindex)."""
    out = {}
    for b in _top_blends(state):
        out.setdefault(int(b.p("m_ilayerindex", 0) or 0), []).append(b)
    return out


def _own_events(node):
    """Event nodes owned by `node` itself (not by a transition / nested state / blend)."""
    out = []
    stack = list(node.children)
    while stack:
        n = stack.pop(0)
        if n.cls == CLS_EVENT:
            out.append(n)
        elif n.cls not in (CLS_STATE, CLS_TRANS, CLS_BLEND, CLS_GROUP):
            stack[0:0] = n.children
    return out


def slot_speed(slot):
    """AnimSlot `speedFactor` (native property, object +0x64): the per-slot
    factor in the page rate (SetAllSlotBlends 0x5b5175-0x5b51c7)."""
    v = slot.p("speedFactor", 1.0)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 1.0


def state_speed(state, main_slot=None):
    """(rate factor of a state, basis): the speedFactor of the slots of its
    first layer.  When they differ (blend trees) the rate depends on the blend
    weights; the value given is then that of `main_slot` (else the first slot)
    and the basis says so.  (None, None) without slots."""
    lists = layer_lists(state)
    if not lists:
        return None, None
    slots = lists[min(lists)][0].kids(CLS_SLOT)
    if not slots:
        return None, None
    speeds = [slot_speed(s) for s in slots]
    if max(speeds) - min(speeds) < 1e-9:
        return speeds[0], "slot speedFactor"
    pick = next((i for i, s in enumerate(slots) if s is main_slot), 0)
    return speeds[pick], "one slot's speedFactor (the first layer's slots differ in speed)"


def _slot_duration(slot):
    try:
        return float(str(slot.p("m_sduration", "")).split()[0])
    except (ValueError, IndexError):
        return 0.0


def _soft(state, env=None):
    """Curve applies only with "Soft Blend To" and without AnimationData
    "Force Linear Transitions" (UpdatePageBlendsFaster 0x5b4bd6)."""
    return bool(state.p("m_tusesoftblend", False)) and not (env is not None and env.force_linear)


def _curve(state, raw, env=None):
    if raw <= 0.0:
        return 0.0
    if raw >= 1.0:
        return 1.0
    if not _soft(state, env):
        return raw
    return page_blend_curve(
        raw, state.p("m_nblendpower", 1.0), state.p("m_nblendinitialpower", 1.0)
    )


def _inv_curve(state, value, env=None):
    """Inverse of `_curve` (used by SetupNewPage on re-entry).  The engine's
    `MathLib.InversePowerSmooth` 0x7917a7 is a closed form: r1 = (0.5·(2y)^(1/P))^(1/I),
    r2 = (1 − 0.5·(2 − 2y)^(1/P))^(1/I); it returns r1 only if PowerSmooth(r1) is strictly
    closer to y, else r2.  The bisection here agrees to 4e-8 for P ≥ 1; the closed form can
    produce NaN for P < 1, so it is not used."""
    if not _soft(state, env) or value <= 0.0 or value >= 1.0:
        return min(1.0, max(0.0, value))
    lo, hi = 0.0, 1.0
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        if _curve(state, mid, env) < value:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


class Page:
    """One entry of a page list (SetupNewPage 0x5b7788).

    raw    linear blend, page+0x08 (advanced by dt/ease AFTER the frame's weights)
    shown  the raw value the current frame's weights were built from
    blend  curve(shown): what slot_weights() uses
    rate   playpos units per second, page+0x14 (rebuilt every tick)
    """

    def __init__(self, state, ease_in, playpos, raw=None, sync=False, rng=None, env=None):
        self.state, self.ease_in = state, ease_in
        self.playpos, self.time_played = playpos, 0.0
        self.age, self.done = 0.0, False
        self.duration = _state_duration(state)
        self.raw = (1.0 if ease_in <= 0.0 else 0.0) if raw is None else raw
        self.shown = self.raw
        self.sync, self.rate, self.env = bool(sync), 0.0, env
        self.end_sent = False
        # one blend node per layer list, picked at random (FUN_0047aa2e, rand % n)
        self.layers = []
        for idx, blends in sorted(layer_lists(state).items()):
            pick = rng.randrange(len(blends)) if (rng is not None and len(blends) > 1) else 0
            self.layers.append(blends[pick])
        # PLAY_POS / TOTAL_PLAY_TIME entries {event, fired, pending} (ctrl+0x6c list)
        self.events = []
        for ev in self.event_nodes():
            if event_trigger(ev) in (EV_PLAY_POS, EV_TOTAL_PLAY_TIME):
                self.events.append([ev, event_prelatched(ev, playpos), False])

    def event_nodes(self):
        out = _own_events(self.state)
        for b in self.layers:
            out.extend(_own_events(b))
        return out

    @property
    def blend(self):
        return _curve(self.state, self.shown, self.env)

    def slots(self):
        out = []
        for top in self.layers:
            for blend in [top] + top.descend(CLS_BLEND):
                for s in blend.kids(CLS_SLOT):
                    out.append((blend, s))
        return out

    def slot_playpos(self, blend, slot):
        """Play position handed to one slot (UpdatePagePlayPos 0x5b61b9):
        m_noffset + playpos wrapped into 0..1; 1.0 for an additive blend with
        "Force Playpos=1.0". A state m_eplayposmapper is not applied here."""
        if blend.p("m_tlayeradditive", False) and blend.p("m_tforcedpos", False):
            return 1.0
        v = float(slot.p("m_noffset", 0.0) or 0.0) + self.playpos
        while v > 1.0:
            v -= 1.0
        while v < 0.0:
            v += 1.0
        return v


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
    return owned(node, CLS_TRANS)


transitions_of = _trans_nodes  # the transition list of a state / group / class


def state_events(state):
    """Every event a page of `state` can fire: the state's own and those of all
    its layer blend nodes (a page uses one blend node per layer list). Events
    of the state's transitions are NOT included: they fire with the transition."""
    out = _own_events(state)
    for b in _top_blends(state):
        out.extend(_own_events(b))
    return out


class Interpreter:
    """Replicates state choice, page stacks, play position and blend weights.

    seed / rng        the engine picks one blend node per layer list with rand % n;
                      the choice is drawn from `rng` (default random.Random(seed)).
    done_fallback     pre-v2 behaviour: also run the fallback step whenever the top
                      page has finished, even if the state's criteria still hold
                      (the engine only does so when they fail). Default False.
    """

    def __init__(self, class_root, log=None, seed=0, rng=None, done_fallback=False):
        self.root = class_root
        self.env = Env()
        self.pages = []  # body page stack (Update flag 0), newest last
        self.opages = []  # OVERLAY page stack (Update flag 1)
        self._act_overlay = False  # which stack the current pass evaluates
        self.rr_index = {}  # unused since the scan-start fix; kept for old callers
        self._tested = None  # tested list of the transition evaluation in progress
        self.log = log if log is not None else []
        self.rng = rng if rng is not None else random.Random(seed)
        self.done_fallback = done_fallback
        self.stay = [0.0, 0.0]  # force-stay timer per stack (page list +0x14)
        self.fired = []  # (event node, value) in firing order; cleared by the caller
        self._dirty = False  # ctrl+0x2c: a page was set up / is still blending this frame

    def _cur(self):
        """Top page of the stack the current pass evaluates (criteria ctx)."""
        st = self.opages if self._act_overlay else self.pages
        return st[-1] if st else None

    # ---- engine: command_get_valid_state 0x5f076f
    def get_valid_state(self, group, entry=True):
        """First acceptable member of `group`, scanning cyclically from member 0
        (0x5f0792), or from a uniformly random member when the group has "Choose
        Random State" (+0x0c; 0x5f07bb-0x5f07d7, the draw comes from `rng`).
        While a transition evaluation is running, members already in its tested
        list (_etestedstates, state +0x8c) are skipped and every member examined is
        appended to it."""
        kids = members(group)
        if not kids:
            return None
        n = len(kids)
        start = self.rng.randrange(n) if group.p(RANDOM_STATE, False) else 0
        tested = self._tested
        for i in range(n):
            k = kids[(start + i) % n]
            if tested is not None and any(k is x for x in tested):
                continue
            if not k.p("enabled", True):
                continue
            if tested is not None:
                tested.append(k)
            if not group_criteria_met(k, self.env, self._cur(), entry):
                continue
            if k.cls == CLS_GROUP:
                s = self.get_valid_state(k, entry)
                if s is not None:
                    return s
            else:
                return k
        return None

    # ---- engine: AnimationLib.TransitionMet 0x5c5ea4
    def transition_met(self, t, target, entry=False):
        if not t.p("enabled", True) or not target.p("enabled", True):
            return False
        win = sync_window(t)
        if win is not None:  # super-sync gate: top playpos inside [min, max] local marker
            cur = self._cur()
            p = cur.playpos if cur else 0.0
            if p < win[0] or p > win[1]:
                return False
        crits = transition_criteria(t, target)
        return all(criteria_met(c, self.env, self._cur(), entry) for c in crits)

    # ---- engine: AnimationState.command_get_valid_transition 0x5f7873 +
    # AnimationLib.GetValidStateGroupTransition 0x5c6140 (owning groups)
    def get_valid_transition(self, node, entry=None, fallback=False):
        """(transition, state) or None. `fallback` selects the pass: the normal
        pass only sees non-fallback transitions, the fallback pass only
        "Fallback transition?" ones (m_tfallback must equal the pass).
        entry: test "entry only" criteria unconditionally; default = in the
        normal pass only (EvaluateTransitions sets state +0x68 around it)."""
        if entry is None:
            entry = not fallback
        tested = []  # _etestedstates: each target is tried once per evaluation
        self._tested = tested  # get_valid_state skips / appends its members too
        try:
            return self._valid_transition(node, entry, fallback, tested)
        finally:
            self._tested = None

    def _valid_transition(self, node, entry, fallback, tested):
        owner, first = node, True
        while owner is not None:
            for t in _trans_nodes(owner):
                target = self._resolve_target(t)
                if target is None:
                    continue
                if not first and any(target is x for x in tested):
                    continue
                tested.append(target)
                if bool(t.p("m_tfallback", False)) != bool(fallback):
                    continue
                if not self.transition_met(t, target, entry):
                    continue
                if target.cls == CLS_GROUP:
                    if not chain_criteria_met(target, self.env, self._cur(), entry):
                        continue
                    s = self.get_valid_state(target, entry)
                    if s is None:
                        continue
                    return t, s
                # state target: its own criteria are part of the transition's list
                # (transition_criteria); here only its owning groups' are tested
                g = _parent_group(target)
                if g is not None and not chain_criteria_met(g, self.env, self._cur(), entry):
                    continue
                return t, target
            owner, first = _parent_group(owner), False
        return None

    def _resolve_target(self, trans):
        return self._ref(trans, "m_etostate")

    def _ref(self, node, key):
        return resolve_ref(node, node.p(key), self._index())

    def _index(self):
        if not hasattr(self, "_byid"):
            self._byid = node_index(self.root)
        return self._byid

    def _send(self, ev, value):
        """SendAnimationEvent: recorded in self.fired and the log."""
        self.fired.append((ev, value))
        self.log.append(("event", ev.name, ev.p("m_ianimationevent"), round(value, 4)))

    def _leave(self, page):
        for ev in page.event_nodes():  # LEAVE_STATE events of the page being left
            if int(ev.p("m_ieventtype", 0) or 0) == EV_LEAVE_STATE:
                self._send(ev, 1.0)

    # ---- engine: TransitToState 0x5b4a31 + SetupNewPage 0x5b7788
    def transit(self, state, trans=None, overlay=False):
        """Enter `state` (optionally through transition `trans`). Returns the new
        Page, or None when the engine creates none."""
        overlay = bool(overlay or state.p("m_toverridestate", False))
        cur = self._cur()
        ease_arg = -1.0
        if trans is not None and trans.p("m_toverrideeasein", False):
            ease_arg = float(trans.p("m_neaseinduration", 0.0) or 0.0)
        body_top = self.pages[-1] if (self.pages and not overlay) else None
        start, sync, _rule = start_playpos(
            state,
            trans,
            body_top.state if body_top is not None else None,
            cur.playpos if cur else 0.0,
        )
        return self._setup_page(state, start, sync, ease_arg, overlay)

    def _setup_page(self, state, start, sync, ease_arg, overlay):
        stack = self.opages if overlay else self.pages
        multi = bool(state.p("m_tallowmultipleinstances", False))
        if stack and stack[-1].state is state and not multi:
            return None  # already on top and not "Allow more than once"
        if overlay:
            if self.pages and self.pages[-1].state.p("m_tdisallowoverridelayers", False):
                return None
        if stack:
            self._leave(stack[-1])
        self.stay[1 if overlay else 0] = float(state.p("m_nforcestaytime", 0.0) or 0.0)
        raw0, found = 0.0, False
        if not overlay and not multi:
            for i, pg in enumerate(stack):  # re-entry of a state lower in the stack
                if pg.state is not state:
                    continue
                found = True
                w = pg.blend
                for above in stack[i + 1 :]:
                    w *= 1.0 - above.blend
                if state.p("m_tiswalkcycle", False):
                    start = pg.playpos
                if w < 1.0:
                    s = 1.0 / (1.0 - w)
                    for above in reversed(stack[i + 1 :]):
                        b = above.blend
                        above.raw = _inv_curve(above.state, min(1.0, b * s), self.env)
                        above.shown = above.raw
                        if above.raw >= 1.0 or (1.0 - b) > 0.9998999834060669:
                            s = 1.0
                        else:
                            s = min(1.0, ((1.0 - b) * s) / b) if b > 0.0 else 1.0
                    del stack[i]
                raw0 = _inv_curve(state, w, self.env)
                break
        state_ease = float(state.p("m_neaseinduration", 0.0) or 0.0)
        has_prev = bool(stack) or bool(state.p("m_toverridestate", False))
        if state_ease <= 0.0 or not has_prev or ease_arg == 0.0:
            raw, ease = 1.0, 0.0  # instant: the transition's ease override is ignored
        else:
            raw = raw0 if found else 0.0
            ease = ease_arg if ease_arg > 0.0 else state_ease
        page = Page(state, ease, start, raw=raw, sync=sync, rng=self.rng, env=self.env)
        stack.append(page)
        self._dirty = True
        for ev in page.event_nodes():  # ENTER_STATE events fire at page setup
            if int(ev.p("m_ieventtype", 0) or 0) == EV_ENTER_STATE:
                self._send(ev, 0.0)
        self.log.append(
            ("otransit" if overlay else "transit", state.name, round(ease, 4), round(start, 4))
        )
        return page

    # ---- engine: AnimationState.command_get_fallback_state 0x5f7c4e
    def _fallback_state(self, state):
        n = self._ref(state, "m_efallbackstate")
        if n is None and not state.p("m_toverridestate", False):
            n = self._ref(self.root, "m_edefaultanimstate")
        if n is not None and n.cls == CLS_GROUP:
            n = self.get_valid_state(n, False)
        if n is None:
            n = self._ref(self.root, "m_esafetyfallbackanimstate")
            if n is not None and n.cls == CLS_GROUP:
                n = self.get_valid_state(n, False)
        return n if (n is not None and n.cls == CLS_STATE) else None

    def _fallback(self, state):
        """Fallback pass of EvaluateTransitions: fallback transitions, then the
        fallback / class default / class safety state. (transition, state) or None."""
        hit = self.get_valid_transition(state, fallback=True)
        if hit is not None:
            return hit
        n = self._fallback_state(state)
        return (None, n) if n is not None else None

    @property
    def page(self):
        return self.pages[-1] if self.pages else None

    @property
    def opage(self):
        return self.opages[-1] if self.opages else None

    # ---- engine: EvaluateTransitions 0x5cbbc2, empty-overlay-stack branch
    def _overlay_candidates(self):
        """The class's override list (command_add_state 0x5a03a8): for every
        "Override State" in tree order its outermost state group, or the state
        itself when no group owns it; each once."""
        out = []
        for st in walk(self.root):
            if st.cls != CLS_STATE or not st.p("m_toverridestate", False):
                continue
            top, g = st, _parent_group(st)
            while g is not None:
                top, g = g, _parent_group(g)
            if not any(top is x for x in out):
                out.append(top)
        return out

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

    # ---- engine: EvaluateTransitions 0x5cbbc2, non-empty stack. True = a
    # transition is wanted but held back by the force-stay timer.
    def _evaluate(self, pages, overlay):
        top = pages[-1]
        state = top.state
        if not self._dirty and state.p("m_tnotransitiontests", False) and top.playpos < 1.0:
            return False  # "No Transition Tests": nothing until the clip has ended
        idx = 1 if overlay else 0
        hit = self.get_valid_transition(state)
        if hit is not None:
            if hit[1] is state and not state.p("m_tallowmultipleinstances", False):
                return False
            if self.stay[idx] > 0.0:
                return True
            self.transit(hit[1], hit[0], overlay=overlay)
            for ev in _own_events(hit[0]):  # the transition's own event list
                self._send(ev, 1.0)
            return False
        g = _parent_group(state)
        stays = (g is None or chain_criteria_met(g, self.env, top, False)) and (
            group_criteria_met(state, self.env, top, False)
        )
        if stays and not (self.done_fallback and top.done):
            return False
        if self.stay[idx] > 0.0:
            return True
        fb = self._fallback(state)
        if fb is not None:
            self.transit(fb[1], fb[0], overlay=overlay)
        return False

    # ---- engine: UpdatePageBlendsFaster 0x5b4bd6 + SetAllSlotBlends 0x5b4ef7
    def _page_rate(self, pg):
        """speed * sum(weight * slot speedFactor / duration) over the slots of the
        page's FIRST layer."""
        if not pg.layers:
            return self.env.speed / pg.duration if pg.duration > 0 else 0.0
        blend = pg.layers[0]
        lw = self._layer_weight(blend)
        if lw <= 0.0:
            return 0.0  # layer weight 0: SetAllSlotBlends is not called
        slots = blend.kids(CLS_SLOT)
        durs = [_slot_duration(s) for s in slots]
        rate = 0.0
        if blend.p("m_iblendctrlparam") and len(slots) > 1:
            posw = self._slot_pos_weights(blend, slots)
            for i, d in enumerate(durs):
                if d > 0.0:
                    rate += posw[i] * slot_speed(slots[i]) / d
        else:
            # an uncontrolled blend plays its FIRST child alone (lowest siblingOrder;
            # command_evaluate_blends 0x59e905, see _slot_pos_weights): `slots` is in
            # sibling order, so the rate is that slot's (the first with a duration)
            first = [(d, slot_speed(s)) for d, s in zip(durs, slots) if d > 0.0]
            d, sp = first[0] if first else (pg.duration, 1.0)
            rate = sp / d if d > 0 else 0.0
        return self.env.speed * lw * rate

    # ---- engine: SynchronizePages 0x5ac387
    @staticmethod
    def _synchronize(pages):
        i = len(pages) - 1
        while i > 0:
            if not pages[i].sync:
                i -= 1
                continue
            period, rem, j = 0.0, 1.0, i
            ok = True
            while True:
                last = j == 0 or not pages[j].sync
                w = rem if last else pages[j].raw * rem
                if pages[j].rate <= 0.0:
                    ok = False
                else:
                    period += w / pages[j].rate
                rem -= w
                if last:
                    break
                j -= 1
            if ok and period > 0.0:
                for k in range(j, i + 1):
                    pages[k].rate = 1.0 / period
            i = j - 1

    # ---- engine: CheckPlayPosEvents 0x5b51f3 (normal play)
    def _check_events(self, pg):
        for ent in pg.events:
            ev, fired, pending = ent
            if not fired and event_due(ev, pg.playpos, pg.time_played):  # latch
                self._send(ev, pg.blend)
                ent[1] = True
            if pending:  # skipped by a loop wrap: fires on the next check
                self._send(ev, pg.blend)
                ent[2] = False

    # ---- engine: StateMain 0x5b417b = Update(0, body) then Update(1, overlay);
    # Update 0x5b4613 order: EvaluateTransitions (last frame's playpos), force-stay
    # timer, page weights, DeleteOldPages, SynchronizePages, UpdatePagePlayPos.
    def tick(self, dt):
        self._dirty = bool(self.env.force_update)
        for overlay in (False, True):
            self._act_overlay = overlay
            pages = self.opages if overlay else self.pages
            idx = 1 if overlay else 0
            self.env.overlay_page = self.opages[-1] if self.opages else None
            wanted = False
            if not pages:
                if overlay:
                    self._try_overlay_entry()
            else:
                wanted = self._evaluate(pages, overlay)
            self.stay[idx] = (self.stay[idx] - dt) if wanted else 0.0
            # weights of this frame are built from the blend BEFORE it advances
            for pg in pages:
                pg.shown = pg.raw
                pg.rate = self._page_rate(pg)
            # DeleteOldPages 0x5b9e4c: pages under the highest fully blended page,
            # and pages faded below 0
            i = len(pages) - 1
            while i > 0 and pages[i].raw < 1.0:
                i -= 1
            if i > 0:
                del pages[:i]
            pages[:] = [pg for pg in pages if pg.raw >= 0.0]
            self._synchronize(pages)
            # UpdatePagePlayPos 0x5b56a9
            body_top = self.pages[-1] if self.pages else None
            forced_out = overlay and (
                self.env.no_override_layer
                or (body_top is not None and body_top.state.p("m_tdisallowoverridelayers", False))
            )
            for pg in pages:
                top = pg is pages[-1]
                looping = bool(pg.state.p("m_tislooping", False))
                pg.age += dt
                pg.time_played += dt
                pg.playpos += min(pg.rate, MAX_RATE) * dt
                if pg.playpos > 1.0:
                    if looping:
                        if top:  # unfired PLAY_POS events fire late, flags reset
                            for ent in pg.events:
                                if int(ent[0].p("m_ieventtype", 0) or 0) == EV_PLAY_POS:
                                    if not ent[1]:
                                        ent[2] = True
                                    ent[1] = False
                        while pg.playpos > 1.0:
                            pg.playpos -= 1.0
                    else:
                        pg.playpos = 1.0
                        if top and overlay and not pg.end_sent:
                            self._leave(pg)
                        if top:
                            pg.end_sent = True
                if not looping and pg.playpos >= 1.0:
                    pg.done = True
                if top:
                    self._check_events(pg)
                # page blend (tail of UpdatePagePlayPos)
                if pg.raw < 1.0:
                    self._dirty = True
                if forced_out:
                    pg.raw = 0.0 if pg.ease_in <= 0.0 else pg.raw - dt / pg.ease_in
                elif overlay and top and not looping and pg.playpos >= 1.0:
                    if pg.ease_in > 0.0:
                        pg.raw = max(pg.raw - dt / pg.ease_in, FADE_FLOOR)
                    else:
                        pg.raw = 1.0
                elif pg.raw < 1.0 and pg.ease_in > 0.0:
                    pg.raw += dt / pg.ease_in
                else:
                    pg.raw = 1.0
                pg.raw = min(pg.raw, 1.0)
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
        m_nparentblendposition, linear between neighbours (09j blend trees).

        Without a control parameter (0 = NONE) a blend with two or more slots
        plays its FIRST child alone: weight 1.0 for the slot with the lowest
        siblingOrder (file order among equals), 0.0 for the rest.  Read:
        command_evaluate_blends 0x59e905 writes the blend properties on
        m_echildlist[0] only; the child list is in sibling order (Init 0x59f8b0,
        Node insert 0x48f556); SetAllSlotBlends 0x5b4ef7 sets every slot it was
        not told about to weight 0 and a new source starts at 0 (0x594b36); the
        mixer 0x596532 skips a source below 1e-5."""
        p = blend.p("m_iblendctrlparam")
        if len(slots) < 2:
            return {i: 1.0 for i in range(len(slots))}
        if not p:  # 0 = NONE: first child only
            first = min(range(len(slots)), key=lambda i: (slots[i].p("siblingOrder", 0) or 0, i))
            return {i: (1.0 if i == first else 0.0) for i in range(len(slots))}
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
                    # m_nweight (slot and blend) and m_npriority are not factors: no
                    # reader of either was found in the executable, and every
                    # m_nweight is 1.0 in the shipped classes (1,660 blends, 1,899
                    # slots), so leaving them out changes no shipped result
                    w = sh * posw[i] * lw
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
    ap.add_argument("--seed", type=int, default=0, help="seed of the layer-variant choice")
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
    it = Interpreter(root, seed=args.seed)
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
