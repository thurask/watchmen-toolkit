#!/usr/bin/env python3
"""parts_rule.py -- which of a variant's models the game shows at once.

A character collection (`Thug.fragment`, `Heavies.fragment`, ...) holds MEMBERS:
CharacterHeadModel nodes, each a complete outfit with its own model list (and
texture sheets).  Several members can carry the same name -- the Heavy has 18
"Heavy" nodes: one with an afro, one with long hair, one bald with sunglasses...
The extractor's per-name instance record is the UNION of their model lists, and
up to 1.3.0 the character GLBs showed that union: every hairstyle and every
jacket of a variant at once.

Engine (KapowMultiDEDRM.exe):
  CharacterModelCollection.initialize_local 0x66cd2a   lists the members in child
      order, each with an instance count of 0;
  CharacterModelCollection.command_get_model 0x66ca15  hands out the member that
      was asked for if it is in the list, else the member with the LOWEST
      instance count (the first of them in list order), and counts it;
      command_decrease_model_ref 0x66ccad gives it back (sent only for the body
      model, 0x6791b9; never for a weapon).  Nothing is random.
  CharacterRoot.InstantiateSubSystems 0x67884e         asks the CharacterDef for
      the model (command_get_override_model 0x666d03 -> get_model), creates the
      weapon attach node on bone "Attach RHand" and sends command_set_weapon
      with the root's `_iweapontype` (WEAPON_TYPES: -1 NONE, 0 BASH_1H, 1 BASH_2H;
      default -1);
  CharacterRoot.command_set_weapon 0x694378            -1: no weapon (an existing
      one is removed); 0 / 1: one model from the CharacterDef's "Model coll bash
      1H" / "Model coll bash 2H" collection (same get_model rule), cloned and
      attached.  A character holds at most ONE weapon.

So: the first character of a kind that spawns wears member 1, the second member
2, and so on round the list; a weapon is shown only when the spawner (or a
pick-up) sets a weapon type.  The export shows member 1 unarmed and keeps the
other parts as alternatives (variant_glb: nodes `ALT <model>` / `WPN_<model>`
under a node `alternatives` that is in no scene).
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

MODES = ("game", "all")

MEMBER_RULE = (
    "CharacterModelCollection.command_get_model 0x66ca15: the member asked for, else the "
    "member with the lowest instance count, first in list order -- member 1 for the first "
    "character of this kind, then 2, 3, ... round the list; not random"
)
WEAPON_RULE = (
    "CharacterRoot.command_set_weapon 0x694378 with the root's _iweapontype (default -1 = "
    "NONE): none, or ONE model of the CharacterDef's bash-1H (type 0) or bash-2H (type 1) "
    "collection, attached to bone 'Attach RHand' (InstantiateSubSystems 0x67884e)"
)
ORDER_BASIS = (
    "member order = the collection's child list, which the engine keeps sorted by the "
    "nodes' siblingOrder (child insert 0x48f556: before the first sibling with a larger "
    "order; initialize_local 0x66cd2a walks first child +0x4c / next sibling +0x50); in "
    "the shipped fragments that is also the file order"
)
OUTFIT_RULE = (
    "a model every outfit lists with the same texture sheets is part of the main mesh; "
    "every other model is one node 'OUTFIT <k> <model>' per outfit k that wears it, with "
    "that outfit's sheets.  To show outfit k: hide the 'OUTFIT <shown> ...' nodes, show "
    "the 'OUTFIT <k> ...' nodes"
)


def mode(value=None):
    """The parts mode in force: `value`, else $WATCHMEN_PARTS, else "game".
    "all" = every model the variant's members list, all at once, and every
    weapon in the hand (the files of 1.3.0 and earlier)."""
    v = value or os.environ.get("WATCHMEN_PARTS") or "game"
    if v not in MODES:
        raise ValueError("parts mode must be one of %s, not %r" % (", ".join(MODES), v))
    return v


def members(extract_out, variant):
    """[{index (1-based), head_model_type, head_model_type_name, models}] of the
    collection members named `variant`, in list order.  [] when the fragments
    have no such node (the player characters)."""
    import face_rule

    body = face_rule.head_tables(extract_out)[0]
    out = []
    for i, (typ, models) in enumerate(body.get(variant) or [], 1):
        out.append(
            {
                "index": i,
                "head_model_type": typ,
                "head_model_type_name": face_rule.HEAD_MODEL_TYPES.get(typ),
                "models": [m for m in models if m and "skeleton" not in m.lower()],
            }
        )
    return out


def split(models, member_list, show=1):
    """(shown, alternatives) of `models` (base names, the union the export
    loads) for member number `show`.  A model no member lists (a skeleton, a
    reconstructed part) stays shown.  With no or one member everything is shown."""
    if len(member_list) < 2:
        return list(models), []
    cur = next((m for m in member_list if m["index"] == show), member_list[0])
    listed = {x for m in member_list for x in m["models"]}
    keep = set(cur["models"])
    shown = [m for m in models if m in keep or m not in listed]
    return shown, [m for m in models if m not in shown]


def outfit_node(index, model):
    return "OUTFIT %d %s" % (index, model)


def outfits(models, member_list, sheets_by_member=None, show=1, skip=()):
    """Split `models` (base names, the union the export loads) for a variant with
    several outfits -> (common, nodes):
      common  models of the main mesh: listed by EVERY member with the same texture
              sheets, or listed by none (a skeleton, a reconstructed part);
      nodes   [(node name, member index, model, shown)] one per member and model
              for the rest, in member then model order.
    sheets_by_member: {member index: {model base name (lower): {texture key: sheet}}}
    (characters_export.variant_sheets(node=index-1)).  skip: models the face rig
    stands for (the static head, the body's eye model) -- left out altogether.
    With fewer than two members everything is common."""
    models = [m for m in models if m not in skip]
    if len(member_list) < 2:
        return list(models), []
    sbm = sheets_by_member or {}

    def sig(m, k):
        return tuple(sorted((sbm.get(k) or {}).get(m.lower(), {}).items()))

    listed = {x for m in member_list for x in m["models"]}
    common = []
    for m in models:
        if m not in listed:
            common.append(m)
        elif all(m in mem["models"] for mem in member_list):
            if len({sig(m, mem["index"]) for mem in member_list}) == 1:
                common.append(m)
    nodes = []
    for mem in member_list:
        for m in models:
            if m in mem["models"] and m not in common:
                nodes.append((outfit_node(mem["index"], m), mem["index"], m, mem["index"] == show))
    return common, nodes


def outfit_record(rec, common, nodes, sheets_by_member=None):
    """Add the outfit nodes to a `record(...)`: members[].nodes / .sheets,
    common_models, and `alternatives` = the hidden outfit nodes."""
    sbm = sheets_by_member or {}
    rec = dict(rec)
    rec["common_models"] = list(common)
    rec["members"] = [
        dict(
            m,
            nodes=[n for n, k, _m, _s in nodes if k == m["index"]],
            sheets={
                mdl: {os.path.basename(t).rsplit(".", 1)[0]: sh for t, sh in sorted(tt.items())}
                for mdl, tt in sorted((sbm.get(m["index"]) or {}).items())
            },
        )
        for m in rec["members"]
    ]
    rec["shown_nodes"] = [n for n, _k, _m, s in nodes if s]
    rec["alternatives"] = [{"node": n, "model": m, "members": [k]} for n, k, m, s in nodes if not s]
    rec["outfit_rule"] = OUTFIT_RULE
    return rec


def record(member_list, models, shown, alternatives, show=1):
    """The `parts` extras of a character GLB."""
    exported = set(models)
    mem = []
    for m in member_list:
        d = dict(m, shown=(m["index"] == show))
        missing = [x for x in m["models"] if x not in exported]
        if missing:
            d["not_exported"] = missing
        mem.append(d)
    return {
        "mode": "game",
        "member_shown": show if len(member_list) > 1 else (1 if member_list else None),
        "members": mem,
        "shown_models": list(shown),
        "alternatives": [
            {
                "node": "ALT " + a,
                "model": a,
                "members": [m["index"] for m in member_list if a in m["models"]],
            }
            for a in alternatives
        ],
        "rule": MEMBER_RULE,
        "order_basis": ORDER_BASIS,
    }


def weapon_type_of(collection):
    """WEAPON_TYPES name of a weapon collection, from its name ('…_1H' / '…_2H')."""
    c = (collection or "").upper()
    return "BASH_2H" if c.endswith("_2H") else "BASH_1H" if c.endswith("_1H") else None


def weapon_record(names, sets, colls, always=()):
    """The `weapons` extras: names = attachment node names (`WPN_<model>`),
    sets = {collection: [model base paths]}, colls = the character's collections
    (or "*": a player character, who picks up any weapon), always = nodes that
    are part of the character itself (Twilight Lady's whip)."""
    by_model = {}
    for coll, bases in (sets or {}).items():
        if colls == "*" or coll in (colls or ()):
            for b in bases:
                by_model.setdefault(os.path.basename(b), []).append(coll)
    nodes = []
    for n in names:
        model = n[4:] if n.startswith("WPN_") else n
        cl = sorted(by_model.get(model, []))
        types = sorted({t for t in (weapon_type_of(c) for c in cl) if t})
        nodes.append(
            {
                "node": n,
                "model": model,
                "collections": cl,
                "weapon_types": types,
                "shown": n in always,
            }
        )
    return {
        "shown": [n for n in names if n in always],
        "nodes": nodes,
        "attach_bone": "Attach RHand",
        "rule": WEAPON_RULE,
        "player": colls == "*",
    }


# ------------------------------------------------- weapon class of each clip
def clip_weapon_use(meta):
    """{clip: {classes, basis}}: the weapon class a clip is played with, from
    the states that use it.
      criteria   the state (or its groups) tests WEAPON_ANIMATION_TYPE;
      blend      the clip is one end of a "blend on HAS_2H_WEAPON" /
                 "HAS_WEAPON" layer: the high end is the armed / two-handed
                 clip, the low end the other.
    A clip with no entry is not tied to a weapon class by the data."""
    out = {}

    def add(clip, classes, basis):
        d = out.setdefault(clip, {"classes": set(), "basis": []})
        d["classes"].update(classes)
        if basis not in d["basis"]:
            d["basis"].append(basis)

    for cn, c in sorted((meta.get("classes") or {}).items()):
        for s in c.get("states", []):
            crit = list(s.get("weapon") or [])
            layers = {}
            for row in s.get("clips", []):
                layers.setdefault(row.get("layer") or "", []).append(row)
            for layer, rows in layers.items():
                var = None
                for v in ("HAS_2H_WEAPON", "HAS_WEAPON"):
                    if "blend on " + v + " " in layer:
                        var = v
                pos = [r.get("blend_position") for r in rows]
                if var and len(rows) > 1 and None not in pos and max(pos) > min(pos):
                    for r in rows:
                        if not r.get("clip"):
                            continue
                        hi = r["blend_position"] >= max(pos)
                        lo = r["blend_position"] <= min(pos)
                        if not (hi or lo):
                            continue
                        if var == "HAS_2H_WEAPON":
                            cl = ["BASH_2H"] if hi else ["UNARMED", "BASH_1H"]
                        else:
                            cl = ["BASH_1H", "BASH_2H"] if hi else ["UNARMED"]
                        if crit:
                            cl = [x for x in cl if x in crit] or cl
                        add(r["clip"], cl, "blend on %s (%s end)" % (var, "high" if hi else "low"))
                elif crit:
                    for r in rows:
                        if r.get("clip") and r["clip"] == s.get("main_clip"):
                            add(r["clip"], crit, "criteria WEAPON_ANIMATION_TYPE")
    order = ("UNARMED", "BASH_1H", "BASH_2H")
    return {
        k: {"classes": [x for x in order if x in v["classes"]], "basis": v["basis"]}
        for k, v in sorted(out.items())
    }
