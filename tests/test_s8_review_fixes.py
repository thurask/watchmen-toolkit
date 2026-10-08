"""Clip timing, resumable exports, exit codes and smaller fixes.

    H1   every clip is written at its header-exact rate: no walk / run multiplier
    M1   `extract` and `all` return the extractor's exit code
    M2   a resumed `characters` / `faces` run rewrites a GLB written with other options
    N32  a GLB is written to <name>.tmp and renamed; the log names the final file
    M3   the baker reads clips from the bank it is given, never from /tmp pickles
    M4   a cached bake records the bind and the clip bytes it was baked from
    M5   the jiggle constants come from the extract's GameEssentials fragment; a fragment
         that cannot be read gives one WARNING line
    M6   a command given a folder that is not an extract output stops with an error
         (also `grademeta`, and also a folder that exists but has no extracted/)
    M7   `all` runs the character export
    M8   one sheet-record parser; texture headers found without regard to letter case
    L2   a sheet.json that cannot be written is reported
    L7   a bind that needs a missing archive names the argument
    L10  the X360 untiling is vectorised and gives the same bytes
    L11  a root bone takes the track the lookup found (track_names="prefix")
    -    Windows device names are not written as file names

Synthetic fixtures only."""

import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import bake_v4
import characters_export as ce
import jiggle_d6
import variant_glb as vg

from conftest import build_clip_header
from test_p6_anim import I4, _clip

ROOT = Path(__file__).resolve().parent.parent


def _bind(tmp_path, names=("Bip", "Hand"), par=(-1, 0)):
    p = tmp_path / "bind_t_file_v1.npz"
    n = len(names)
    np.savez(
        p,
        Rb=np.tile(np.eye(3), (n, 1, 1)),
        tb=np.zeros((n, 3)),
        tloc=np.zeros((n, 3)),
        par=np.array(par),
        names=np.array(list(names)),
    )
    return str(p)


# ------------------------------------------------------------------ H1 timing
def test_char_writes_walk_and_run_cycles_at_the_header_rate(tmp_path, monkeypatch):
    frag = tmp_path / "X.fragment.json"
    frag.write_text(
        '{"instances": [{"name": "V", "model_ref": ["/a/Skel_Skeleton.model", "/a/B.model"]}]}'
    )
    bind = _bind(tmp_path)
    bakedir = tmp_path / "bake"
    bakedir.mkdir()
    A = np.zeros((41, 2, 3, 4), np.float32)
    A[:, :, :, :3] = np.eye(3)
    bank = {}
    for nm, dur in (("EN4_EXP_MOV_walk_cycle", 3.4), ("EN4_COM_MOV_run_cycle", 1.2)):
        np.save(bakedir / (nm + ".npy"), A)
        bank[nm] = build_clip_header(41, dur)
    seen = {}
    monkeypatch.setattr(vg, "load_parts", lambda meshes, pal, naz=None: [])
    monkeypatch.setattr(
        vg, "write_glb", lambda parts, manifest, out, bindp, **k: seen.update(m=manifest)
    )
    vg.build(str(frag), "V", str(tmp_path / "o.glb"), bakedir=str(bakedir), bank=bank, bind=bind)
    fps = {nm: f for nm, _a, f in seen["m"]}
    assert fps["EN4_EXP_MOV_walk_cycle"] == pytest.approx(bake_v4.fps_for(41, 3.4))
    assert fps["EN4_COM_MOV_run_cycle"] == pytest.approx(bake_v4.fps_for(41, 1.2))
    assert not hasattr(vg, "speed_mult") and not hasattr(vg, "SPEED_MULT")


def test_characters_writes_every_cached_bake_at_its_stored_rate(tmp_path):
    for nm in ("RSH_COM_MOV_run_cycle", "RSH_EXP_MOV_walk_cycle", "RSH_COM_ATT_kick"):
        p = tmp_path / (nm + ".npz")
        np.savez(p, pal=np.zeros((21, 1, 3, 4), np.float32), dur=np.float32(1.3333), fps=15.0)
        with np.load(p) as d:
            assert ce.bake_fps(d) == pytest.approx(15.0)
    old = tmp_path / "old.npz"  # no stored rate: (frames - 1) / duration
    np.savez(old, pal=np.zeros((21, 1, 3, 4), np.float32), dur=np.float32(2.0))
    with np.load(old) as d:
        assert ce.bake_fps(d) == pytest.approx(10.0)
    src = inspect.getsource(ce.export)
    assert "fps = bake_fps(d)" in src and "speed_mult" not in src


def test_a_jiggle_memo_is_used_only_at_the_rate_it_was_solved_at(tmp_path):
    raw = tmp_path / "raw.npz"
    np.savez(raw, pal=np.zeros((2, 1, 3, 4), np.float32))
    t = os.path.getmtime(raw)

    def memo(name, **kw):
        p = tmp_path / name
        np.savez(p, pal=np.zeros((2, 1, 3, 4), np.float32), **kw)
        os.utime(p, (t + 5, t + 5))
        return str(p)

    assert ce.jiggle_memo_is_current(memo("a.npz", fps=np.float32(12.5)), str(raw), "X", 12.5)
    assert not ce.jiggle_memo_is_current(memo("b.npz", fps=np.float32(32.5)), str(raw), "X", 12.5)
    # a memo without a stored rate: the walk / run cycles were solved at 2.3 / 2.6 x
    legacy = memo("c.npz")
    assert ce.jiggle_memo_is_current(legacy, str(raw), "EN4_COM_ATT_kick", 12.5)
    assert not ce.jiggle_memo_is_current(legacy, str(raw), "EN4_COM_MOV_run_cycle", 12.5)
    assert not ce.jiggle_memo_is_current(legacy, str(raw), "EN4_EXP_MOV_walk_cycle", 12.5)
    assert not ce.jiggle_memo_is_current(str(tmp_path / "none.npz"), str(raw), "X", 12.5)


# ------------------------------------------------------------- M1 / M7 CLI
class _FakeWl:
    def __init__(self, rc):
        self.rc, self.calls = rc, []

    def extract_all(self, naz, out, *extra):
        self.calls.append(("extract", naz, out, extra))
        return self.rc

    def ensure_binds(self, naz, outdir, extract_dir=None):
        self.calls.append(("binds", naz, outdir, extract_dir))
        return {}


def test_extract_and_all_return_the_extractors_exit_code(monkeypatch, capsys):
    import watchmen

    fake = _FakeWl(2)
    monkeypatch.setattr(watchmen, "_wl", lambda: fake)
    assert watchmen.main(["w", "extract", "missing.naz", "OUT"]) == 2
    assert watchmen.main(["w", "all", "missing.naz", "OUT"]) == 2
    assert [c[0] for c in fake.calls] == ["extract", "extract"]  # no bind step after a failure
    assert "the extract step failed (exit code 2)" in capsys.readouterr().out


def test_extract_of_a_missing_archive_exits_with_2(tmp_path):
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "watchmen.py"),
            "extract",
            str(tmp_path / "no.naz"),
            str(tmp_path / "o"),
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    assert r.returncode == 2, r.stdout + r.stderr


def test_all_runs_the_character_export_with_its_options(monkeypatch, capsys):
    import watchmen

    fake = _FakeWl(0)
    calls = {}

    class FakeExport:
        @staticmethod
        def export(exout, outdir, naz, jiggle_model=None):
            calls["characters"] = (
                exout,
                outdir,
                naz,
                jiggle_model,
                os.environ.get("WATCHMEN_PARTS"),
            )
            return 0

    monkeypatch.setattr(watchmen, "_wl", lambda: fake)
    monkeypatch.setitem(sys.modules, "characters_export", FakeExport)
    monkeypatch.setattr(watchmen, "write_sound_meta", lambda ex, out: calls.update(sound=out))
    monkeypatch.setenv("WATCHMEN_PARTS", "")  # recorded, so the value `all` sets is undone
    monkeypatch.delenv("WATCHMEN_PARTS")
    argv = ["w", "all", "g.naz", "OUT", "--jiggle-model", "pinned", "--parts", "all"]
    assert watchmen.main(argv) == 0
    assert [c[0] for c in fake.calls] == ["extract", "binds"]
    assert fake.calls[0][3] == ()  # the character options are not handed to the extractor
    out = os.path.join("OUT", "characters")
    assert calls["characters"] == ("OUT", out, "g.naz", "pinned", "all")
    assert calls["sound"] == out
    assert "EVERYTHING" not in watchmen.__doc__


# ------------------------------------------------------------- M2 options
def test_characters_options_name_every_switch(monkeypatch):
    for k in ("WATCHMEN_FACE_RULE", "WATCHMEN_FACE_IDLE", "WATCHMEN_PARTS", "WATCHMEN_RAGDOLL"):
        monkeypatch.delenv(k, raising=False)
    meta = {"format": "watchmen-anim-meta/2", "revision": 7}
    base = ce.characters_options(meta=meta)
    assert base == ce.characters_options(meta=meta)
    assert json.loads(json.dumps(base)) == base  # survives the record file
    for kw in (
        dict(jiggle_model="pinned"),
        dict(face_rule="legacy"),
        dict(face_idle=False),
        dict(parts="all"),
        dict(ragdoll=False),
        dict(meta=dict(meta, revision=8)),
        dict(meta=None),
    ):
        assert ce.characters_options(**dict(dict(meta=meta), **kw)) != base, kw
    for env, value in (
        ("WATCHMEN_MATERIALS", "legacy"),
        ("WATCHMEN_NAMES", "stored"),
        (
            "WATCHMEN_FRAME",
            "mirrored" if os.environ.get("WATCHMEN_FRAME") != "mirrored" else "true",
        ),
        ("WATCHMEN_VERTEX_ATTRS", "0"),
        ("WATCHMEN_NO_SYNTH", "1"),
        ("WATCHMEN_CONSOLE", "x360"),
    ):
        monkeypatch.setenv(env, value)
        assert ce.characters_options(meta=meta) != base, env
        monkeypatch.undo()
        for k in ("WATCHMEN_FACE_RULE", "WATCHMEN_FACE_IDLE", "WATCHMEN_PARTS", "WATCHMEN_RAGDOLL"):
            monkeypatch.delenv(k, raising=False)


def test_a_glb_written_with_other_options_is_rewritten(tmp_path, capsys):
    out = tmp_path / "Char" / "V.glb"
    out.parent.mkdir()
    out.write_bytes(b"not a glb")  # no frame mark: the frame test lets it pass
    a, b = {"parts": "game", "glb_revision": 1}, {"parts": "all", "glb_revision": 1}
    assert ce.glb_is_current(str(out))  # no options named: not tested
    assert not ce.glb_is_current(str(out), None, a, str(tmp_path))  # no record
    assert "no record of its options" in capsys.readouterr().out
    ce.record_glb_options(str(out), str(tmp_path), a)
    rec = json.loads((tmp_path / ce.OPTIONS_FILE).read_text())
    assert rec["files"] == {"Char/V.glb": a} and rec["format"] == ce.OPTIONS_FORMAT
    assert ce.glb_is_current(str(out), None, a, str(tmp_path))
    assert not ce.glb_is_current(str(out), None, b, str(tmp_path))
    assert "written with other parts" in capsys.readouterr().out
    src = inspect.getsource(ce.export)
    assert "glb_is_current(out, baked, opts, outdir)" in src
    assert "record_glb_options(out, outdir, opts)" in src


def test_faces_keep_a_head_only_with_the_same_options_and_write_atomically(tmp_path, monkeypatch):
    import build_bind_file
    import char_lib
    import face_export

    ex, out = tmp_path / "ex", tmp_path / "faces"
    (ex / "extracted").mkdir(parents=True)
    written = []
    monkeypatch.setattr(face_export, "find_heads", lambda e: [str(tmp_path / "Head1")])
    monkeypatch.setattr(face_export, "face_clips", lambda e: {})
    monkeypatch.setattr(
        build_bind_file, "build", lambda m, t, p: np.savez(p, names=np.array(["Jaw"]))
    )
    monkeypatch.setattr(bake_v4, "_load_bind", lambda p=None: None)
    monkeypatch.setattr(char_lib, "load_parts", lambda models, bn: [])
    monkeypatch.setattr(char_lib, "find_textures", lambda parts, roots: {})

    def write_glb(parts, anims, path, bind, textures=None):
        written.append(path)
        Path(path).write_bytes(b"glb")

    monkeypatch.setattr(vg, "write_glb", write_glb)
    monkeypatch.delenv("WATCHMEN_MATERIALS", raising=False)
    assert face_export.export(str(ex), str(out)) == 0
    assert written == [str(out / "Head1.glb")] and (out / "Head1.glb").read_bytes() == b"glb"
    assert not (out / "Head1.glb.tmp").exists()
    assert face_export.export(str(ex), str(out)) == 0 and len(written) == 1  # kept
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    assert face_export.export(str(ex), str(out)) == 0 and len(written) == 2  # other options


def test_write_glb_renames_its_temp_file_and_logs_the_final_path(tmp_path, rig, capsys):
    out = tmp_path / "c.glb"
    vg.write_glb(rig.parts, rig.manifest, out, str(rig.bind_npz))
    log = capsys.readouterr().out
    assert out.read_bytes()[:4] == b"glTF" and not (tmp_path / "c.glb.tmp").exists()
    assert "wrote %s " % out in log and ".tmp" not in log


def test_an_interrupted_write_glb_leaves_no_glb(tmp_path, rig, monkeypatch):
    def killed(src, dst):
        raise KeyboardInterrupt

    monkeypatch.setattr(vg.os, "replace", killed)
    with pytest.raises(KeyboardInterrupt):
        vg.write_glb(rig.parts, rig.manifest, tmp_path / "c.glb", str(rig.bind_npz))
    assert not (tmp_path / "c.glb").exists()


def test_characters_and_faces_hand_write_glb_the_final_path():
    import face_export

    for mod in (ce, face_export):
        src = inspect.getsource(mod)
        assert 'out + ".tmp"' not in src and "os.replace(out" not in src


# ------------------------------------------------------------- M3 / M4 bakes
def test_the_baker_reads_only_the_bank_it_is_given(tmp_path):
    assert not hasattr(bake_v4, "_bank_lookup")
    src = inspect.getsource(bake_v4)
    assert "import pickle" not in src and "pickle.load" not in src and "clipbank" not in src
    bind = _bind(tmp_path)
    clip = _clip([("Bip", 3, ((0, 0.5, 0), I4)), ("Hand", 3, ((0, 0, 0), I4))])
    pal, _dur = bake_v4.bake("c", 1, bind=bind, bank={"c": clip})
    assert pal.shape[1] == 2
    with pytest.raises(FileNotFoundError):  # not in the bank: the archive, which is missing
        bake_v4.bake("other", 1, bind=bind, bank=None, naz=str(tmp_path / "no.naz"))
    for fn in (ce.bake_cache, ce._face_attach):
        assert "_bank_lookup" not in inspect.getsource(fn)


def test_a_cached_bake_records_its_bind_and_clip(tmp_path, monkeypatch):
    bind = _bind(tmp_path)
    ex, out = tmp_path / "ex", tmp_path / "out"
    d = ex / "extracted" / "Animation" / "T"
    d.mkdir(parents=True)
    clip = _clip([("Bip", 3, ((0, 0.5, 0), I4)), ("Hand", 3, ((0, 0, 0), I4))])
    (d / "T_a.animation").write_bytes(clip)
    monkeypatch.setitem(ce.CLIP_PREFIX, "t", ("T",))
    assert ce.bake_cache("t", bind, str(ex), str(out)) == (1, 0)
    npz = out / "_bake" / "t" / "T_a.npz"
    with np.load(npz) as z:
        assert str(z["bind_sha"]) == ce.bind_digest(bind)
        assert str(z["clip_sha"]) == ce.clip_digest(str(d / "T_a.animation"))
    clipf = str(d / "T_a.animation")
    assert ce.bake_is_current(str(npz), clipf, "exact", ce.bind_digest(bind))
    # the same arrays in another zip: the same bind
    other = tmp_path / "copy.npz"
    with np.load(bind) as z:
        np.savez_compressed(other, **{k: z[k] for k in z.files})
    assert ce.bind_digest(str(other)) == ce.bind_digest(bind)
    # another rest pose: not current
    moved = tmp_path / "moved.npz"
    with np.load(bind) as z:
        arrs = {k: z[k] for k in z.files}
    arrs["tloc"] = arrs["tloc"] + 0.01
    np.savez(moved, **arrs)
    assert not ce.bake_is_current(str(npz), clipf, "exact", ce.bind_digest(str(moved)))
    # other clip bytes under the same name: not current, and bake_cache bakes again
    (d / "T_a.animation").write_bytes(_clip([("Bip", 3, ((0, 0.7, 0), I4))]))
    assert not ce.bake_is_current(str(npz), clipf, "exact", ce.bind_digest(bind))
    before = np.load(npz)["pal"].copy()
    assert ce.bake_cache("t", bind, str(ex), str(out)) == (1, 0)
    assert not np.array_equal(np.load(npz)["pal"], before)
    # a bake without the identity keys is baked again when its clip is named
    legacy = tmp_path / "legacy.npz"
    with np.load(npz) as z:
        np.savez(legacy, **{k: z[k] for k in z.files if k not in ("bind_sha", "clip_sha")})
    assert ce.bake_is_current(str(legacy))
    assert not ce.bake_is_current(str(legacy), clipf)
    assert not ce.bake_is_current(str(legacy), None, None, ce.bind_digest(bind))


# ------------------------------------------------------------- M5 constants
def _game_essentials(monkeypatch, root, k_):
    import kapow_json

    f = root / "extracted" / "TNT" / "Production" / "Fragments" / "GameEssentials.fragment"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"")
    seen = []
    real = kapow_json.load_fragment

    def load(p, *a, **k):
        if "GameEssentials" not in str(p):
            return real(p, *a, **k)
        seen.append(p)
        return {
            "nodes_full": [
                {"props": [["name", 0, "PhysicsWorld"], ["m_nbreastspringconstant", 0, k_]]}
            ]
        }

    monkeypatch.setattr(kapow_json, "load_fragment", load)
    return seen


def test_jiggle_constants_come_from_the_extract_only(tmp_path, monkeypatch):
    seen = _game_essentials(monkeypatch, tmp_path, 300.0)
    assert jiggle_d6.load_world_props(None) == jiggle_d6._FILE_DEFAULTS
    assert seen == []  # no folder next to the toolkit is read
    W = jiggle_d6.load_world_props(str(tmp_path))
    assert W["breast"]["k"] == 300.0 and len(seen) == 1
    sig = jiggle_d6.cache_signature()
    assert jiggle_d6.cache_signature(props=dict(jiggle_d6._FILE_DEFAULTS)) == sig
    assert jiggle_d6.cache_signature(props=W) != sig
    assert ce.jiggle_cache_dir("c", None, W) != ce.jiggle_cache_dir("c", None)
    assert ce.characters_options(world=W) != ce.characters_options()
    src = inspect.getsource(ce.export)
    assert "load_world_props(extract_out)" in src and "props=world" in src


def test_a_game_essentials_fragment_that_cannot_be_read_is_reported(tmp_path, monkeypatch, capsys):
    import kapow_json

    f = tmp_path / "extracted" / "TNT" / "Production" / "Fragments" / "GameEssentials.fragment"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"not a fragment")

    def bad(p, *a, **k):
        raise ValueError("bad header")

    monkeypatch.setattr(kapow_json, "load_fragment", bad)
    assert jiggle_d6.load_world_props(str(tmp_path)) == jiggle_d6._FILE_DEFAULTS
    out = capsys.readouterr().out
    assert out.count("WARNING: GameEssentials.fragment not read (bad header)") == 1
    assert "shipped PhysicsWorld values used" in out


def test_char_jiggles_with_the_constants_of_its_extract(tmp_path, monkeypatch):
    _game_essentials(monkeypatch, tmp_path, 250.0)
    frag = tmp_path / "X.fragment.json"
    frag.write_text('{"instances": [{"name": "V", "model_ref": ["/a/S_Skeleton.model"]}]}')
    bakedir = tmp_path / "bake"
    bakedir.mkdir()
    np.save(bakedir / "EN4_a.npy", np.zeros((3, 2, 3, 4), np.float32))
    got = {}
    monkeypatch.setattr(vg, "load_parts", lambda meshes, pal, naz=None: [])
    monkeypatch.setattr(vg, "write_glb", lambda *a, **k: None)
    monkeypatch.setattr(jiggle_d6, "apply_jiggle", lambda A, fps, b, **k: got.update(k) or A)
    vg.build(
        str(frag),
        "V",
        str(tmp_path / "o.glb"),
        bakedir=str(bakedir),
        bind=_bind(tmp_path),
        jiggle=True,
        extract_root=str(tmp_path),
    )
    assert got["props"]["breast"]["k"] == 250.0
    import watchmen

    assert 'kw["extract_root"] = extract_out_of(frag)' in inspect.getsource(watchmen.main)


# ------------------------------------------------------------- M6 folders
@pytest.mark.parametrize(
    "cmd", ["fxmeta", "soundmeta", "animmeta", "grademeta", "faces", "characters"]
)
def test_a_folder_that_is_not_an_extract_is_an_error(cmd, tmp_path):
    missing = tmp_path / "typo"
    r = subprocess.run(
        [sys.executable, str(ROOT / "watchmen.py"), cmd, str(missing), str(tmp_path / "out.json")],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert not missing.exists()  # nothing is created in the mistyped folder
    assert not (tmp_path / "out.json").exists()


@pytest.mark.parametrize(
    "cmd", ["fxmeta", "soundmeta", "animmeta", "grademeta", "faces", "characters"]
)
def test_an_existing_folder_without_extracted_is_an_error(cmd, tmp_path):
    other = tmp_path / "characters_v1.4.0"  # e.g. the character export, not an extract
    other.mkdir()
    r = subprocess.run(
        [sys.executable, str(ROOT / "watchmen.py"), cmd, str(other), str(tmp_path / "out.json")],
        capture_output=True,
        text=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not an extract output" in r.stderr
    assert not (tmp_path / "out.json").exists()
    assert sorted(p.name for p in other.iterdir()) == []


def test_the_characters_usage_names_the_archive_default_and_the_jiggle_values():
    import watchmen

    u = watchmen.__doc__
    i = u.index("  characters EXTRACT_OUT")
    m = re.compile(r"\n  \S").search(u, i + 1)  # the next command
    block = u[i : m.start()]
    assert "NAZ default: 01_game.naz, else game.naz." in block
    assert "file constants only" not in block
    assert "values\n" in block and "of EXTRACT_OUT)" in block


def test_the_extract_test_accepts_an_extract_output(tmp_path):
    import extract_out

    assert not extract_out.is_extract_out(str(tmp_path))
    (tmp_path / "extracted").mkdir()
    assert extract_out.require(str(tmp_path)) == str(tmp_path)


# ------------------------------------------------------------- M8 sheets
def test_one_sheet_record_parser_reads_both_versions():
    import face_rule

    v2 = "2,0,1,2,art/a.texture,5,1,0,0,art/b.texture,6,"
    v1 = "1,0,1,art/a.texture,5,"
    assert face_rule.sheet_records(v2) == [
        {"slot": 0, "pivot": 1, "lod": 2, "path": "art/a.texture", "sheet_id": 5},
        {"slot": 1, "pivot": 0, "lod": 0, "path": "art/b.texture", "sheet_id": 6},
    ]
    assert face_rule.sheet_records(v1) == [
        {"slot": 0, "pivot": 1, "lod": 0, "path": "art/a.texture", "sheet_id": 5}
    ]
    assert [tuple(r.values()) for r in face_rule.sheet_records(v1)] == ce.sheet_records(v1)


def test_texture_headers_are_found_without_regard_to_letter_case(tmp_path, monkeypatch):
    import face_rule
    import watchmen_extract as we

    f = tmp_path / "extracted" / "Art" / "Chars" / "Tex.texture"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"hdr")
    sheet = {"name": "Blue", "unique_id": 5, "overrides": {"diffuse": "art/blue.texture"}}
    monkeypatch.setattr(face_rule, "texture_sheets", lambda h, order="<": [sheet] if h else [])
    rec = [{"slot": 0, "pivot": 0, "lod": 0, "path": "art/chars/tex.texture", "sheet_id": 5}]
    assert face_rule.sheet_overrides(str(tmp_path), rec) == {
        "art/chars/tex.texture": {"sheet": "Blue", "unique_id": 5, "overrides": sheet["overrides"]}
    }
    monkeypatch.setattr(we, "texture_sheets", lambda h, order="<": [sheet] if h == b"hdr" else [])
    ce._TEX_SHEETS.clear()
    assert ce._texture_sheets(str(tmp_path), "ART/CHARS/TEX.texture") == [sheet]
    assert ce._asset_file(str(tmp_path), ["Art", "Chars", "Tex.texture"]) == str(f)


# ------------------------------------------------------------- L2 / L7
def test_a_sheet_json_that_is_not_written_is_reported(tmp_path, monkeypatch, capsys):
    import watchmen_extract as we

    def boom(header, order="<"):
        raise ValueError("bad sheet")

    monkeypatch.setattr(we, "texture_sheet", boom)
    we._write_sheet_json(b"", tmp_path / "T")
    said = capsys.readouterr().out
    assert "WARNING: texture T: sheet.json not written (ValueError: bad sheet)" in said
    we._mark_texture_decode(tmp_path / "missing" / "T2", ["layer 1: no data"])
    assert "WARNING: texture T2: decode notes not recorded" in capsys.readouterr().out


def test_a_bind_that_needs_a_missing_archive_names_the_argument(tmp_path):
    (tmp_path / "extracted").mkdir()
    with pytest.raises(FileNotFoundError) as e:
        ce.ensure_bind("female", str(tmp_path), str(tmp_path / "game.naz"))
    assert "name the game archive as the third argument" in str(e.value)
    assert "does not exist" in str(e.value)


# ------------------------------------------------------------- L10 untiling
def _untile_reference(data, we_, he, bpe, alw=None, yoff=0):
    import watchmen_extract as we

    alw = max(alw or we_, 32)
    out = bytearray(we_ * he * bpe)
    for y in range(he):
        for x in range(we_):
            s = we._xg2d(x, y + yoff, alw, bpe) * bpe
            d = (y * we_ + x) * bpe
            if s + bpe <= len(data):
                out[d : d + bpe] = data[s : s + bpe]
    return bytes(out)


@pytest.mark.parametrize(
    "we_,he,bpe,alw,yoff,cut",
    [
        (32, 32, 4, None, 0, 0),
        (40, 8, 8, 40, 0, 0),
        (64, 16, 16, 64, 3, 0),
        (8, 64, 1, None, 0, 999),
    ],
)
def test_the_vectorised_untiling_gives_the_loops_bytes(we_, he, bpe, alw, yoff, cut):
    import watchmen_extract as we

    rng = np.random.default_rng(we_ * he + bpe)
    n = ((max(alw or we_, 32) + 31) & ~31) * (((he + yoff) + 31) & ~31) * bpe
    data = rng.integers(0, 256, n - cut, dtype=np.uint8).tobytes()
    got = we._xg_untile(data, we_, he, bpe, alw=alw, yoff=yoff)
    assert got == _untile_reference(data, we_, he, bpe, alw=alw, yoff=yoff)
    assert len(got) == we_ * he * bpe


# ------------------------------------------------------------- L11 roots
def test_a_root_takes_the_track_the_prefix_lookup_finds(tmp_path):
    bind = _bind(tmp_path, names=("Bip01 Pelvis", "Bip01 Spine"), par=(-1, 0))
    clip = _clip([("Pelvis", 2, [((0.0, 0.9, 0.1), I4)]), ("Spine", 3, ((0, 0, 0), I4))])
    pal, _ = bake_v4.bake("c", 1, bind=bind, bank={"c": clip}, track_names="prefix")
    assert pal[0, 0, :, 3] == pytest.approx([0.0, 0.9, 0.1], abs=1e-6)  # the track's position
    exact, _ = bake_v4.bake("c", 1, bind=bind, bank={"c": clip}, track_names="exact")
    assert exact[0, 0, :, 3] == pytest.approx([0.0, 0.0, 0.0])  # no track: at the origin


# ------------------------------------------------------------- device names
def test_windows_device_names_are_not_written(tmp_path, monkeypatch):
    import watchmen_extract as we

    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    assert we.safe(tmp_path, "a/CON.txt") == tmp_path / "a" / "_CON.txt"
    assert we.safe(tmp_path, "nul/lpt1") == tmp_path / "_nul" / "_lpt1"
    assert we.safe(tmp_path, "a/CONSOLE.txt") == tmp_path / "a" / "CONSOLE.txt"
