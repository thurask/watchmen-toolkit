#!/usr/bin/env python3
"""characters_export.py -- one folder per character, one GLB per fragment
variant, each GLB carrying EVERY animation of that variant's skeleton.

Characters come straight from the game's fragment definitions
(TNT/Production/Fragments/Enemy/*.fragment + the player refs in the level
fragments).  Bakes are cached per skeleton in <outdir>/_bake/<key>/ so the
export is resumable and variants of the same skeleton share the work.
"""

import os, sys, json, glob
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

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


def _is_part1(extract_out):
    return os.path.exists(
        os.path.join(
            extract_out,
            "extracted",
            "TNT",
            "Production",
            "Fragments",
            "Enemy",
            "Biker.fragment.json",
        )
    )


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

TEX_OVERRIDES = {
    ("Dominatrices", "Dominatrix_5"): {"FemaleSkinBody_White": "FemaleSkinBody_Black"},
    ("Dominatrices", "Dominatrix_7"): {"FemaleSkinBody_White": "FemaleSkinBody_Black"},
    ("Dominatrices", "Dominatrix_10"): {"FemaleSkinBody_White": "FemaleSkinBody_Black"},
    # Dominatrix_3 reconstruction: dark dominatrix body skin (pre-release).
    ("Dominatrices", "Dominatrix_3"): {"FemaleSkinBody_White": "FemaleSkinBody_Dominatrix1"},
}

# --- Synthetic (reconstructed) variants (2026-07-16) ---------------------------
# The Dominatrices fragment ships variants 1,2,4..10 -- there is NO Dominatrix_3
# in the shipped data. Pre-release screenshots show a _3 identical to Dominatrix_2
# but with Twilight Lady's hair (the TwilightLadyHair submesh of BS2_WithoutWeapon,
# no standalone hair model exists) tinted the FimaleGimpMask brown, and the dark
# FemaleSkinBody_Dominatrix1 body skin (via TEX_OVERRIDES above). discover() clones
# the base variant (minus its own hair mesh); export() grafts the hair submesh +
# fabricated brown texture. Disable with WATCHMEN_NO_SYNTH=1.
SYNTH_VARIANTS = {
    ("Dominatrices", "Dominatrix_3"): dict(
        base="Dominatrix_2",
        drop_mesh="GoGoWhite_HairLayered2",
        hair_from=("BS2_WithoutWeapon", "TwilightLadyHair"),
        hair_tint_from="FimaleGimpMask1",
        hair_mat="TwilightLadyHair_Brown",
    ),
}


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
    idx = {}
    for p in glob.glob(os.path.join(extract_out, "extracted", "**", "*.model"), recursive=True):
        idx.setdefault(os.path.basename(p)[:-6], p[:-6])
    return idx


def discover(extract_out):
    """-> {charName: {variantName: (bindKey, [model base paths])}}"""
    midx = _model_index(extract_out)
    chars = {}
    fragroot = os.path.join(extract_out, "extracted", "TNT", "Production", "Fragments")
    stems = list(ENEMY_FRAGS)
    if _is_part1(extract_out):
        stems += ENEMY_FRAGS_P1
    for stem in stems:
        hits = glob.glob(os.path.join(fragroot, "**", stem + ".fragment.json"), recursive=True)
        if not hits:
            print("  ! fragment %s not found" % stem)
            continue
        d = json.load(open(hits[0]))
        vs = {}
        for i in d.get("instances", []):
            refs = i.get("model_ref")
            if not refs:
                continue
            name = i.get("name") or stem
            if name == "(preamble)":
                name = stem
            basenames = [r.rsplit("/", 1)[-1].replace(".model", "") for r in refs]
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
            models = [midx[b] for b in meshes if b in midx]
            missing = [b for b in meshes if b not in midx]
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
    return wl.ensure_binds(naz, bdir, extract_dir=extract_out)[key]


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


def bake_cache(key, bind, extract_out, outdir, budget=None):
    """Bake every <prefix>_* clip for this skeleton into <outdir>/_bake/<key>/.
    Resumable (skips existing .npy).  Returns (done, remaining).
    ADAPTIVE RATE: bake at 2x, keep 1x when LERP mid-frame error <= LERP_ERR_DEG,
    escalate to 4x (keeping 2x/4x) for fast clips -- fixes hand/finger shear."""
    import importlib, bake_v4

    sys.argv = ["bake", "--bind", bind, "--conj"]
    importlib.reload(bake_v4)
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
            if os.sep + "FACE" in dp or dp.endswith("FACE"):
                continue
            for f in fn:
                if f.endswith(".animation"):
                    clips[f[:-10].strip()] = os.path.join(dp, f)
    bake_v4._bank_lookup = lambda nm: open(clips[nm], "rb").read() if nm in clips else None
    cdir = os.path.join(outdir, "_bake", key)
    os.makedirs(cdir, exist_ok=True)
    import time

    t0 = time.time()
    done = 0
    todo = 0
    for nm in sorted(clips):
        dst = os.path.join(cdir, nm + ".npz")
        if os.path.exists(dst):
            done += 1
            continue
        if budget and time.time() - t0 > budget:
            todo += 1
            continue
        try:
            pal2, dur = bake_v4.bake(nm, 2)
            if _lerp_err(pal2, _B4) <= LERP_ERR_DEG:
                pal = pal2[::2]  # 1x is safe
            else:
                pal4, _ = bake_v4.bake(nm, 4)
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


def export(extract_out, outdir, naz="game.naz", budget=None, only=None):
    """Write <outdir>/<Char>/<Variant>.glb.  Resumable: existing glbs skipped,
    bakes cached.  budget: seconds of baking per skeleton per call."""
    import char_lib, variant_glb as vg

    chars = discover(extract_out)
    texroots = [os.path.join(extract_out, "textures")]
    if _is_part1(extract_out) and "part1" not in str(naz).replace("\\", "/").lower():
        print(
            "  WARNING: extract looks like Part 1 but naz=%r (Part 2?). Part 1 rest "
            "poses DIFFER -- delete <extract_out>/binds and pass the Part 1 source "
            "(e.g. part1_pc/Watchmen/derived_pc) as the 3rd argument." % str(naz)
        )
    pending = 0
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
            anims = None  # lazy-load once per key
            for vname, (k2, models) in sorted(vs.items()):
                if k2 != key:
                    continue
                out = os.path.join(outdir, cname, vname + ".glb")
                if os.path.exists(out):
                    continue
                os.makedirs(os.path.dirname(out), exist_ok=True)
                if anims is None:
                    # 2026-07-13 perf: npz members are lazy — when a jiggle
                    # memo exists, read pal from the memo ONLY (raw npz is
                    # opened just for dur/fps), halving mount I/O per skeleton.
                    anims = []
                    from jiggle_d6 import apply_jiggle

                    jdir = cdir + "_j"  # jiggle disk memo (chunked runs)
                    os.makedirs(jdir, exist_ok=True)
                    jn = 0
                    jig_todo = []  # anim indices needing a jiggle attempt
                    # (was named `pending`, which shadowed the outer resumable-
                    #  bake counter and made export() return a list)
                    for f in sorted(glob.glob(os.path.join(cdir, "*.npz"))):
                        nm = os.path.basename(f)[:-4]
                        d = np.load(f)
                        if "fps" in d:
                            fps = float(d["fps"])  # header-exact
                        else:
                            dur = float(d["dur"])
                            fps = len(d["pal"]) / (dur / 3.0) if dur > 0 else 30
                        jf = os.path.join(jdir, nm + ".npz")
                        if os.path.exists(jf):
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
                            jp = apply_jiggle(pal, fps, bind)
                        except Exception:
                            if jn == 0:
                                break  # skeleton without jiggle bones
                            continue
                        jf = os.path.join(jdir, nm + ".npz")
                        np.savez(jf + ".tmp.npz", pal=jp.astype(np.float32))
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
                parts = char_lib.load_parts(usemodels, bn)
                # synthetic variant: graft a hair submesh from another model,
                # retextured (Dominatrix_3 = Twilight Lady hair, brown-tinted).
                sv = SYNTH_VARIANTS.get((cname, vname))
                if sv and sv.get("hair_from") and not os.environ.get("WATCHMEN_NO_SYNTH"):
                    hmodel, hmat = sv["hair_from"]
                    if hmodel in midx:
                        # (collapsed-UV tangent sanitation now happens for every
                        # normal-mapped part in variant_glb.write_glb.)
                        hp = [
                            (v, si, sw, t, uv, sv["hair_mat"])
                            for (v, si, sw, t, uv, mat) in char_lib.load_parts([midx[hmodel]], bn)
                            if mat == hmat
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
                    tex.update(char_lib.find_textures(face["parts"], texroots))
                atts = char_attachments(cname, bind, bn, extract_out)
                for _, apts in atts:
                    tex.update(char_lib.find_textures(apts, texroots))
                grips = grip_anims(anims, bn, bv["par"])
                # atomic write: chunked runs get SIGTERM'd mid-call; a
                # partial glb must not survive (export skips existing files).
                vg.write_glb(
                    parts,
                    anims + grips,
                    out + ".tmp",
                    bind,
                    textures=tex,
                    face=face,
                    attachments=atts,
                )
                os.replace(out + ".tmp", out)
    return pending


def weapon_sets(extract_out):
    """WeaponDB.fragment -> {collection name: [model base paths]} (file-only)."""
    hits = glob.glob(
        os.path.join(
            extract_out,
            "extracted",
            "TNT",
            "Production",
            "Fragments",
            "**",
            "WeaponDB.fragment.json",
        ),
        recursive=True,
    )
    if not hits:
        return {}
    d = json.load(open(hits[0]))
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
                cand = glob.glob(os.path.join(ex, "**", os.path.basename(m)), recursive=True)
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

    bv = np.load(bind, allow_pickle=True)
    Rb, tbb = bv["Rb"][slot], bv["tb"][slot]
    M, t = Rb, tbb
    if offset is not None:
        p, q = offset
        Ro = _q2m_conj(q)
        M = Rb @ Ro
        t = Rb @ np.asarray(p, float) + tbb
    mh = open(model_base + ".model", "rb").read()
    ms = open(model_base + ".model.stream", "rb").read()
    order = ">" if len(we.find_descriptors(mh, ">")) > len(we.find_descriptors(mh, "<")) else "<"
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
            continue
        V = (np.array(v, float) @ M.T) + t
        SI = np.full((len(V), 4), slot, np.uint16)
        SW = np.zeros((len(V), 4), np.float32)
        SW[:, 0] = 1
        parts.append(
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
            )
        )
    return parts


def _tw_weapon_spec(extract_out, bn):
    """TwilightLady's data-driven weapon: (model base, slot, (pos, quat)) from
    Bs2CharVisual.fragment (HandAttach node: attachedBone + child model node
    local offset), or None."""
    hits = glob.glob(
        os.path.join(
            extract_out,
            "extracted",
            "TNT",
            "Production",
            "Fragments",
            "**",
            "Bs2CharVisual.fragment.json",
        ),
        recursive=True,
    )
    if not hits:
        return None
    d = json.load(open(hits[0]))
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
            base = os.path.join(extract_out, "extracted", *m.split("/"))[:-6]
            if not os.path.exists(base + ".model"):
                return None
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
    colls = CHAR_WEAPON_COLLS.get(cname)
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
                bases.append(gg[0][:-6])
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

    mh = open(model_base + ".model", "rb").read()
    ms = open(model_base + ".model.stream", "rb").read()
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
    # byte order: console (X360/PS3) model headers/streams are big-endian.
    # Compare descriptor counts (a BE model can throw a stray LE false positive).
    order = ">" if len(we.find_descriptors(mh, ">")) > len(we.find_descriptors(mh, "<")) else "<"
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
            continue
        V = (np.array(v, float) @ M.T) + t
        SI = np.full((len(V), 4), bidx, np.uint16)
        SW = np.zeros((len(V), 4), np.float32)
        SW[:, 0] = 1
        parts.append(
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


def _face_attach(model_base, bone, bind, bn, cname, extract_out, outdir, align_ref=None):
    """Animated face attach: face bind from the head model's own nodes, its
    family's expression poses baked on, alignment M,t mapping face-model space
    -> body bind space (same node-FK alignment as the old rigid attach)."""
    import importlib, bake_v4, char_lib, parse_model_nodes, build_bind_file as bbf
    import face_export

    # face bind
    fdir = os.path.join(extract_out, "binds", "face")
    os.makedirs(fdir, exist_ok=True)
    head = os.path.basename(model_base)
    fbind = os.path.join(fdir, "bind_face_%s.npz" % head)
    if not os.path.exists(fbind):
        bbf.build(model_base + ".model", None, fbind)
    # alignment from both models' conj-gauge FK
    names, pos, quat, parent = parse_model_nodes.parse(open(model_base + ".model", "rb").read())
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
    parts = char_lib.load_parts([model_base], fbn)
    proxy_slots = []
    if align_ref is None:
        # 2026-07-13: NAME-PROXY RIDE (designed in work_D/NTO_FACE_FINDINGS.md,
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
                (
                    V,
                    np.where(
                        np.isin(SI, list(slotmap)),
                        np.vectorize(lambda x: slotmap.get(int(x), int(x)))(SI),
                        SI,
                    ).astype(SI.dtype),
                    SW,
                    T,
                    UV,
                    nm,
                )
                for (V, SI, SW, T, UV, nm) in parts
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
        M0, t0 = M.copy(), t.copy()
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
        for V, SI, SW, T, UV, nm in parts:
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
            newparts.append((V, nSI, nSW.astype(np.float32), T, UV, nm))
        parts = newparts
        print("  weight transfer: proxy body slots %s" % [bn[b] for b in proxy_slots])
    fam = face_export.head_family(head)
    clips = {
        k: v for k, v in face_export.face_clips(extract_out).items() if k.startswith(fam + "/")
    }
    sys.argv = ["bake", "--bind", fbind, "--conj"]
    importlib.reload(bake_v4)
    bake_v4._bank_lookup = lambda nm: open(clips[nm], "rb").read() if nm in clips else None
    anims = []
    for nm in sorted(clips):
        try:
            pal, dur = bake_v4.bake(nm, 2)
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
    )
