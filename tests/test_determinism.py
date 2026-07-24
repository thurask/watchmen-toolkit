"""Determinism of filesystem enumeration.

`os.walk` and `Path.glob` return entries in filesystem order, which varies with
creation order, inode allocation and the filesystem itself. Two of the pipeline
inputs are built by walking directories, so without an explicit sort the same
game files would produce a different texture->material assignment and a
different archive entry order on a different machine -- exactly the kind of
non-reproducibility that makes "it works here" bug reports unfalsifiable.
"""

import os
from pathlib import Path

import watchmen_extract as we

# Two directories whose *basenames collide* after the ".texture" suffix is
# stripped -- the case where enumeration order actually decides the winner.
TEX_TREE = [
    "chars/rorschach_skin.texture/0_diffuse_512x512_DXT1.png",
    "chars/rorschach_skin.texture/1_normal_512x512_DXT5.png",
    "props/rorschach_skin.texture/0_diffuse_256x256_DXT1.png",
    "chars/mask.texture/0_diffuse_128x128_DXT1.png",
    "props/mask.texture/0_diffuse_64x64_DXT1.png",
    "zzz/mask.texture/0_diffuse_32x32_DXT1.png",
    "aaa/coat.texture/0_diffuse_256x256_DXT1.png",
    "chars/nested/deep/boot.texture/0_diffuse_64x64_DXT1.png",
]


def _build_tex_tree(root, order):
    root = Path(root)
    for rel in order:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x89PNG\r\n\x1a\n")  # content is never read by the index
    return root


def _relative(index, root):
    return {k: Path(v).relative_to(root).as_posix() for k, v in index.items()}


def test_texture_index_is_stable_across_calls(tmp_path):
    """Repeated calls on the same tree must return the identical mapping.

    build_texture_index feeds material -> texture assignment for every exported
    model; an unstable result means re-running the exporter silently repaints
    characters with different textures.
    """
    root = _build_tex_tree(tmp_path / "tex", TEX_TREE)
    first = we.build_texture_index(root)
    for _ in range(4):
        assert we.build_texture_index(root) == first
    assert first, "the index should not be empty"


def test_texture_index_ignores_creation_order(tmp_path):
    """Colliding basenames must resolve the same way whatever order they were written in.

    Three directories all named 'mask.texture' collapse to the key 'mask'.
    Whichever one wins has to be decided by the sorted path, not by whichever
    the filesystem happens to hand back first.
    """
    forward = _build_tex_tree(tmp_path / "a", TEX_TREE)
    shuffled = _build_tex_tree(tmp_path / "b", list(reversed(TEX_TREE)))
    interleaved = _build_tex_tree(tmp_path / "c", TEX_TREE[3:] + TEX_TREE[:3])

    ia = _relative(we.build_texture_index(forward), forward)
    ib = _relative(we.build_texture_index(shuffled), shuffled)
    ic = _relative(we.build_texture_index(interleaved), interleaved)

    assert ia == ib == ic
    # and the winner really is the first in sorted order, not an arbitrary one
    assert ia["mask"] == "chars/mask.texture"
    assert ia["rorschach_skin"] == "chars/rorschach_skin.texture"


def test_texture_index_keys_are_lowercased_stems(tmp_path):
    """Keys are the directory basename minus its extension, lowercased.

    Material names in the model files are not case-consistent, so the lookup
    key has to be normalised or half the textures silently go missing.
    """
    root = _build_tex_tree(
        tmp_path / "tex", ["Chars/MiXeD_Case.Texture/0_diffuse_8x8_DXT1.png"] + TEX_TREE
    )
    idx = we.build_texture_index(root)
    assert "mixed_case" in idx
    assert set(idx) == {
        "mixed_case",
        "rorschach_skin",
        "mask",
        "coat",
        "boot",
    }
    assert all(k == k.lower() for k in idx)


def test_texture_index_survives_a_missing_root(tmp_path):
    """A non-existent texture root yields an empty index, not an exception.

    Texture extraction is optional; a model-only run must not abort because the
    texture pass was skipped.
    """
    assert we.build_texture_index(tmp_path / "does_not_exist") == {}


# ---------------------------------------------------------------------------
# loose_entries
# ---------------------------------------------------------------------------

LOOSE_TREE = [
    "derived_pc/zeta.block_h_z",
    "derived_pc/zeta.block_s_z",
    "derived_pc/alpha.block_h_z",
    "derived_pc/alpha.block_s_z",
    "derived_pc/sub/beta.texture_h_z",
    "derived_pc/sub/beta.texture_s_z",
    "derived_pc/aaa/gamma.modelres_h_z",
    "derived_pc/music.mediastream_s",
    "derived_pc/readme.txt",  # not a loose asset -> must be skipped
    "derived_pc/sub/notes.md",  # ditto
]


def _build_loose(root, order):
    root = Path(root)
    for i, rel in enumerate(order):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00" * (16 + i))
    return root


def test_loose_entries_order_is_sorted_and_reproducible(tmp_path):
    """Entry order is a deterministic sorted walk, identical across calls and trees.

    grab_blocks pairs '<stem>_h_z' with '<stem>_s_z' by walking this stream;
    a filesystem-dependent order means a different pairing -- and therefore a
    different set of extracted models -- on a different machine. The order is a
    top-down DFS with BOTH the file list and the directory list sorted at every
    level, which is what makes it reproducible.
    """
    a = _build_loose(tmp_path / "a", LOOSE_TREE)
    b = _build_loose(tmp_path / "b", list(reversed(LOOSE_TREE)))
    c = _build_loose(tmp_path / "c", LOOSE_TREE[4:] + LOOSE_TREE[:4])

    names_a = [e.name for e in we.loose_entries(a)]
    names_b = [e.name for e in we.loose_entries(b)]
    names_c = [e.name for e in we.loose_entries(c)]

    assert names_a == names_b == names_c, "order depends on filesystem creation order"
    for _ in range(3):
        assert [e.name for e in we.loose_entries(a)] == names_a

    # within any one directory the names are sorted, and directories are
    # visited in sorted order
    by_dir = {}
    for i, nm in enumerate(names_a):
        by_dir.setdefault(nm.rsplit("/", 1)[0], []).append((i, nm.rsplit("/", 1)[1]))
    for _d, items in by_dir.items():
        assert [nm for _i, nm in items] == sorted(nm for _i, nm in items)
        assert [i for i, _nm in items] == list(range(items[0][0], items[0][0] + len(items)))
    assert list(by_dir) == sorted(by_dir, key=lambda d: (d.count("/"), d))


def test_loose_entries_selects_only_asset_containers(tmp_path):
    """Only LOOSE_SUFFIXES files are yielded, named .naz-style with a leading '/'.

    Entry names must mirror the .naz naming so downstream decoders and the
    stem-pairing logic work unchanged on loose Part 1 trees.
    """
    root = _build_loose(tmp_path / "p1", LOOSE_TREE)
    entries = list(we.loose_entries(root))

    assert [e.name for e in entries] == [
        "/derived_pc/alpha.block_h_z",
        "/derived_pc/alpha.block_s_z",
        "/derived_pc/music.mediastream_s",
        "/derived_pc/zeta.block_h_z",
        "/derived_pc/zeta.block_s_z",
        "/derived_pc/aaa/gamma.modelres_h_z",
        "/derived_pc/sub/beta.texture_h_z",
        "/derived_pc/sub/beta.texture_s_z",
    ]
    for e in entries:
        assert e.name.startswith("/") and "\\" not in e.name
        assert e.compr == 0, "loose bytes are returned verbatim"
        assert e.psize == e.usize == os.path.getsize(e.path)
        assert Path(e.path).is_file()


def test_loose_entries_round_trips_through_naz_read(tmp_path):
    """naz_read() on a loose entry returns that file's bytes verbatim.

    Loose containers are byte-for-byte what a .naz would store internally, so
    the two code paths must be interchangeable for every downstream decoder.
    """
    root = _build_loose(tmp_path / "p1", LOOSE_TREE)
    payload = b"KAPOW" * 7
    (root / "derived_pc" / "alpha.block_h_z").write_bytes(payload)
    entry = next(e for e in we.loose_entries(root) if e.name.endswith("alpha.block_h_z"))
    assert we.naz_read(root, entry) == payload


def test_naz_entries_delegates_directories_to_loose_entries(tmp_path):
    """naz_entries(dir) must behave exactly like loose_entries(dir).

    This is how a loose Part 1 tree is passed to tools that expect an archive
    path; if the two diverged, half the pipeline would see a different file set
    than the other half.
    """
    root = _build_loose(tmp_path / "p1", LOOSE_TREE)
    assert [e.name for e in we.naz_entries(root)] == [e.name for e in we.loose_entries(root)]
    assert [e.name for e in we.naz_entries(str(root))] == [e.name for e in we.loose_entries(root)]
