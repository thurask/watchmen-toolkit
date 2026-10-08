#!/usr/bin/env python3
"""characters_export.py -- one folder per character, one GLB per fragment
variant, each GLB carrying EVERY animation of that variant's skeleton.

Characters come straight from the game's fragment definitions
(TNT/Production/Fragments/Enemy/*.fragment + the player refs in the level
fragments).  Bakes are cached per skeleton in <outdir>/_bake/<key>/ so the
export is resumable and variants of the same skeleton share the work.
"""

import os, sys, glob
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0): flat module names must not shadow the stdlib

# skeleton-model ref -> bind key ; bind key -> clip prefix
SKEL_BIND = {
    "Female_Skeleton": "female",
    "Large_Gimp_Skeleton": "gimp",
    "Medium_Skeleton": "medium",
    "Large_Skeleton": "large",
    "Small_Skeleton": "small",
}
MODEL_BIND = (("rorschach", "rsh"), ("owl", "nto"), ("bs2", "bs2"))  # no-skeleton-ref models
# body-clip families per bind (FACE subdirs are excluded -- those are the
# expression poses).  BS2+EN4 = one family (identical 48-bone rig).
CLIP_PREFIX = {
    "female": ("EN4", "BS2"),
    "gimp": ("EN2",),
    "medium": ("EN1",),
    "large": ("EN1",),
    "small": ("EN1",),
    "rsh": ("RSH",),
    "nto": ("NTO",),
    "bs2": ("BS2", "EN4"),
}
# fragment stem -> character folder name (enemy defs); players added explicitly
ENEMY_FRAGS = [
    "Dominatrices",
    "Gimp",
    "GimpGagBall",
    "TwilightLady",
    "Heavies",
    "Thug",
    "ThugFast",
    "ThugBig",
]

# ---- Part 1 (WM06) cast (2026-07-14). Part 1 enemy defs live under Enemy/
# with different stems; the whole cast rides the Medium/Small/Large binds
# (Part 1 ships no Female/Gimp skeletons -- and its M/S/L REST POSES DIFFER
# from Part 2's, so binds must be built from the Part 1 source, not game.naz).
# Clip families per the AnimationClass fragments: Enemy01 = EN1 (medium),
# Enemy03 = EN1+EN3 (small/fast), EnemyBig = EN1+EN2 (large) -- NOTE 'EN2'
# means gimp on Part 2 but big-enemy on Part 1, hence the per-platform map.
# Underboss (BS1 clips, no skeleton ref in its fragment) is NOT exported yet.
ENEMY_FRAGS_P1 = [
    "Biker",
    "BikerBig",
    "Cop",
    "CopFast",
    "CopLeader",
    "Mercenary",
    "MercenaryFast",
    "MercenaryLeader",
    "Minion",
    "MinionFast",
    "Prisoner",
    "PrisonerElite",
    "PrisonerFast",
    "ThugLeader",
]
CLIP_PREFIX_P1 = {"large": ("EN1", "EN2"), "small": ("EN1", "EN3")}


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


def _find_fragment(root, stem):
    import kapow_json

    return kapow_json.find_fragment(root, stem)


def _load_fragment(path):
    """Fragment JSON, parsed from the binary `.fragment` when it is there (a
    `.fragment.json` left by an older extractor is never preferred)."""
    import kapow_json

    return kapow_json.load_fragment(path)


def bind_mismatches(extract_out):
    """{bind key: reason} for every bind in <extract_out>/binds that was NOT built
    from this extract: its skeleton model is on disk and gives other bones or
    another rest pose, or the extract has no such skeleton at all (a Part 2 bind in
    a Part 1 extract).  The test reads the content -- no path or folder name."""
    import contextlib, io, shutil, tempfile
    import build_bind_file
    import watchmenlib as wl

    bdir = os.path.join(extract_out, "binds")
    have = {
        k: os.path.join(bdir, "bind_%s_file_v1.npz" % k)
        for k in wl._SKEL_ASSETS
        if os.path.exists(os.path.join(bdir, "bind_%s_file_v1.npz" % k))
    }
    if not have:
        return {}
    midx = _model_index(extract_out)
    out = {}
    tmp = tempfile.mkdtemp(prefix="wm_bindcheck_")
    try:
        for k, p in sorted(have.items()):
            base = midx.get(os.path.basename(wl._SKEL_ASSETS[k])[:-6])
            if not base or not os.path.exists(base + ".model"):
                if midx:
                    out[k] = "the extract has no %s" % os.path.basename(wl._SKEL_ASSETS[k])
                continue
            ref = os.path.join(tmp, k + ".npz")
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    build_bind_file.build(base + ".model", None, ref)
                a, b = np.load(p, allow_pickle=True), np.load(ref, allow_pickle=True)
            except (Exception, SystemExit):
                continue  # not checkable: say nothing rather than guess
            if [str(x) for x in a["names"]] != [str(x) for x in b["names"]]:
                out[k] = "other bone list than %s" % os.path.basename(base + ".model")
                continue
            dev = max(
                float(np.abs(a["tb"] - b["tb"]).max()), float(np.abs(a["Rb"] - b["Rb"]).max())
            )
            if dev > 1e-4:
                out[k] = "rest pose differs from %s by up to %.4g" % (
                    os.path.basename(base + ".model"),
                    dev,
                )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


#: why a mesh piece has no NORMAL / TANGENT / COLOR_0 -- the case the log line of
#: the character names (variant_glb.buffer_vertex_attrs returns None)
VERTEX_ATTRS_REASON = (
    "the model header does not locate the vertex buffer of these pieces; viewers "
    "compute flat or smooth normals"
)
#: why a console piece has NORMAL / TANGENT but no COLOR_0 (buffer_vertex_attrs:
#: "color_not_decoded")
VERTEX_COLOUR_REASON = (
    "console pieces whose colour byte order is not known: Xbox 360 and PS3 store the "
    "colour bytes in a different order, the console of the source is not known (no "
    "derived_x360 / derived_ps3 path, WATCHMEN_CONSOLE not set) and the model's data "
    "does not show which; NORMAL and TANGENT are written"
)


def not_decoded_extras(part_lists, ragdoll_why=None, dropped=None, attrs_wanted=True):
    """asset.extras.watchmen.not_decoded of a character GLB: what the game data
    holds and this export does NOT -- so that a gap is stated, never silent.  None
    when nothing is missing (every PC Part 2 character).
      vertex_attributes  pieces without NORMAL / TANGENT / COLOR_0 (the header
                         does not locate the buffer:
                         variant_glb.buffer_vertex_attrs)
      vertex_colour      console pieces of a model whose colour byte order is not
                         known: NORMAL / TANGENT written, COLOR_0 (and the
                         vertex-alpha blend) not
      ragdoll            why there is no ragdoll rig / .ragdoll.json
      pieces             mesh pieces no loader could decode (char_lib.note_dropped)"""
    out = {}
    n = k = c = 0
    for parts in part_lists:
        for pt in parts or ():
            n += 1
            at = getattr(pt, "attrs", None)
            k += at is not None
            c += bool(at is not None and at.get("color_not_decoded"))
    if attrs_wanted and k < n:
        out["vertex_attributes"] = {
            "missing": ["NORMAL", "TANGENT", "COLOR_0"],
            "pieces": n,
            "pieces_without": n - k,
            "reason": VERTEX_ATTRS_REASON,
        }
    if attrs_wanted and c:
        out["vertex_colour"] = {
            "missing": ["COLOR_0"],
            "pieces": n,
            "pieces_without": c,
            "reason": VERTEX_COLOUR_REASON,
        }
    if ragdoll_why:
        out["ragdoll"] = {"reason": ragdoll_why}
    if dropped:
        out["pieces"] = list(dropped)
    return {"not_decoded": out} if out else None


def _is_part1(extract_out):
    d = os.path.join(extract_out, "extracted", "TNT", "Production", "Fragments", "Enemy")
    return any(os.path.exists(os.path.join(d, "Biker.fragment" + e)) for e in ("", ".json"))


def track_names_for(extract_out):
    """Part 1 keeps the prefix-insensitive track lookup (not established for Part 1; see
    bake_v4)."""
    return "prefix" if _is_part1(extract_out) else "exact"


# RESTORATION overrides (material -> texture name), applied per variant.
# The game's own data gives the black-afro dominatrices (5/7/10) a black FACE
# (GogoHeadAfro) but a WHITE body: the in-game dark body skin is FemaleSkinBody_Dominatrix1 (white skin x neutral 0.606 shadow overlay, per user NinjaRipper QA); FemaleSkinBody_Black ships completely
# unreferenced (no model or fragment names it).  Clearly authored for these
# variants, so we swap it in.  Disable with WATCHMEN_NO_RESTORE=1.
# runtime-attached head models (not in the fragment's model_ref):
# char -> (head model basename, attach bone).  The head has its own facial rig
# (jaw/lips/eyelids) that the body skeleton doesn't carry -- exported rigid on
# the attach bone, aligned via both models' node FK.
EXTRA_HEADS = {
    "TwilightLady": ("TwilightLady_Head", "Head"),
    # 2026-07-13: Heavy variant is a headless wardrobe set; the
    # face-rigged head was never wired (user QA approved attach)
    "Heavies": ("Heavies_Head_1", "Head"),
    # NiteOwl's mask model carries his facial rig (Bip01>Neck>Head +
    # Jaw/lips/teeth) -- the long-orphaned NTO face poses attach here.
    "NiteOwl": ("NiteOwl_MaskDry2", "Head"),
}

# static game head -> its face-rigged twin (same texture set; the game swaps
# these in for facial closeups).  The static head is dropped from the body
# mesh and the twin attached as the animated face skin.
HEAD_SWAPS = {
    "Girl_Head_White": "FemaleHead_White1",
    "GoGoBlack_Head": "Female_Black1",
    "GoGoWhite1_Head": "Female_White2",
    "GoGoWhite2_Head": "Female_White3",
    "FimaleGimpMask": "FemaleHead_White1_Gimp",
}

# char -> WeaponDB collections (engine: WeaponDB.fragment CharacterModelCollection
# groups per enemy class; players disarm+use any common weapon -> '*').
# For the enemies this is only the FALLBACK: char_weapon_colls reads the two
# collections from the character's own CharacterDef.  (The table gave ThugBig no
# two-handed collection; its CharacterDef names ThugsWeapons_2H.)
# Attach rule (decomp part_0023 + Bs2CharVisual): the engine BoneAttacher snaps
# the weapon model (grip authored at origin) onto the 'Attach RHand' bone;
# TwilightLady's TW_weapon is data-driven instead (HandAttach node:
# attachedBone index + authored local grip offset on the model node).
CHAR_WEAPON_COLLS = {
    "Thug": ("ThugsWeapons_1H", "ThugsWeapons_2H"),
    "ThugFast": ("ThugsWeapons_1H", "ThugsWeapons_2H"),
    "ThugBig": ("ThugsWeaponsBIG_1H",),
    "Heavies": ("HeaviesWeapons_1H", "HeaviesWeapons_2H"),
    "Gimp": ("GimpWeapons_1H", "GimpWeapons_2H"),
    "GimpGagBall": ("GimpWeapons_1H", "GimpWeapons_2H"),
    "Dominatrices": ("DominitrixWeapons_1H",),
    "Rorschach": "*",
    "NiteOwl": "*",
}
ATTACH_BONE = "Attach RHand"

_WEAPON_COLLS = {}


def char_weapon_colls(extract_out, cname):
    """The weapon collections of a character: "*" for a player, else the names
    its CharacterDef points at -- `m_emodelcollbash1h` / `m_emodelcollbash2h`,
    the two collections CharacterRoot.command_set_weapon 0x694378 draws from --
    resolved in WeaponDB.fragment.  Falls back to CHAR_WEAPON_COLLS when the
    fragment does not name them (an extract whose fragments cannot be parsed)."""
    table = CHAR_WEAPON_COLLS.get(cname)
    if table == "*":
        return table
    key = (os.path.abspath(extract_out), cname)
    if key not in _WEAPON_COLLS:
        got = None
        fragroot = os.path.join(extract_out, "extracted", "TNT", "Production", "Fragments")
        try:
            wf, cf = _find_fragment(fragroot, "WeaponDB"), _find_fragment(fragroot, cname)
            if wf and cf:
                names = {}
                for n in _load_fragment(wf).get("nodes_full") or []:
                    for rec in n.get("props") or []:
                        if len(rec) == 3 and rec[0] == "name" and isinstance(rec[2], str):
                            names[n.get("id")] = rec[2]
                for n in _load_fragment(cf).get("nodes_full") or []:
                    if not str(n.get("type") or "").startswith("CharacterDef"):
                        continue
                    p = {r[0]: r[2] for r in n.get("props") or [] if len(r) == 3}
                    if "m_emodelcollbash1h" not in p and "m_emodelcollbash2h" not in p:
                        continue
                    got = []
                    for k in ("m_emodelcollbash1h", "m_emodelcollbash2h"):
                        x = p[k].get("xref") if isinstance(p.get(k), dict) else None
                        if x and names.get(x[-1]) and names[x[-1]] not in got:
                            got.append(names[x[-1]])
                    break
        except (OSError, ValueError, KeyError, IndexError):
            got = None
        _WEAPON_COLLS[key] = tuple(got) if got is not None else table
    return _WEAPON_COLLS[key]


# Whole-texture replacements by material name.  Empty since the variants' texture
# SHEETS are read from the fragment (variant_sheets): the dark skin of Dominatrix_5 /
# 7 / 10 is the "Black" sheet of FemaleSkinBody_White their nodes name, and the
# reconstructed Dominatrix_3 wears its "Dominatrix1" sheet (SYNTH_VARIANTS).
TEX_OVERRIDES = {}

# --- Synthetic (reconstructed) variants (2026-07-16) ---------------------------
# The Dominatrices fragment ships variants 1,2,4..10 -- there is NO Dominatrix_3
# in the shipped data. Pre-release screenshots show a _3 identical to Dominatrix_2
# but with Twilight Lady's hair (the TwilightLadyHair submesh of BS2_WithoutWeapon,
# no standalone hair model exists) tinted the FimaleGimpMask brown, and the dark
# FemaleSkinBody_Dominatrix1 body skin (the "Dominatrix1" sheet). discover() clones
# the base variant (minus its own hair mesh); export() grafts the hair submesh +
# fabricated brown texture. Disable with WATCHMEN_NO_SYNTH=1.
SYNTH_VARIANTS = {
    ("Dominatrices", "Dominatrix_3"): dict(
        base="Dominatrix_2",
        drop_mesh="GoGoWhite_HairLayered2",
        hair_from=("BS2_WithoutWeapon", "TwilightLadyHair"),
        hair_tint_from="FimaleGimpMask1",
        hair_mat="TwilightLadyHair_Brown",
        sheets={"/art/characters/dominatrix/textures/FemaleSkinBody_White.bmp": "Dominatrix1"},
    ),
}


def is_reconstruction(stem, vname):
    """True for a variant the game data does not contain (SYNTH_VARIANTS)."""
    return (stem, vname) in SYNTH_VARIANTS


def reconstruction_extras(stem, vname):
    """asset.extras.watchmen.reconstruction of such a variant's GLB, else None."""
    sv = SYNTH_VARIANTS.get((stem, vname))
    if not sv:
        return None
    return {
        "reconstruction": {
            "shipped": False,
            "base": sv["base"],
            "note": "not a variant of the shipped game: %s.fragment has no node of this "
            "name.  Rebuilt by the toolkit from %s (hair taken from %s, tinted; body skin "
            "sheet %s) after pre-release screenshots.  WATCHMEN_NO_SYNTH=1 leaves it out."
            % (
                stem,
                sv["base"],
                "/".join(sv.get("hair_from") or ()),
                ", ".join(sorted((sv.get("sheets") or {}).values())) or "-",
            ),
        }
    }


_FRAG_NODES = {}


def variant_nodes(extract_out, stem):
    """The model nodes of an enemy fragment, in the engine's child-list order ->
    [{"name", "models": [asset path or ""], "sheets": textureSheetsDescription}].

    One fragment holds several nodes of the same name (18 `Heavy`, 11
    `KnotTop_Large` ...): each is one outfit -- its own model list and its own
    texture sheets.  The game hands them out in turn (CharacterModelCollection.
    command_get_model 0x66ca15: the member used least so far, the first on a tie)."""
    key = (os.path.abspath(extract_out), stem)
    if key not in _FRAG_NODES:
        fragroot = os.path.join(extract_out, "extracted", "TNT", "Production", "Fragments")
        hit = _find_fragment(fragroot, stem)
        nodes = []
        if hit:
            try:
                d = _load_fragment(hit)
            except (OSError, ValueError):
                d = {}
            for n in d.get("nodes_full") or []:
                p = {}
                for rec in n.get("props") or []:
                    if len(rec) == 3:
                        p[rec[0]] = rec[2]
                if isinstance(p.get("modelNames"), list) and p["modelNames"]:
                    desc = p.get("textureSheetsDescription")
                    so = p.get("siblingOrder")
                    nodes.append(
                        {
                            "name": p.get("name") or stem,
                            "models": [str(m or "") for m in p["modelNames"]],
                            "sheets": desc if isinstance(desc, str) else "",
                            "sibling_order": so if isinstance(so, int) else 0,
                        }
                    )
        # the engine's child list is sorted by siblingOrder (Node insert 0x48f556);
        # the sort is stable, so equal orders keep the file order
        nodes.sort(key=lambda n: n["sibling_order"])
        _FRAG_NODES[key] = nodes
    return _FRAG_NODES[key]


def sheet_records(description):
    """textureSheetsDescription -> [(model slot, pivot, lod, texture path, sheet id)].
    "2," then "slot,pivot,lod,<path>,<id>," per record (version 1: "1," and
    "slot,pivot,<path>,<id>,"; parsers 0x4a56c2 / 0x4a544a, getter 0x49f95e)."""
    tok = str(description or "").split(",")
    n = 5 if tok[0].strip() == "2" else 4 if tok[0].strip() == "1" else 0
    out = []
    for i in range(1, len(tok) - n + 1, n) if n else ():
        try:
            lod = int(tok[i + 2]) if n == 5 else 0
            out.append((int(tok[i]), int(tok[i + 1]), lod, tok[i + n - 2], int(tok[i + n - 1])))
        except ValueError:
            break
    return out


_TEX_SHEETS = {}


def _asset_file(extract_out, rel):
    """<extract_out>/extracted/<rel parts>: the exact spelling when it exists, else the
    file whose parts match without regard to letter case (the engine's lookup), else the
    exact path (which then does not exist)."""
    import anim_state_machine

    exact = os.path.join(extract_out, "extracted", *rel)
    if os.path.exists(exact) or not rel:
        return exact
    return (
        anim_state_machine._find_ci(os.path.join(extract_out, "extracted"), "/".join(rel)) or exact
    )


def _texture_sheets(extract_out, path):
    """watchmen_extract.texture_sheets of the Texture asset `path` ([] if missing)."""
    import watchmen_extract as we

    key = (os.path.abspath(extract_out), we.texture_key(path))
    if key not in _TEX_SHEETS:
        rel = [x for x in path.replace("\\", "/").split("/") if x not in ("", ".", "..")]
        got = []
        try:
            with open(_asset_file(extract_out, rel), "rb") as fh:
                hdr = fh.read()
            got = we.texture_sheets(hdr, "<") or we.texture_sheets(hdr, ">")
        except OSError:
            pass
        _TEX_SHEETS[key] = got
    return _TEX_SHEETS[key]


def variant_sheets(extract_out, stem, vname, node=None):
    """Texture sheets the variant's fragment nodes select ->
    {model base name (lower): {texture key: sheet name}}, non-first sheets only.

    A record applies to the meshes of its model slot whose texture is the record's
    path, and picks the sheet with that uniqueID; an unknown id, or no record,
    leaves the texture's first sheet (BaseModel 0x4a56c2, sheet lookup 0x524caf).
    The last record for a (slot, texture) wins, as in the engine's loop.
    node: index among the nodes named `vname` -- that outfit only.  None: every
    model takes its sheets from the first node (file order) that lists it, which
    is what a GLB holding all the variant's models needs."""
    import watchmen_extract as we

    nodes = [n for n in variant_nodes(extract_out, stem) if n["name"] == vname]
    if node is not None:
        nodes = nodes[node : node + 1]
    out, seen = {}, set()
    for n in nodes:
        per = {}
        for slot, _pivot, _lod, path, sid in sheet_records(n["sheets"]):
            if not 0 <= slot < len(n["models"]) or not n["models"][slot]:
                continue
            mdl = os.path.basename(n["models"][slot].replace("\\", "/"))
            mdl = mdl.rsplit(".", 1)[0].lower()
            per.setdefault(mdl, {})[we.texture_key(path)] = (path, sid)
        for m in n["models"]:
            mdl = os.path.basename(m.replace("\\", "/")).rsplit(".", 1)[0].lower()
            if not mdl or mdl in seen:
                continue
            seen.add(mdl)
            for tkey, (path, sid) in sorted(per.get(mdl, {}).items()):
                sheets = _texture_sheets(extract_out, path)
                sh = we.select_sheet(sheets, sid)
                if sheets and sh is not sheets[0] and sh.get("name"):
                    out.setdefault(mdl, {})[tkey] = sh["name"]
    sv = SYNTH_VARIANTS.get((stem, vname))
    if sv and sv.get("sheets") and not os.environ.get("WATCHMEN_NO_RESTORE"):
        base = [n for n in variant_nodes(extract_out, stem) if n["name"] == sv["base"]]
        for n in base[:1]:
            for m in n["models"]:
                mdl = os.path.basename(m.replace("\\", "/")).rsplit(".", 1)[0].lower()
                for path, name in sv["sheets"].items():
                    if mdl:
                        out.setdefault(mdl, {})[we.texture_key(path)] = name
    return out


def _brown_hair_layers(texroots, hair_mat, tint_mat):
    """Fabricate the tinted-hair texture layer dict: recolour the hair diffuse to
    the median-brown of `tint_mat`, preserving strand detail + the alpha cutout;
    reuse the hair's own normal/spec/specSize. Returns a layers dict or None."""
    import char_lib, io
    from PIL import Image

    src = char_lib._find_layers(hair_mat, texroots)
    if not src or "diffuse" not in src:
        return None
    out = dict(src)
    brown = np.array([87.0, 52.0, 27.0])  # fallback = measured FimaleGimpMask brown
    tl = char_lib._find_layers(tint_mat, texroots)
    if tl and "diffuse" in tl:
        g = (
            np.asarray(Image.open(io.BytesIO(tl["diffuse"])).convert("RGB"))
            .reshape(-1, 3)
            .astype(float)
        )
        r, gg, b = g[:, 0], g[:, 1], g[:, 2]
        lum = g.mean(1)
        m = (r > gg) & (gg >= b) & (lum > 30) & (lum < 200)  # brownish: warm, mid-value
        if m.any():
            brown = np.median(g[m], 0)
    im = Image.open(io.BytesIO(out["diffuse"])).convert("RGBA")
    a = np.asarray(im).astype(float)
    rgb = a[..., :3]
    alpha = a[..., 3]
    wl = np.array([0.299, 0.587, 0.114])
    L = rgb @ wl
    bl = float(brown @ wl) or 1.0
    scale = (L / (L.mean() + 1e-6)) * bl  # per-pixel target luminance vs brown
    new = np.clip((brown / bl)[None, None, :] * scale[..., None], 0, 255)
    buf = io.BytesIO()
    Image.fromarray(np.dstack([new, alpha]).astype(np.uint8), "RGBA").save(buf, "PNG")
    out["diffuse"] = buf.getvalue()
    out["alphaMask"] = True
    return out


def _model_index(extract_out):
    """model base name -> base path.  Two models may share a name (AirVent_01): the
    one whose path sorts first is taken, whatever order the file system lists in."""
    idx = {}
    hits = glob.glob(os.path.join(extract_out, "extracted", "**", "*.model"), recursive=True)
    for p in sorted(hits, key=lambda q: (q.replace(os.sep, "/").lower(), q)):
        idx.setdefault(os.path.basename(p)[:-6], p[:-6])
    return idx


def _model_ref_base(extract_out, ref, midx):
    """Base path of a fragment's model reference: the asset path itself
    ('/art/characters/.../X.model') when that file was extracted, else by name."""
    rel = [x for x in ref.replace("\\", "/").split("/") if x not in ("", ".", "..")]
    base = os.path.join(extract_out, "extracted", *rel)[:-6]
    if rel and rel[-1].lower().endswith(".model") and os.path.exists(base + ".model"):
        return base
    return midx.get(rel[-1][:-6] if rel else "")


def discover(extract_out):
    """-> {charName: {variantName: (bindKey, [model base paths])}}"""
    midx = _model_index(extract_out)
    chars = {}
    fragroot = os.path.join(extract_out, "extracted", "TNT", "Production", "Fragments")
    stems = list(ENEMY_FRAGS)
    if _is_part1(extract_out):
        stems += ENEMY_FRAGS_P1
    for stem in stems:
        hit = _find_fragment(fragroot, stem)
        if not hit:
            print("  ! fragment %s not found" % stem)
            continue
        d = _load_fragment(hit)
        vs = {}
        for i in d.get("instances", []):
            refs = i.get("model_ref")
            if not refs:
                continue
            name = i.get("name") or stem
            if name == "(preamble)":
                name = stem
            basenames = [r.rsplit("/", 1)[-1].replace(".model", "") for r in refs]
            refbase = {b: _model_ref_base(extract_out, r, midx) for b, r in zip(basenames, refs)}
            skel = [b for b in basenames if b in SKEL_BIND]
            meshes = [b for b in basenames if b not in SKEL_BIND]
            # runtime head selection: keep ONE head, prefer *_NoSKL (non-NoSKL
            # heads carry their own embedded rig and mis-skin into the chest)
            heads = [m for m in meshes if "head" in m.lower()]
            if heads:
                noskl = [m for m in heads if "noskl" in m.lower()]
                keep = noskl[0] if noskl else heads[0]
                for m in heads:
                    if m != keep:
                        meshes.remove(m)
            if skel:
                key = SKEL_BIND[skel[0]]
            else:
                key = None
                for pat, k in MODEL_BIND:
                    if any(pat in b.lower() for b in basenames):
                        key = k
                        break
                if key is None:
                    continue
            models = [refbase[b] for b in meshes if refbase.get(b)]
            missing = [b for b in meshes if not refbase.get(b)]
            if missing:
                print("  ! %s/%s: missing meshes %s" % (stem, name, missing))
            if models:
                vs[name] = (key, models)
        if vs:
            chars[stem] = vs
    # players (refs live in the level fragments; canonical models).  Both
    # outfits ship: base + _Dry (dried inkblot / dried cowl rain variant).
    for cname, key, variants in [
        ("Rorschach", "rsh", [("Rorschach", "Rorschach"), ("Rorschach_Dry", "Rorschach_Dry")]),
        (
            "NiteOwl",
            "nto",
            [("NiteOwl", "NightOwl_No_Mask"), ("NiteOwl_Dry", "NightOwl_No_MaskDry")],
        ),
    ]:
        vs = {vn: (key, [midx[mdl]]) for vn, mdl in variants if mdl in midx}
        if vs:
            chars[cname] = vs
    # synthetic (reconstructed) variants: clone the base variant's models minus
    # its own hair mesh (export() grafts the replacement hair submesh + texture).
    if not os.environ.get("WATCHMEN_NO_SYNTH"):
        for (frag, vname), sv in SYNTH_VARIANTS.items():
            base = sv["base"]
            if frag in chars and base in chars[frag] and vname not in chars[frag]:
                key, models = chars[frag][base]
                drop = sv.get("drop_mesh")
                models = [m for m in models if not (drop and os.path.basename(m) == drop)]
                chars[frag][vname] = (key, models)
    return chars


def ensure_bind(key, extract_out, naz="game.naz"):
    """bind npz path for key; builds the BS2 (or any missing) bind from the
    model's own embedded skeleton if needed."""
    bdir = os.path.join(extract_out, "binds")
    p = os.path.join(bdir, "bind_%s_file_v1.npz" % key)
    if os.path.exists(p):
        return p
    if key == "bs2":
        import build_bind_file

        midx = _model_index(extract_out)
        build_bind_file.build(midx["BS2_WithoutWeapon"] + ".model", None, p)
        return p
    import watchmenlib as wl

    # extract_dir lets ensure_binds build from the skeleton .model headers
    # already on disk -- a completed extract needs no naz to make binds.
    try:
        got = wl.ensure_binds(naz, bdir, extract_dir=extract_out)
    except RuntimeError:  # no skeleton at all in the extract and the archive
        got = {}
    if key not in got:
        raise FileNotFoundError(
            "no bind for skeleton %r: its skeleton model is not in %s/extracted and the archive"
            " %r %s; name the game archive as the third argument (characters EXTRACT_OUT OUT_DIR"
            " NAZ)"
            % (key, extract_out, naz, "has none" if os.path.exists(str(naz)) else "does not exist")
        )
    return got[key]


LERP_ERR_DEG = 8.0  # max tolerated mid-frame world-rotation error (glTF LERP)


def _lerp_err(pal, bind_B4):
    """Max mid-frame error (deg) if only every other frame is kept and the
    viewer LERPs between them.  pal: (F,NB,3,4) palettes at 2x rate; even
    frames = kept keys, odd frames = ground truth midpoints.  glTF lerps each
    joint's WORLD rotation independently -- fast wrist/finger motion shears
    mid-keyframe (user QA: EN4_COM_WPN_1H_heavy_B hands, 35 deg at 1x)."""
    F, NB = pal.shape[:2]
    if F < 3:
        return 0.0
    A4 = np.concatenate(
        [
            pal.astype(np.float64),
            np.tile(np.array([0, 0, 0, 1.0]).reshape(1, 1, 1, 4), (F, NB, 1, 1)),
        ],
        2,
    )
    W = np.einsum("fkab,kbc->fkac", A4, bind_B4)[:, :, :3, :3]
    import variant_glb as vg

    n = (F - 1) // 2
    Q = vg.batch_m2q(W[::2].reshape(-1, 3, 3)).reshape(-1, NB, 4)
    for f in range(1, len(Q)):
        fl = np.einsum("kc,kc->k", Q[f], Q[f - 1]) < 0
        Q[f, fl] *= -1
    qm = Q[:n] + Q[1 : n + 1]
    qm /= np.linalg.norm(qm, axis=2, keepdims=True)
    x, y, z, w = qm[..., 0], qm[..., 1], qm[..., 2], qm[..., 3]
    R = np.empty(qm.shape[:2] + (3, 3))
    R[..., 0, 0] = 1 - 2 * (y * y + z * z)
    R[..., 0, 1] = 2 * (x * y - z * w)
    R[..., 0, 2] = 2 * (x * z + y * w)
    R[..., 1, 0] = 2 * (x * y + z * w)
    R[..., 1, 1] = 1 - 2 * (x * x + z * z)
    R[..., 1, 2] = 2 * (y * z - x * w)
    R[..., 2, 0] = 2 * (x * z - y * w)
    R[..., 2, 1] = 2 * (y * z + x * w)
    R[..., 2, 2] = 1 - 2 * (x * x + y * y)
    D = np.einsum("fkba,fkbc->fkac", R, W[1 : 2 * n : 2])
    tr = np.clip((np.einsum("fkaa->fk", D) - 1) / 2, -1, 1)
    return float(np.degrees(np.arccos(tr)).max())


def bind_digest(bind):
    """sha1 of what a bake reads from bind npz `bind` (Rb, tb, tloc, par, names): equal for
    two binds that bake the same, whatever their zip bytes."""
    import hashlib

    h = hashlib.sha1()
    with np.load(bind, allow_pickle=True) as z:
        for k in ("Rb", "tb", "tloc", "par", "names"):
            a = z[k]
            if a.dtype.kind in "OUS":
                data = "\0".join(str(x) for x in a.ravel()).encode("utf-8")
            elif a.dtype.kind in "iu":
                data = np.ascontiguousarray(a, "<i8").tobytes()
            else:
                data = np.ascontiguousarray(a, "<f8").tobytes()
            h.update(("%s %s\n" % (k, a.shape)).encode())
            h.update(data)
    return h.hexdigest()


def clip_digest(clip):
    """sha1 of clip file `clip`."""
    import hashlib

    with open(clip, "rb") as fh:
        return hashlib.sha1(fh.read()).hexdigest()


def bake_is_current(path, clip=None, track_names=None, bind=None):
    """Is the cached bake `path` one this toolkit would write?  Yes when it carries the pose
    rule of this baker (bake_v4.POSE_RULE) and was read with this baker's name scan: it
    stores `scan` = bake_v4.NAME_SCAN_START, or its clip file `clip` reads the same with
    the scan that bakes without `scan` used (bake_v4.scan_start_matters; without `clip`
    the scan is not tested).  A bake written by another rule (or before the rule was
    stored) is baked again.  So is one whose stored `track_names` differs from the
    argument `track_names` (the track lookup the caller would bake with); the lookup is
    not tested when either is missing.  Identity: with `clip` the bake must store the
    sha1 of that clip file (`clip_sha`, clip_digest), with `bind` (a bind_digest) the
    digest of the bind it was baked with (`bind_sha`); a bake without them, or of other
    bytes, is baked again."""
    import bake_v4

    try:
        with np.load(path) as z:
            if "rule" not in z.files or int(z["rule"]) != bake_v4.POSE_RULE:
                return False
            if "twist_align" in z.files and int(z["twist_align"]) != 1:
                return False  # baked without the twist pass
            if track_names is not None and "track_names" in z.files:
                if str(z["track_names"]) != track_names:
                    return False  # baked with the other track lookup
            if bind is not None and ("bind_sha" not in z.files or str(z["bind_sha"]) != bind):
                return False  # another bind (or not recorded)
            if clip is not None and (
                "clip_sha" not in z.files or str(z["clip_sha"]) != clip_digest(clip)
            ):
                return False  # other clip bytes (or not recorded)
            if "scan" in z.files:
                return int(z["scan"]) == bake_v4.NAME_SCAN_START
        if clip is None:
            return True
        with open(clip, "rb") as fh:
            return not bake_v4.scan_start_matters(fh.read(400))
    except Exception:  # torn or foreign file: bake again
        return False


def newest_bake_time(cdir):
    """Modification time of the newest raw bake in cache folder `cdir` (None without one)."""
    times = [
        os.path.getmtime(f)
        for f in glob.glob(os.path.join(cdir, "*.npz"))
        if not f.endswith(".tmp.npz")
    ]
    return max(times) if times else None


def bake_cache(key, bind, extract_out, outdir, budget=None):
    """Bake every <prefix>_* clip for this skeleton into <outdir>/_bake/<key>/.
    Resumable (skips existing .npy).  Returns (done, remaining).
    ADAPTIVE RATE: bake at 2x, keep 1x when LERP mid-frame error <= LERP_ERR_DEG,
    escalate to 4x (keeping 2x/4x) for fast clips -- fixes hand/finger shear."""
    import bake_v4

    bake_v4._load_bind(bind)
    _tn = track_names_for(extract_out)
    bv = np.load(bind, allow_pickle=True)
    _NB = len(bv["Rb"])
    _B4 = np.tile(np.eye(4), (_NB, 1, 1))
    _B4[:, :3, :3] = bv["Rb"]
    _B4[:, :3, 3] = bv["tb"]
    prefs = CLIP_PREFIX[key]
    if _is_part1(extract_out):
        prefs = CLIP_PREFIX_P1.get(key, prefs)
    if isinstance(prefs, str):
        prefs = (prefs,)
    clips = {}
    for pref in prefs:
        animroot = os.path.join(extract_out, "extracted", "Animation", pref)
        for dp, dn, fn in os.walk(animroot):
            dn.sort()  # result must not depend on the file system's listing order
            if os.sep + "FACE" in dp or dp.endswith("FACE"):
                continue
            for f in sorted(fn):
                if f.endswith(".animation"):
                    clips[f[:-10].strip()] = os.path.join(dp, f)
    cdir = os.path.join(outdir, "_bake", key)
    os.makedirs(cdir, exist_ok=True)
    import time

    t0 = time.time()
    done = 0
    todo = 0
    _bsha = bind_digest(bind)
    for nm in sorted(clips):
        dst = os.path.join(cdir, nm + ".npz")
        if os.path.exists(dst) and bake_is_current(dst, clips[nm], _tn, _bsha):
            done += 1
            continue
        if budget and time.time() - t0 > budget:
            todo += 1
            continue
        try:
            pal2, dur = bake_v4.bake(nm, 2, bank=clips, track_names=_tn)
            if _lerp_err(pal2, _B4) <= LERP_ERR_DEG:
                pal = pal2[::2]  # 1x is safe
            else:
                pal4, _ = bake_v4.bake(nm, 4, bank=clips, track_names=_tn)
                if _lerp_err(pal4, _B4) <= LERP_ERR_DEG:
                    pal = pal4[::2]  # keep 2x
                else:
                    pal = pal4  # keep 4x
                print("  dense bake %s: %dx frames" % (nm, len(pal) // len(pal2[::2])))
            # fps stored EXPLICITLY (header-exact: frames span dur seconds).
            # Old caches lack 'fps' and used the misread x3 formula -- loader
            # falls back for them, but a full rebake is the real fix.
            np.savez(
                dst + ".tmp.npz",
                pal=pal.astype(np.float32),
                dur=np.float32(dur),
                fps=np.float32(bake_v4.fps_for(len(pal), dur)),
                rule=np.int32(bake_v4.POSE_RULE),
                scan=np.int32(bake_v4.NAME_SCAN_START),
                twist_align=np.int32(1),  # bake(twist_align=None): applied
                track_names=np.str_(_tn),
                bind_sha=np.str_(_bsha),  # identity: which bind and clip bytes
                clip_sha=np.str_(clip_digest(clips[nm])),
            )
            os.replace(dst + ".tmp.npz", dst)  # atomic: chunked runs get killed
            done += 1
        except Exception as e:
            print("  bake fail %s: %s" % (nm, e))
            todo += 1
    return done, todo


def grip_anims(anims, bn, par):
    """Synthesize GRIP 1H/2H overlay poses from the WPN idle clips (engine:
    AnimLayer over the hand bones while armed -- state machine in
    AnimationClass*.fragment; here exposed as 2-frame partial anims to layer
    in NLA, same pattern as FACE poses).  anims: [(name, pal, fps)]."""

    def subtree(root):
        out = set()
        for k, n in enumerate(bn):
            j = k
            while j >= 0:
                if bn[j] == root:
                    out.add(k)
                    break
                j = par[j]
        return out

    rh = sorted(subtree("R Hand"))
    lh = sorted(subtree("L Hand"))
    out = []
    for tag, hand, bones in (
        ("GRIP 1H", "wpn_1h", rh),
        ("GRIP 2H", "wpn_2h", sorted(set(rh + lh))),
    ):
        low = [(a[0].lower(), a) for a in anims]
        src = (
            [a for n, a in low if hand + "_idle_stand" in n]
            or [a for n, a in low if hand + "_idle" in n]
            or [a for n, a in low if hand in n]
        )
        if not src or not bones:
            continue
        pal = src[0][1][:1]
        out.append((tag, np.repeat(pal, 2, axis=0), 2.0, bones))
    return out


def anim_meta_is_current(m, extract_out):
    """True when a stored anim_meta table `m` is what this toolkit would write:
    its own format and content revision, and the format marker of every block the
    build adds (face, combat, fx).  A table from before one of those blocks, or with an older one,
    is not reused by a resumed export -- it would keep the old tables for good."""
    import anim_meta
    import combat_meta
    import face_rule
    import frame
    import fx_meta

    return (
        isinstance(m, dict)
        and m.get("format") == anim_meta.FORMAT
        and m.get("revision") == anim_meta.REVISION  # content, not layout: see anim_meta
        and frame.frame_of(m) == frame.mode()  # a table in the other frame is rebuilt
        and (
            _block_current(m, "face", face_rule.FACE_FORMAT)
            or not face_rule.find_face_fragments(extract_out)
        )
        and _block_current(m, "combat", combat_meta.COMBAT_FORMAT)
        and _block_current(m, "fx", fx_meta.FORMAT)
    )


def _block_current(m, block, fmt):
    """The table has block `block` in format `fmt`, or records that building it in
    that format was attempted and failed (anim_meta.BUILD_FAILED_KEY): a failure
    is the same on every run over the same extract, so it is not retried."""
    import anim_meta

    if m.get(block + "_format") == fmt:
        return True
    failed = m.get(anim_meta.BUILD_FAILED_KEY)
    failed = failed.get(block) if isinstance(failed, dict) else None
    return isinstance(failed, dict) and failed.get("format") == fmt


def anim_meta_failures(m):
    """["combat: attempted, failed: <reason>", ...] of a table (anim_meta.BUILD_FAILED_KEY)."""
    import anim_meta

    failed = m.get(anim_meta.BUILD_FAILED_KEY) if isinstance(m, dict) else None
    return [
        "%s: %s: %s" % (k, v.get("status", "attempted, failed"), v.get("reason"))
        for k, v in sorted(failed.items() if isinstance(failed, dict) else ())
        if isinstance(v, dict)
    ]


#: bump when what the GLB writers put into a file changes for the same inputs and options
GLB_REVISION = 1
#: per output folder: {GLB path relative to the folder: the options it was written with}
OPTIONS_FILE = "_glb_options.json"
OPTIONS_FORMAT = "watchmen-glb-options/1"


def _env_flag(name):
    return (os.environ.get(name) or "").strip()


def writer_options(**over):
    """What the GLB writers' output depends on besides the game files and the bakes:
    the coordinate frame, materials, naming, vertex attributes, the environment switches
    WATCHMEN_MATERIAL_OPTS / NORMALS / CONSOLE / NO_SYNTH / NO_RESTORE and GLB_REVISION.
    `over` adds the options of one command (characters_options)."""
    import canonical_names
    import frame
    import materials
    import variant_glb as vg

    o = {
        "glb_revision": GLB_REVISION,
        "frame": frame.mode(),
        "materials": materials.mode(),
        "names": canonical_names.mode(),
        "vertex_attrs": vg.vertex_attrs_enabled(),
    }
    for k in ("MATERIAL_OPTS", "NORMALS", "CONSOLE", "NO_SYNTH", "NO_RESTORE"):
        o["env_" + k.lower()] = _env_flag("WATCHMEN_" + k)
    o.update(over)
    return o


def characters_options(
    jiggle_model=None,
    face_rule=None,
    face_idle=None,
    parts=None,
    ragdoll=None,
    meta=None,
    world=None,
):
    """writer_options of a `characters` GLB: plus the jiggle cache signature (model,
    constants, the extract's PhysicsWorld values), face rule and idle cycle, parts mode,
    ragdoll, and the format and revision of the animation table embedded in the clips."""
    import face_rule as _fr
    import jiggle_d6
    import parts_rule

    return writer_options(
        jiggle=jiggle_d6.cache_signature(jiggle_model, props=world),
        face_rule=_fr.rule(face_rule),
        face_idle=bool(_fr.idle_enabled(face_idle)),
        parts=parts_rule.mode(parts),
        ragdoll=ragdoll_enabled(ragdoll),
        anim_meta=[meta.get("format"), meta.get("revision")] if isinstance(meta, dict) else None,
    )


def read_glb_options(root):
    """{relative GLB path: options} recorded in folder `root` ({} without a record)."""
    import json

    try:
        with open(os.path.join(root, OPTIONS_FILE), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("format") != OPTIONS_FORMAT:
        return {}
    files = doc.get("files")
    return files if isinstance(files, dict) else {}


def _rel(out, root):
    return os.path.relpath(out, root).replace(os.sep, "/")


def record_glb_options(out, root, options):
    """Record that GLB `out` (under folder `root`) was written with `options` (atomic)."""
    import json

    files = read_glb_options(root)
    files[_rel(out, root)] = options
    path = os.path.join(root, OPTIONS_FILE)
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(
            {"format": OPTIONS_FORMAT, "files": dict(sorted(files.items()))},
            fh,
            indent=1,
            sort_keys=True,
        )
    os.replace(path + ".tmp", path)


def glb_is_current(out, bakes=None, options=None, root=None):
    """Does a resumed export skip `out`?  Yes when the file exists, is in the
    coordinate frame of this run (frame.mode()), is not older than `bakes`, the time
    of the newest raw bake of its skeleton (newest_bake_time; None = not tested), and,
    when `options` is given, was recorded in `root`/_glb_options.json as written with
    exactly these options (writer_options; a GLB without a record is written again).  A
    GLB written with the other --frame or other options is rewritten, so one folder
    holds one set of options; a GLB older than a bake holds clips of a cache that has
    been baked again since."""
    import frame

    if not os.path.exists(out):
        return False
    if bakes is not None and os.path.getmtime(out) < bakes:
        print("  %s is older than a bake of its skeleton: rewriting" % out)
        return False
    if frame.glb_frame(out) not in (None, frame.mode()):
        print("  %s is in the other coordinate frame: rewriting" % out)
        return False
    if options is not None:
        old = read_glb_options(root or os.path.dirname(out)).get(
            _rel(out, root or os.path.dirname(out))
        )
        if old != options:
            if old is None:
                why = "no record of its options"
            else:
                diff = sorted(k for k in set(old) | set(options) if old.get(k) != options.get(k))
                why = "written with other %s" % ", ".join(diff)
            print("  %s: %s: rewriting" % (out, why))
            return False
    return True


def animation_meta(extract_out, outdir):
    """The game's animation metadata table (anim_meta.build), written once to
    <outdir>/anim_meta.json and reused by later (resumed) runs.  None when the
    extract has no AnimationClass fragments (it is optional decoration: a
    failure here must not stop the character export)."""
    import json
    import anim_meta

    path = os.path.join(outdir, "anim_meta.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                m = json.load(fh)
            if anim_meta_is_current(m, extract_out):
                for line in anim_meta_failures(m):  # reused although a block is missing
                    print(
                        "  anim_meta: reusing %s without the %s block (%s); delete the file"
                        " to try again" % (path, line.split(":", 1)[0], line.split(": ", 1)[1])
                    )
                return m  # (a table without the face / combat / fx block is rebuilt)
        except (OSError, ValueError):
            pass
    try:
        if not anim_meta.find_class_fragments(extract_out):
            return None
        bdir = os.path.join(extract_out, "binds")
        m = anim_meta.build(extract_out, binds=bdir if os.path.isdir(bdir) else None)
    except Exception as ex:
        print("  anim_meta: skipped (%s: %s)" % (type(ex).__name__, ex))
        return None
    os.makedirs(outdir, exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as fh:
        json.dump(m, fh, indent=1)
    os.replace(path + ".tmp", path)
    print("  anim_meta: %s -> %s" % (anim_meta.summary(m), path))
    unchecked = pairs_without_contact_check(m)
    if unchecked:
        print(
            "  anim_meta: %d of %d placed pairs have no contact check (a bind or a skeleton"
            " key is missing)" % (len(unchecked), sum(1 for p in m["pairs"] if p.get("placement")))
        )
    for line in anim_meta_failures(m):
        print("  anim_meta: %s (the table is written without that block and reused)" % line)
    return m


def pairs_without_contact_check(m):
    """Indices of the pairs of an anim_meta table that have a placement but no
    `placement.check.contact`: the contact check could not bake one of the two clips."""
    return [
        i
        for i, p in enumerate((m or {}).get("pairs") or [])
        if p.get("placement") and "contact" not in (p["placement"].get("check") or {})
    ]


def ensure_all_binds(keys, extract_out, naz="game.naz"):
    """Build every missing bind of `keys` now ({key: reason} for those that fail), so the
    animation table that is written next can run its contact check on every pair: the
    `bs2` bind used to be built after the table, on the first run of an export."""
    failed = {}
    for key in sorted(keys):
        try:
            ensure_bind(key, extract_out, naz)
        except Exception as ex:
            failed[key] = "%s: %s" % (type(ex).__name__, ex)
    return failed


def jiggle_cache_dir(cdir, jiggle_model=None, props=None):
    """Directory of the jiggled-palette memo of bake cache `cdir`.  Its name
    carries the jiggle model, mode and constants (jiggle_d6.cache_signature), and the
    extract's PhysicsWorld values `props` when they differ from the shipped ones, so a
    directory baked with another model or other values -- including the bare `<key>_j`
    of 1.2.0 -- is never read.  Old directories are simply unused and can be deleted."""
    from jiggle_d6 import cache_signature

    return cdir + "_j_" + cache_signature(jiggle_model, props=props)


def bake_fps(d):
    """The rate a cached bake `d` (an opened npz) is written at: its stored header-exact `fps`,
    else bake_v4.fps_for(frames, dur).  No clip gets a multiplier (variant_glb, "Clip
    timing")."""
    import bake_v4

    if "fps" in d.files:
        return float(d["fps"])
    return bake_v4.fps_for(len(d["pal"]), float(d["dur"]))


#: clip names the retired walk / run multipliers applied to: a jiggle memo of one of them
#: without a stored `fps` was solved at 2.3 / 2.6 x the clip's rate
_LEGACY_MULTIPLIED = ("walk_cycle", "run_cycle")


def jiggle_memo_is_current(memo, bake, clip, fps):
    """Is the jiggled palette `memo` of clip `clip` usable with raw bake `bake` written at
    `fps`?  It must exist, be no older than the bake and have been solved at `fps`: a memo
    stores the rate it was solved at; one without it is from before the rate was stored and
    is used only for a clip that was never written at another rate."""
    if not (os.path.exists(memo) and os.path.getmtime(memo) >= os.path.getmtime(bake)):
        return False
    try:
        with np.load(memo) as z:
            if "fps" in z.files:
                return abs(float(z["fps"]) - float(np.float32(fps))) <= 1e-6 * max(1.0, fps)
    except Exception:  # torn or foreign file: solve again
        return False
    return not any(k in clip for k in _LEGACY_MULTIPLIED)


def clip_loops(meta, name):
    """The game's loop flag of clip `name` in an anim_meta table (False when unknown)."""
    import variant_glb

    return variant_glb.clip_loops(meta, name)


def export(
    extract_out,
    outdir,
    naz="game.naz",
    budget=None,
    only=None,
    jiggle_model=None,
    face_rule=None,
    face_idle=None,
    parts=None,
    ragdoll=None,
):
    """Write <outdir>/<Char>/<Variant>.glb.  Resumable: an existing glb is kept when
    glb_is_current says so -- same coordinate frame, not older than the newest raw bake
    of its skeleton, and recorded in <outdir>/_glb_options.json as written with the
    options of this run (characters_options); any other is written again.  Bakes are
    cached.  budget: seconds of baking per skeleton per call.
    jiggle_model: 'solver' / 'pivot' / 'pinned' (None = jiggle_d6.DEFAULT_MODEL, 'solver';
    'pinned' reproduces the jiggle of 1.2.0 - 1.3.0).
    face_rule: "engine" (default; $WATCHMEN_FACE_RULE) = the face track of the
    game's face animation classes on every body clip, and the game's own
    face-rigged head on the characters whose fragment only lists a static one;
    "legacy" = the name-based faces and static heads of 1.3.0.  face_idle: see
    variant_glb.write_glb.
    parts: "game" (default; $WATCHMEN_PARTS) = the GLB shows what the game shows
    for the variant -- the models of the collection's first member, no weapon --
    and keeps the other members' models and the weapons as alternatives outside
    the scene (parts_rule; node "alternatives"); "all" = every listed model and every weapon
    at once, as up to 1.3.0.
    ragdoll: True (default; $WATCHMEN_RAGDOLL=0 turns it off) = the ragdoll rig of the
    variant's slot-0 model as helper nodes in the GLB (node "ragdoll", outside the
    scene) and <Variant>.ragdoll.json beside it (ragdoll_rig)."""
    import char_lib, variant_glb as vg
    import extract_out as _xo
    import parts_rule

    _xo.require(extract_out)  # a mistyped folder is an error, not an empty export
    _game_parts = parts_rule.mode(parts) == "game"
    import face_rule as _fr

    _engine = _fr.rule(face_rule) == "engine"

    chars = discover(extract_out)
    texroots = [os.path.join(extract_out, "textures")]
    for _k, _why in sorted(bind_mismatches(extract_out).items()):
        print(
            "  WARNING: binds/bind_%s_file_v1.npz does not match this extract (%s). Rest "
            "poses DIFFER between Part 1 and Part 2 -- delete <extract_out>/binds and run "
            "again (binds are rebuilt from the extract's own skeleton models)." % (_k, _why)
        )
    pending = 0
    # every bind first: the animation table's contact check bakes with them
    for _k, _why in ensure_all_binds(
        {k for vs in chars.values() for k, _ in vs.values()}, extract_out, naz
    ).items():
        print("  bind %s: not built before the animation table (%s)" % (_k, _why))
    meta = animation_meta(extract_out, outdir)
    from jiggle_d6 import load_world_props

    world = load_world_props(extract_out)  # this extract's PhysicsWorld
    opts = characters_options(jiggle_model, face_rule, face_idle, parts, ragdoll, meta, world)
    kept = 0
    for cname, vs in sorted(chars.items()):
        if only and cname != only:
            continue
        keys = {k for k, _ in vs.values()}
        for key in sorted(keys):
            bind = ensure_bind(key, extract_out, naz)
            done, todo = bake_cache(key, bind, extract_out, outdir, budget=budget)
            if todo:
                print(
                    "%s [%s]: %d baked, %d remaining -- rerun to continue"
                    % (cname, key, done, todo)
                )
                pending += todo
                continue
            cdir = os.path.join(outdir, "_bake", key)
            baked = newest_bake_time(cdir)
            anims = None  # lazy-load once per key
            for vname, (k2, models) in sorted(vs.items()):
                if k2 != key:
                    continue
                out = os.path.join(outdir, cname, vname + ".glb")
                if glb_is_current(out, baked, opts, outdir):
                    kept += 1
                    continue
                char_lib.dropped_pieces(reset=True)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                if anims is None:
                    # 2026-07-13 perf: npz members are lazy — when a jiggle
                    # memo exists, read pal from the memo ONLY (raw npz is
                    # opened just for dur/fps), halving mount I/O per skeleton.
                    anims = []
                    from jiggle_d6 import apply_jiggle, cache_file

                    jdir = jiggle_cache_dir(cdir, jiggle_model, world)  # disk memo (chunked runs)
                    os.makedirs(jdir, exist_ok=True)
                    jn = 0
                    jig_todo = []  # anim indices needing a jiggle attempt
                    # (was named `pending`, which shadowed the outer resumable-
                    #  bake counter and made export() return a list)
                    for f in sorted(glob.glob(os.path.join(cdir, "*.npz"))):
                        if f.endswith(".tmp.npz"):
                            os.remove(f)  # torn write from a killed run
                            continue
                        nm = os.path.basename(f)[:-4]
                        d = np.load(f)
                        fps = bake_fps(d)  # header-exact, for every clip
                        jf = os.path.join(jdir, cache_file(nm, jiggle_model, clip_loops(meta, nm)))
                        if jiggle_memo_is_current(jf, f, nm, fps):
                            anims.append((nm, np.load(jf)["pal"], fps))
                            jn += 1
                        else:
                            anims.append((nm, d["pal"], fps))
                            jig_todo.append(len(anims) - 1)
                    # 2026-07-13: d6 jiggle promoted into the character glbs
                    # (07-12e capture verdict; was CLI-only in variant_glb).
                    for i in jig_todo:
                        nm, pal, fps = anims[i]
                        try:
                            jp = apply_jiggle(
                                pal,
                                fps,
                                bind,
                                model=jiggle_model,
                                loop=clip_loops(meta, nm),
                                props=world,
                            )
                        except Exception:
                            if jn == 0:
                                break  # skeleton without jiggle bones
                            continue
                        jf = os.path.join(jdir, cache_file(nm, jiggle_model, clip_loops(meta, nm)))
                        np.savez(jf + ".tmp.npz", pal=jp.astype(np.float32), fps=np.float32(fps))
                        os.replace(jf + ".tmp.npz", jf)
                        anims[i] = (nm, jp, fps)
                        jn += 1
                    if jn:
                        print("  jiggle_d6: %d clips [%s]" % (jn, key))
                bv = np.load(bind, allow_pickle=True)
                bn = [str(x) for x in bv["names"]]
                face = None
                midx = _model_index(extract_out)
                usemodels = list(models)
                # the collection member the game hands out first (parts_rule):
                # its models are the character, the other members' are alternatives
                members = parts_rule.members(extract_out, vname)
                shown_models, alt_models = list(models), []
                if _game_parts:
                    names = [os.path.basename(m) for m in models]
                    keep, _alt = parts_rule.split(names, members)
                    shown_models = [m for m in models if os.path.basename(m) in keep]
                    alt_models = [m for m in models if os.path.basename(m) not in keep]
                    usemodels = list(shown_models)
                for m in list(usemodels):
                    base = os.path.basename(m)
                    if base in HEAD_SWAPS and HEAD_SWAPS[base] in midx:
                        usemodels.remove(m)
                        face = _face_attach(
                            midx[HEAD_SWAPS[base]],
                            "Head",
                            bind,
                            bn,
                            cname,
                            extract_out,
                            outdir,
                            align_ref=m,
                        )
                        break
                extra = EXTRA_HEADS.get(cname)
                if cname == "NiteOwl" and "Dry" not in vname and "NiteOwl_Mask2" in midx:
                    extra = ("NiteOwl_Mask2", "Head")  # non-dry cowl variant
                if face is None and extra and extra[0] in midx:
                    face = _face_attach(
                        midx[extra[0]], extra[1], bind, bn, cname, extract_out, outdir
                    )
                if face is None and _engine:
                    # the head the game itself attaches (CharacterHeadModel type
                    # -> head collection); the static copy leaves the body mesh
                    gh = _fr.game_head(extract_out, vname, [os.path.basename(m) for m in usemodels])
                    if gh is not None and gh["head"] in midx:
                        static = [m for m in usemodels if os.path.basename(m) == gh["static"]][0]
                        usemodels.remove(static)
                        face = _face_attach(
                            midx[gh["head"]],
                            "Head",
                            bind,
                            bn,
                            cname,
                            extract_out,
                            outdir,
                            align_ref=static,
                        )
                        face["game_head"] = gh
                        # the rigged head brings its own eyes: the body's
                        # separate eye model would be a second pair
                        # (bare names: the two eye models may point at different
                        # copies of the texture, e.g. knottops/ and bikers/ EnemyEye)
                        fmats = {str(pt[5]) for pt in face["parts"]}
                        for m in list(usemodels):
                            if "eyes" not in os.path.basename(m).lower():
                                continue
                            if all(str(pt[5]) in fmats for pt in char_lib.load_parts([m], bn)):
                                usemodels.remove(m)
                                gh["dropped_body_models"] = gh.get("dropped_body_models", []) + [
                                    os.path.basename(m)
                                ]
                # the texture sheets this variant's nodes select (outfit colours).
                # Several outfits: each takes its sheets from ITS OWN node, and the
                # models that differ between outfits become nodes of their own
                # (parts_rule.outfits) so that an outfit can be switched cleanly.
                vsheets = variant_sheets(extract_out, cname, vname)
                outfit_nodes, msheets, common_names = [], {}, None
                if _game_parts and len(members) > 1:
                    msheets = {
                        m["index"]: variant_sheets(extract_out, cname, vname, node=m["index"] - 1)
                        for m in members
                    }
                    vsheets = msheets.get(1, {})
                    _names = [os.path.basename(m) for m in models]
                    _used = {os.path.basename(m) for m in usemodels}
                    _skip = [
                        n
                        for n in _names
                        if n not in _used and n in {os.path.basename(m) for m in shown_models}
                    ]
                    common_names, outfit_nodes = parts_rule.outfits(
                        _names, members, msheets, skip=_skip
                    )
                    if not any(os.path.basename(m) in common_names for m in usemodels):
                        common_names, outfit_nodes = None, []  # nothing would be left
                    else:
                        usemodels = [m for m in usemodels if os.path.basename(m) in common_names]
                parts = char_lib.load_parts(usemodels, bn, sheets=vsheets)
                # synthetic variant: graft a hair submesh from another model,
                # retextured (Dominatrix_3 = Twilight Lady hair, brown-tinted).
                sv = SYNTH_VARIANTS.get((cname, vname))
                if sv and sv.get("hair_from") and not os.environ.get("WATCHMEN_NO_SYNTH"):
                    hmodel, hmat = sv["hair_from"]
                    if hmodel in midx:
                        # (collapsed-UV tangent sanitation now happens for every
                        # normal-mapped part in variant_glb.write_glb.)
                        hp = [
                            vg.keep_attrs(pt, (pt[0], pt[1], pt[2], pt[3], pt[4], sv["hair_mat"]))
                            for pt in char_lib.load_parts([midx[hmodel]], bn)
                            if pt[5] == hmat
                        ]
                        if hp:
                            parts = list(parts) + hp
                            print(
                                "  synth: %s/%s + %s hair (%d submesh, brown-tinted)"
                                % (cname, vname, hmat, len(hp))
                            )
                tex = char_lib.find_textures(parts, texroots)
                if sv and sv.get("hair_from") and not os.environ.get("WATCHMEN_NO_SYNTH"):
                    bl = _brown_hair_layers(texroots, sv["hair_from"][1], sv["hair_tint_from"])
                    if bl:
                        tex[sv["hair_mat"]] = bl
                if not os.environ.get("WATCHMEN_NO_RESTORE"):
                    for mat, repl in TEX_OVERRIDES.get((cname, vname), {}).items():
                        layers = char_lib._find_layers(repl, texroots)
                        if layers and mat in tex:
                            if "alphaMask" in tex[mat]:
                                layers["alphaMask"] = tex[mat]["alphaMask"]
                            tex[mat] = layers
                            print("  restore: %s/%s %s -> %s" % (cname, vname, mat, repl))
                if face is not None:
                    tex.update(_face_textures(face, texroots, extract_out))
                atts = char_attachments(cname, bind, bn, extract_out)
                for _, apts in atts:
                    tex.update(char_lib.find_textures(apts, texroots))
                alt_parts, outfit_parts, prec = [], [], None
                if _game_parts:
                    _by = {os.path.basename(m): m for m in models}
                    for _node, _k, _m, _sh in outfit_nodes:
                        ap = char_lib.load_parts([_by[_m]], bn, sheets=msheets.get(_k, {}))
                        if ap:
                            outfit_parts.append((_node, ap, _sh))
                            tex.update(char_lib.find_textures(ap, texroots))
                    for a in alt_models if common_names is None else ():
                        ap = char_lib.load_parts([a], bn)
                        if ap:
                            alt_parts.append(("ALT " + os.path.basename(a), ap))
                            tex.update(char_lib.find_textures(ap, texroots))
                    names = [os.path.basename(m) for m in models]
                    prec = parts_rule.record(
                        members,
                        names,
                        [os.path.basename(m) for m in shown_models],
                        [os.path.basename(a) for a in alt_models],
                    )
                    if common_names is not None:
                        _have = {n for n, _p, _s in outfit_parts}
                        prec = parts_rule.outfit_record(
                            prec,
                            [
                                n
                                for n in common_names
                                if n in {os.path.basename(m) for m in usemodels}
                            ],
                            [x for x in outfit_nodes if x[0] in _have],
                            msheets,
                        )
                    always = [n for n, _ in atts] if cname == "TwilightLady" else []
                    prec["weapons"] = parts_rule.weapon_record(
                        [n for n, _ in atts],
                        weapon_sets(extract_out),
                        char_weapon_colls(extract_out, cname),
                        always,
                    )
                grips = grip_anims(anims, bn, bv["par"])
                _rwhy = []
                rag = ragdoll_helpers(extract_out, key, models, bind, out, ragdoll, why=_rwhy)
                # what this GLB does not carry is stated in it and in the log
                _nd = not_decoded_extras(
                    [parts, (face or {}).get("parts")]
                    + [a for _, a in atts]
                    + [a for _, a in alt_parts]
                    + [a for _, a, _s in outfit_parts],
                    _rwhy[0] if _rwhy else None,
                    char_lib.dropped_pieces(reset=True),
                    vg.vertex_attrs_enabled(),
                )
                if _nd and "vertex_attributes" in _nd["not_decoded"]:
                    _va = _nd["not_decoded"]["vertex_attributes"]
                    print(
                        "  note: %s/%s: no NORMAL / TANGENT / COLOR_0 on %d of %d mesh pieces "
                        "(the header does not locate the buffer)"
                        % (cname, vname, _va["pieces_without"], _va["pieces"])
                    )
                if _nd and "vertex_colour" in _nd["not_decoded"]:
                    _vc = _nd["not_decoded"]["vertex_colour"]
                    print(
                        "  note: %s/%s: no COLOR_0 on %d of %d mesh pieces (console pieces "
                        "whose colour byte order is not known: set WATCHMEN_CONSOLE=x360 or "
                        "ps3)" % (cname, vname, _vc["pieces_without"], _vc["pieces"])
                    )
                # write_glb writes <out>.tmp and renames it: chunked runs get
                # SIGTERM'd mid-call and a partial glb must not survive (export
                # skips existing files); the log names the final file.
                vg.write_glb(
                    parts,
                    anims + grips,
                    out,
                    bind,
                    textures=tex,
                    face=face,
                    attachments=atts,
                    meta=meta,
                    face_rule=face_rule,
                    face_idle=face_idle,
                    alt_parts=alt_parts,
                    parts_record=prec,
                    outfit_parts=outfit_parts,
                    asset_extras=__import__("fx_meta").with_attachments(
                        dict(reconstruction_extras(cname, vname) or {}, **(_nd or {})) or None,
                        extract_out,
                        cname,
                        bn,
                        meta,
                    ),
                    ragdoll=rag,
                )
                record_glb_options(out, outdir, opts)
    if kept:
        print("  kept %d existing GLB(s) written with these options" % kept)
    return pending


def ragdoll_enabled(value=None):
    """Export the ragdoll rig?  `value`, else $WATCHMEN_RAGDOLL ("0" = off), else on."""
    if value is not None:
        return bool(value)
    return os.environ.get("WATCHMEN_RAGDOLL", "1") not in ("0", "off", "false", "no")


def ragdoll_source_model(extract_out, key, models):
    """Path of the model whose articulated body the game instantiates for a
    variant = the model in slot 0 of its list (Character vtable slot 41, 0x4bee1e):
    the skeleton model for the enemies, the body model itself for the players and
    the Twilight Lady.  None when it is not on disk."""
    import watchmenlib as wl

    midx = _model_index(extract_out)
    if key in ("rsh", "nto"):
        base = models[0] if models else None
    elif key == "bs2":
        base = midx.get("BS2_WithoutWeapon")
    else:
        base = midx.get(os.path.basename(wl._SKEL_ASSETS.get(key, ""))[:-6])
    path = base + ".model" if base else None
    return path if path and os.path.exists(path) else None


def ragdoll_helpers(extract_out, key, models, bind, out, enabled=None, why=None):
    """ragdoll_rig.glb_helpers for one variant (None when switched off or the
    model has no rig); writes <out stem>.ragdoll.json as a side effect.  Without a
    rig one line says why, and the reason is appended to the list `why`.  The byte
    order is the one the model header states (console headers are big-endian)."""
    if not ragdoll_enabled(enabled):
        return None
    import json
    import ragdoll_rig

    def _none(reason):
        expected = reason.endswith((ragdoll_rig.NO_LAYOUT, ragdoll_rig.NO_BODY))
        print(
            "  %s no ragdoll rig for %s: %s"
            % ("note:" if expected else "WARNING:", os.path.basename(out), reason)
        )
        if why is not None:
            why.append(reason)
        return None

    src = ragdoll_source_model(extract_out, key, models)
    if not src:
        return _none("the slot-0 model of bind %r is not in the extract" % key)
    try:
        mb = _read_bytes(src)
        order = ragdoll_rig.byte_order(mb)
        rig, reason = ragdoll_rig._build(mb, order)
    except Exception as e:  # the rig is optional, the character is not
        return _none("%s not read: %s" % (os.path.basename(src), e))
    if rig is None:
        return _none("%s: %s" % (os.path.basename(src), reason))
    mat = None
    pb = os.path.join(extract_out, "extracted", "pivotbooks", "default.pb")
    if os.path.exists(pb):
        try:
            mat = ragdoll_rig.material_from_pivot_book(_read_bytes(pb), ragdoll_rig.sheet_for(key))
        except (KeyError, ValueError) as e:
            print("  ! pivot book %s: %s" % (pb, e))
    bv = np.load(bind, allow_pickle=True)
    names = [str(x) for x in bv["names"]]
    doc = ragdoll_rig.sidecar(
        rig,
        names,
        material=mat,
        source_model=os.path.relpath(src, os.path.join(extract_out, "extracted")).replace(
            os.sep, "/"
        ),
        group=ragdoll_rig.group_for(key),
        glb=os.path.basename(out),
    )
    side = out[:-4] + ".ragdoll.json"
    with open(side + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, separators=(",", ":"))
    os.replace(side + ".tmp", side)
    helpers = ragdoll_rig.glb_helpers(rig, names, bv["Rb"], bv["tb"], material=mat)
    helpers["extras"]["sidecar"] = os.path.basename(side)
    helpers["extras"]["source_model"] = doc["source_model"]
    return helpers


def weapon_sets(extract_out):
    """WeaponDB.fragment -> {collection name: [model base paths]} (file-only)."""
    hit = _find_fragment(
        os.path.join(extract_out, "extracted", "TNT", "Production", "Fragments"), "WeaponDB"
    )
    if not hit:
        return {}
    d = _load_fragment(hit)
    props = {n["id"]: {k: v for k, t, v in n["props"]} for n in d["nodes_full"]}
    colls = {
        i: p["name"]
        for i, p in props.items()
        if isinstance(p.get("name"), str) and "Weapons" in p.get("name", "")
    }
    ex = os.path.join(extract_out, "extracted")
    out = {}
    for i, p in props.items():
        lp = p.get("logicalParent")
        ref = lp.get("ref") if isinstance(lp, dict) else None
        if ref in colls and p.get("modelNames"):
            m = p["modelNames"][0].lstrip("/")
            base = os.path.join(ex, *m.split("/"))[:-6]  # strip .model
            if not os.path.exists(base + ".model"):
                cand = sorted(
                    glob.glob(os.path.join(ex, "**", os.path.basename(m)), recursive=True)
                )
                if not cand:
                    continue
                base = cand[0][:-6]
            out.setdefault(colls[ref], []).append(base)
    return out


def _q2m_conj(q):
    """fragment/model-node quaternion (xyzw) -> rotation in the conj bind gauge."""
    import build_bind_file as bbf

    x, y, z, w = q
    return bbf.q2m(np.array([-x, -y, -z, w]))


def _weapon_attach_parts(model_base, slot, bind, bn, offset=None):
    """Decode an unskinned prop model rigid on bind slot `slot`.
    Weapon meshes are authored with the grip at the model origin; engine
    BoneAttacher gives them the attach bone's world transform (identity local),
    optionally composed with an authored (localPos, localOrient) offset
    (TwilightLady's TW_weapon).  Verts -> body bind space, all weights on slot."""
    import watchmen_extract as we, struct as st
    import variant_glb as _vga

    bv = np.load(bind, allow_pickle=True)
    Rb, tbb = bv["Rb"][slot], bv["tb"][slot]
    M, t = Rb, tbb
    if offset is not None:
        p, q = offset
        Ro = _q2m_conj(q)
        M = Rb @ Ro
        t = Rb @ np.asarray(p, float) + tbb
    mh = _read_bytes(model_base + ".model")
    ms = _read_bytes(model_base + ".model.stream")
    plat = we.console_platform_for(model_base + ".model")  # the console colour order
    import char_lib as _cl

    # the header states the byte order (the descriptor-count rule tied on
    # single-submesh console models: WPN_2x4_2H was lost on Xbox 360 / PS3)
    order = _cl.model_order(mh, ms, os.path.basename(model_base))
    be = order == ">"
    descs = we.find_descriptors(mh, order)
    mats = we.extract_materials(mh)
    smat = we.submesh_materials(mh, order)
    wname = os.path.basename(model_base)
    parts = []
    off = 0
    for si_, (nv, stride, ib) in enumerate(descs):
        himax = len(ms) - nv * stride - ib
        c = off
        vbo = None
        while c <= min(off + 65536, himax):
            if (
                we._sane(st.unpack_from(order + "f", ms, c)[0])
                and we._vb_ok(ms, c, nv, stride, ib, order)
                and we._ib_ok(ms, c, nv, stride, ib, order)
            ):  # clean IB -> skip false-positive VB
                vbo = c
                break
            c += 1
        if vbo is None:
            _cl.note_dropped(model_base, si_, nv, stride, ib, order, _cl.NO_BUFFER)
            continue
        v, _, uv = we._decode_sub(ms, vbo, nv, stride, be)
        ibo = vbo + nv * stride
        T = []
        for tt in range(ib // 6):
            x, y, z = st.unpack_from(order + "3H", ms, ibo + tt * 6)
            if x < nv and y < nv and z < nv and len({x, y, z}) == 3:
                T.append((x, y, z))
        off = ibo + ib
        if not v or not T:
            _cl.note_dropped(model_base, si_, nv, stride, ib, order, _cl.NO_TRIANGLES)
            continue
        V = (np.array(v, float) @ M.T) + t
        SI = np.full((len(V), 4), slot, np.uint16)
        SW = np.zeros((len(V), 4), np.float32)
        SW[:, 0] = 1
        parts.append(
            _vga.with_attrs(
                (
                    V,
                    SI,
                    SW,
                    np.array(T),
                    np.array(uv if uv else [(0.0, 0.0)] * len(V), np.float32),
                    (
                        mats[smat[si_][1]]
                        if si_ < len(smat) and smat[si_][1] < len(mats)
                        else (mats[si_] if si_ < len(mats) else "%s_sub%d" % (wname, si_))
                    ),
                ),
                # the mesh buffer's own vectors, turned with the positions
                _vga.buffer_vertex_attrs(mh, ms, order, vbo, nv, stride, plat),
                rot=M,
            )
        )
    return parts


def _tw_weapon_spec(extract_out, bn):
    """TwilightLady's data-driven weapon: (model base, slot, (pos, quat)) from
    Bs2CharVisual.fragment (HandAttach node: attachedBone + child model node
    local offset), or None."""
    hit = _find_fragment(
        os.path.join(extract_out, "extracted", "TNT", "Production", "Fragments"), "Bs2CharVisual"
    )
    if not hit:
        return None
    d = _load_fragment(hit)
    props = {n["id"]: {k: v for k, t, v in n["props"]} for n in d["nodes_full"]}
    for i, p in props.items():
        mns = p.get("modelNames") or []
        if any("weapon" in m.lower() for m in mns):
            lp = p.get("logicalParent")
            par = props.get(lp.get("ref")) if isinstance(lp, dict) else None
            slot = (
                par["attachedBone"]
                if par and isinstance(par.get("attachedBone"), int)
                else bn.index(ATTACH_BONE)
            )
            m = mns[0].lstrip("/")
            ex = os.path.join(extract_out, "extracted")
            base = os.path.join(ex, *m.split("/"))[:-6]
            if not os.path.exists(base + ".model"):
                # the reference's folder case ("/Art/Characters/...") is not the
                # extract's ("art/characters/..."): find it by name, as weapon_sets
                cand = sorted(
                    glob.glob(os.path.join(ex, "**", os.path.basename(m)), recursive=True)
                )
                if not cand:
                    return None
                base = cand[0][:-6]
            return base, slot, (p.get("localPos", [0, 0, 0]), p.get("localOrient", [0, 0, 0, 1]))
    return None


def char_attachments(cname, bind, bn, extract_out):
    """-> [(name, parts)] weapon attachments for this character (file-only)."""
    out = []
    if cname == "TwilightLady":
        spec = _tw_weapon_spec(extract_out, bn)
        if spec:
            base, slot, off = spec
            out.append(
                (
                    "WPN_" + os.path.basename(base),
                    _weapon_attach_parts(base, slot, bind, bn, offset=off),
                )
            )
        return out
    colls = char_weapon_colls(extract_out, cname)
    if not colls:
        return out
    ws = weapon_sets(extract_out)
    if colls == "*":
        bases = sorted({b for lst in ws.values() for b in lst}, key=os.path.basename)
        if cname == "NiteOwl":  # his gadget (CharacterRootTemplate_NiteOwl)
            gg = glob.glob(
                os.path.join(extract_out, "extracted", "**", "GrappringGun.model"), recursive=True
            )
            if gg:
                bases.append(min(gg)[:-6])
    else:
        bases = []
        for c in colls:
            for b in ws.get(c, []):
                if b not in bases:
                    bases.append(b)
    if ATTACH_BONE not in bn:
        return out
    slot = bn.index(ATTACH_BONE)
    seen = set()
    for base in bases:
        nm = os.path.basename(base)
        if nm in seen:
            continue
        seen.add(nm)
        parts = _weapon_attach_parts(base, slot, bind, bn)
        if parts:
            out.append(("WPN_" + nm, parts))
    return out


def _rigid_attach_parts(model_base, bone, bind, bn):
    """Decode a runtime-attached model (e.g. facial-rigged head) as rigid parts
    on `bone`: verts moved from the model's own node space into the body's bind
    space, all weights on the attach bone's slot."""
    import parse_model_nodes, build_bind_file as bbf
    import watchmen_extract as we, struct as st
    import variant_glb as _vga

    mh = _read_bytes(model_base + ".model")
    ms = _read_bytes(model_base + ".model.stream")
    plat = we.console_platform_for(model_base + ".model")  # the console colour order
    names, pos, quat, parent = parse_model_nodes.parse(mh)
    pos[0] = 0
    quat[0] = np.array([0, 0, 0, 1.0])
    parent[0] = -1
    Wq = bbf.fk_conj(names, pos, quat, parent)
    # tb-style FK positions in the same gauge
    N = len(names)
    tb = np.zeros((N, 3))
    R = [bbf.q2m(Wq[i]) for i in range(N)]
    order = sorted(range(N), key=lambda k: 0 if parent[k] < 0 else 1)
    done = [False] * N

    def go(k):
        if done[k]:
            return
        pnt = parent[k]
        if pnt >= 0:
            go(pnt)
            tb[k] = tb[pnt] + R[pnt] @ pos[k]
        else:
            tb[k] = pos[k]
        done[k] = True

    for k in range(N):
        go(k)
    hi = names.index(bone)
    bv = np.load(bind, allow_pickle=True)
    bidx = bn.index(bone)
    Rb, tbb = bv["Rb"][bidx], bv["tb"][bidx]
    M = Rb @ np.linalg.inv(R[hi])
    t = tbb - M @ tb[hi]
    # byte order: console (X360/PS3) model headers/streams are big-endian; the
    # header states which (char_lib.model_order).
    import char_lib as _cl

    order = _cl.model_order(mh, ms, os.path.basename(model_base))
    be = order == ">"
    descs = we.find_descriptors(mh, order)
    mats = we.extract_materials(mh)
    smat = we.submesh_materials(mh, order)
    parts = []
    off = 0
    for si_, (nv, stride, ib) in enumerate(descs):
        himax = len(ms) - nv * stride - ib
        c = off
        vbo = None
        while c <= min(off + 65536, himax):
            if (
                we._sane(st.unpack_from(order + "f", ms, c)[0])
                and we._vb_ok(ms, c, nv, stride, ib, order)
                and we._ib_ok(ms, c, nv, stride, ib, order)
            ):  # clean IB -> skip false-positive VB
                vbo = c
                break
            c += 1
        if vbo is None:
            _cl.note_dropped(model_base, si_, nv, stride, ib, order, _cl.NO_BUFFER)
            continue
        v, _, uv = we._decode_sub(ms, vbo, nv, stride, be)
        ibo = vbo + nv * stride
        T = []
        for tt in range(ib // 6):
            x, y, z = st.unpack_from(order + "3H", ms, ibo + tt * 6)
            if x < nv and y < nv and z < nv and len({x, y, z}) == 3:
                T.append((x, y, z))
        off = ibo + ib
        if not v or not T:
            _cl.note_dropped(model_base, si_, nv, stride, ib, order, _cl.NO_TRIANGLES)
            continue
        V = (np.array(v, float) @ M.T) + t
        SI = np.full((len(V), 4), bidx, np.uint16)
        SW = np.zeros((len(V), 4), np.float32)
        SW[:, 0] = 1
        parts.append(
            _vga.with_attrs(
                (
                    V,
                    SI,
                    SW,
                    np.array(T),
                    np.array(uv if uv else [(0.0, 0.0)] * len(V), np.float32),
                    (
                        mats[smat[si_][1]]
                        if si_ < len(smat) and smat[si_][1] < len(mats)
                        else "head_sub%d" % si_
                    ),
                ),
                _vga.buffer_vertex_attrs(mh, ms, order, vbo, nv, stride, plat),
                rot=M,
            )
        )
    return parts


def _icp_refine(A, B, M, t, iters=7):
    """Rigid ICP: refine (M,t) so that M@A+t lands on B (both (N,3))."""
    rng = np.random.default_rng(0)
    A = A[rng.choice(len(A), min(1000, len(A)), replace=False)]
    B = B[rng.choice(len(B), min(2500, len(B)), replace=False)]
    for _ in range(iters):
        A2 = A @ M.T + t
        d = ((A2[:, None, :] - B[None, :, :]) ** 2).sum(2)
        nb = B[d.argmin(1)]
        ca, cb = A2.mean(0), nb.mean(0)
        H = (A2 - ca).T @ (nb - cb)
        U, S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1] *= -1
            R = Vt.T @ U.T
        M = R @ M
        t = R @ t + (cb - R @ ca)
    A2 = A @ M.T + t
    d = np.sqrt(((A2[:, None, :] - B[None, :, :]) ** 2).sum(2).min(1))
    return M, t, float(np.median(d))


def _face_textures(face, texroots, extract_out):
    """Texture layers of the face parts.  A head taken from the head collection
    uses the texture SHEET that collection node names: when that sheet overrides a
    layer with another texture (face_rule.sheet_overrides -- KnotTop_Large's
    Large_Head_1 wears the "Goatee" sheet of bikers/head.bmp, whose diffuse is
    bikers/head02.bmp), the layer is taken from there.  The part gets a material
    key of its own, so a body part with the same texture keeps the default sheet."""
    import char_lib, face_rule, variant_glb as vg
    import watchmen_extract as we

    gh = face.get("game_head") or {}
    over = face_rule.sheet_overrides(extract_out, gh.get("texture_sheets"))
    if over:
        used, parts = [], []
        for pt in face["parts"]:
            nm = pt[5]
            o = over.get(we.texture_key(getattr(nm, "path", None) or ""))
            if o:
                new = we.TexRef(str(nm), "%s#sheet=%s" % (nm.path, o["sheet"]))
                pt = vg.keep_attrs(pt, (pt[0], pt[1], pt[2], pt[3], pt[4], new))
                pt_over = dict(o, texture=nm.path)
                if pt_over not in used:
                    used.append(pt_over)
            parts.append(pt)
        face["parts"] = parts
        gh["sheet_overrides"] = used
    tex = {}
    for pt in face["parts"]:
        nm = pt[5]
        if nm in tex:
            continue
        path = getattr(nm, "path", None) or ""
        base, _, sheet = path.partition("#sheet=")
        layers = char_lib._find_layers(we.TexRef(str(nm), base) if sheet else nm, texroots)
        if layers and sheet:
            layers = dict(layers)
            for layer, opath in over[we.texture_key(base)]["overrides"].items():
                src = char_lib._find_layers(we.texture_ref(opath), texroots) or {}
                if layer in src:
                    layers[layer] = src[layer]
                    if layer == "diffuse":
                        if src.get("alphaMask"):
                            layers["alphaMask"] = True
                        else:
                            layers.pop("alphaMask", None)
                        for _k in ("texAlpha", "texAlphaFlag"):
                            if _k in src:
                                layers[_k] = src[_k]
                            else:
                                layers.pop(_k, None)
                else:
                    print("  ! sheet %s: %s layer of %s not found" % (sheet, layer, opath))
        if layers:
            tex[nm] = layers
    return tex


def _face_attach(model_base, bone, bind, bn, cname, extract_out, outdir, align_ref=None):
    """Animated face attach: face bind from the head model's own nodes, its
    family's expression poses baked on, alignment M,t mapping face-model space
    -> body bind space (same node-FK alignment as the old rigid attach)."""
    import bake_v4, char_lib, parse_model_nodes, build_bind_file as bbf
    import face_export

    # face bind
    fdir = os.path.join(extract_out, "binds", "face")
    os.makedirs(fdir, exist_ok=True)
    head = os.path.basename(model_base)
    fbind = os.path.join(fdir, "bind_face_%s.npz" % head)
    if not os.path.exists(fbind):
        bbf.build(model_base + ".model", None, fbind)
    # alignment from both models' conj-gauge FK
    names, pos, quat, parent = parse_model_nodes.parse(_read_bytes(model_base + ".model"))
    pos[0] = 0
    quat[0] = np.array([0, 0, 0, 1.0])
    parent[0] = -1
    fb = np.load(fbind, allow_pickle=True)
    fbn = [str(x) for x in fb["names"]]
    hi = fbn.index(bone)
    Rf, tf = fb["Rb"][hi], fb["tb"][hi]
    bv = np.load(bind, allow_pickle=True)
    bidx = bn.index(bone)
    Rb, tbb = bv["Rb"][bidx], bv["tb"][bidx]
    M = Rb @ np.linalg.inv(Rf)
    t = tbb - M @ tf
    # face parts (face-model space) + family poses
    import variant_glb as _vgk

    parts = char_lib.load_parts([model_base], fbn)
    proxy_slots = []
    if align_ref is None:
        # 2026-07-13: NAME-PROXY RIDE (see docs/ENGINE_CONSTANTS.md,
        # now applied after user QA: NiteOwl cowl moved separately from the
        # body).  The cowl/head models blend real weight onto Bip01/Neck/
        # clavicles/twists; a rigid Head ride over-rotates all of it.  Face-rig
        # slots NOT under Head whose names exist in the body bind ride the
        # matching BODY joint via the same per-body-slot proxy mechanism the
        # weight-transfer path uses (write_glb unchanged).
        fpar0 = fb["par"]

        def _below0(k):
            pnt = fpar0[k]
            while pnt >= 0:
                if fbn[pnt] == "Head":
                    return True
                pnt = fpar0[pnt]
            return False

        NAME_MAP = {"Bip01": "Bip"}
        slotmap = {}
        proxy_align = []
        B4b = np.eye(4)
        B4fk = np.eye(4)
        for k, n in enumerate(fbn):
            if _below0(k) or n in ("Head", "GamePivot", "Interact", "interact"):
                continue
            bnm = NAME_MAP.get(n, n)
            if bnm in bn:
                bs = bn.index(bnm)
                # PER-BONE alignment (2026-07-13 giraffe fix): engine drives
                # the face-rig bone with the body bone's WORLD, skinning stays
                # against the FACE rig's own bind => proxy skin = P_body(bs) @
                # B_body(bs) @ inv(B_face(k)).  Equals the global head-frame
                # M4 only when the two binds align (Neck/clavicles/twists do;
                # NTO cowl 'Bip01' is 0.34m/122deg off -> M4 slung its verts
                # around the root = giraffe neck).
                B4b = np.eye(4)
                B4b[:3, :3] = bv["Rb"][bs]
                B4b[:3, 3] = bv["tb"][bs]
                B4fk = np.eye(4)
                B4fk[:3, :3] = fb["Rb"][k]
                B4fk[:3, 3] = fb["tb"][k]
                # ALIGNMENT GATE (giraffe fix, round 2): only proxy bones whose
                # face bind agrees with the body bind under the head-frame M4.
                # The cowl is authored rest-coherent (one rigid M4 places ALL
                # of it correctly), so a misaligned 'match' (NTO Bip01: 0.34m/
                # 122deg vs body Bip) is NOT an engine ride target - driving
                # its verts with the body-root palette slings the skirt base
                # around = giraffe neck. Misaligned bones keep the anchor ride.
                Mk = B4b @ np.linalg.inv(B4fk)
                M4g = np.eye(4)
                M4g[:3, :3] = M
                M4g[:3, 3] = t
                _dp = np.linalg.norm(
                    Mk[:3, 3] - M4g[:3, 3] + (Mk[:3, :3] - M4g[:3, :3]) @ fb["tb"][k]
                )
                _dR = np.degrees(
                    np.arccos(np.clip((np.trace(Mk[:3, :3].T @ M4g[:3, :3]) - 1) / 2, -1, 1))
                )
                if _dp > 0.02 or _dR > 5.0:
                    # Misaligned 'match' = the mini-rig ROOT (NTO cowl Bip01:
                    # zeroed bind, Head's grandparent; its verts = the skirt
                    # base at chest height). User QA killed both extremes:
                    # Head-anchor ride pitches the skirt with the head
                    # (round 3), entity ride leaves it behind when the torso
                    # moves (round 4 giraffe). The verts sit at upper-chest
                    # height with clavicle weights already separate -> ride
                    # the UPPER TORSO: proxy to Spine2 with the global M4
                    # (S = P_spine2@M4: exact at rest, follows the chest).
                    for _cand in ("Spine2", "Spine1", "Spine"):
                        if _cand in bn:
                            break
                    _tor = bn.index(_cand) if _cand in bn else 0
                    proxy_slots.append(_tor)
                    proxy_align.append(M4g)
                    slotmap[k] = len(fbn) + len(proxy_slots) - 1
                    print(
                        "  name-proxy %s -> %s ride (bind off %.2fm/%.0fdeg)"
                        % (n, bn[_tor], _dp, _dR)
                    )
                    continue
                proxy_slots.append(bs)
                proxy_align.append(Mk)
                slotmap[k] = len(fbn) + len(proxy_slots) - 1
        if slotmap:
            parts = [
                _vgk.keep_attrs(
                    _pt,
                    (
                        _pt[0],
                        np.where(
                            np.isin(_pt[1], list(slotmap)),
                            np.vectorize(lambda x: slotmap.get(int(x), int(x)))(_pt[1]),
                            _pt[1],
                        ).astype(_pt[1].dtype),
                        _pt[2],
                        _pt[3],
                        _pt[4],
                        _pt[5],
                    ),
                )
                for _pt in parts
            ]
            print("  name-proxy ride: %s" % [bn[b] for b in proxy_slots])
    if align_ref is not None:
        # GROUND-TRUTH alignment: register the face twin onto the static head
        # it replaces (authored in body space) -- cutscene heads carry a
        # slightly different head-vs-bone orientation than the game heads, so
        # pure bone-frame alignment tilts the face (user Blender QA).
        ref_parts = char_lib.load_parts([align_ref], bn)
        A = max((pt[0] for pt in parts), key=len)  # twin's biggest submesh
        B = np.vstack([pt[0] for pt in ref_parts])
        M0 = M.copy()
        M, t, res = _icp_refine(np.asarray(A, float), np.asarray(B, float), M, t)
        dang = np.degrees(np.arccos(np.clip((np.trace(M0.T @ M) - 1) / 2, -1, 1)))
        print(
            "  face align %s: ICP residual %.4f, correction %.2f deg"
            % (os.path.basename(model_base), res, dang)
        )
        # WEIGHT TRANSFER: the static head is body-skinned with a soft blend
        # (e.g. 92%% Head + 8%% Spine2 at the neck base); a rigid ride on Head
        # over-rotates (user QA).  Copy each twin vertex's body blend from its
        # nearest static-head vertex; core (non-face-bone) weight goes to
        # per-body-slot PROXY joints, face-bone weight stays on the face rig.
        fpar = fb["par"]

        def _below(k):
            pnt = fpar[k]
            while pnt >= 0:
                if fbn[pnt] == "Head":
                    return True
                pnt = fpar[pnt]
            return False

        facemask = np.array([_below(k) for k in range(len(fbn))])
        refV = np.vstack([pt[0] for pt in ref_parts])
        refSI = np.vstack([pt[1] for pt in ref_parts])
        refSW = np.vstack([pt[2] for pt in ref_parts])
        newparts = []
        for _pt in parts:
            V, SI, SW, T, UV, nm = _pt
            V2 = np.asarray(V, float) @ M.T + t
            nn = np.empty(len(V2), int)
            CH = 512
            for i0 in range(0, len(V2), CH):
                d = ((V2[i0 : i0 + CH, None, :] - refV[None, :, :]) ** 2).sum(2)
                nn[i0 : i0 + CH] = d.argmin(1)
            nSI = np.zeros_like(SI)
            nSW = np.zeros_like(SW)
            for vi in range(len(V2)):
                comps = []
                wC = 0.0
                for c in range(SI.shape[1]):
                    w = float(SW[vi, c])
                    if w <= 0:
                        continue
                    if facemask[SI[vi, c]]:
                        comps.append((int(SI[vi, c]), w))
                    else:
                        wC += w
                if wC > 0:
                    bslots = {}
                    ri = nn[vi]
                    for c in range(refSI.shape[1]):
                        w = float(refSW[ri, c])
                        if w > 0:
                            bslots[int(refSI[ri, c])] = bslots.get(int(refSI[ri, c]), 0) + w
                    tot = sum(bslots.values()) or 1.0
                    for bs, w in bslots.items():
                        if bs not in proxy_slots:
                            proxy_slots.append(bs)
                        comps.append((len(fbn) + proxy_slots.index(bs), wC * w / tot))
                comps.sort(key=lambda x: -x[1])
                comps = comps[:4]
                tw = sum(w for _, w in comps) or 1.0
                for c, (jidx, w) in enumerate(comps):
                    nSI[vi, c] = jidx
                    nSW[vi, c] = w / tw
            newparts.append(_vgk.keep_attrs(_pt, (V, nSI, nSW.astype(np.float32), T, UV, nm)))
        parts = newparts
        print("  weight transfer: proxy body slots %s" % [bn[b] for b in proxy_slots])
    fam = face_export.head_family(head)
    clips = {
        k: v for k, v in face_export.face_clips(extract_out).items() if k.startswith(fam + "/")
    }
    bake_v4._load_bind(fbind)
    anims = []
    for nm in sorted(clips):
        try:
            # a head model's own node list: its roots keep their bind position
            pal, dur = bake_v4.bake(
                nm, 2, bank=clips, root_rest="bind", twist_align=False, track_names="prefix"
            )
            if len(pal) == 1:
                pal = np.repeat(pal, 2, axis=0)
            # static expression holds (nk 2): 1s hold beats header-exact 30s
            fps = 2.0 if len(pal) <= 3 else bake_v4.fps_for(len(pal), dur)
            anims.append(("FACE " + nm, pal, fps))
        except Exception as e:
            print("  face bake fail %s: %s" % (nm, e))
    # SYNTH (tier-3): blink + talk loops from shipped poses only, plus the
    # pose table for body-clip category pairing in write_glb.
    import face_synth as fs

    pose0 = {nm.split("/")[-1]: pal[0] for nm, pal, _f in anims}

    def _first(*names):
        for n in names:
            if n in pose0:
                return pose0[n]
        return None

    neutral = _first("MouthClosed_EyesOpen", "NiteOwl_MouthClosed")
    closed = _first("MouthClosed_EyesClosed")
    talk = _first("MouthTalk_EyesAnger", "NiteOwl_Talk")
    if neutral is not None and closed is not None:
        anims.append(("FACE SYNTH Blink", fs.blink_anim(neutral, closed), 15.0))
    if neutral is not None and talk is not None:
        anims.append(("FACE SYNTH Talk", fs.talk_anim(neutral, talk), 15.0))
    return dict(
        bind=fbind,
        parts=parts,
        anims=anims,
        attach_idx=bidx,
        M=M,
        t=t,
        proxy_slots=proxy_slots,
        proxy_align=(proxy_align if align_ref is None else None),
        auto_poses=pose0,
        blink_closed=closed,
        family=fam,
        head=head,
    )
