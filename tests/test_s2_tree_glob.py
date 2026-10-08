"""`kapow_json.glob_tree`: the recursive searches of a metadata build walk the
extract once.

`anim_meta.build` / `sound_meta.build` look for a handful of fragment families with
patterns like `extracted/**/CharacterAnimation/AnimationClass*.fragment`.  A recursive
glob walks the whole tree for each pattern and asks the file system once per directory
for the literal name; inside `tree_cache` the directory list is made once.  The paths
returned must be exactly glob's.

Synthetic trees only: no game files.
"""

import glob
import os

import pytest

import kapow_json as kj


def _touch(root, *rel):
    for r in rel:
        p = os.path.join(root, *r.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b"x")


@pytest.fixture
def tree(tmp_path):
    root = str(tmp_path / "out" / "extracted")
    _touch(
        root,
        "TNT/Production/CharacterAnimation/AnimationClassEnemy.fragment",
        "TNT/Production/CharacterAnimation/AnimationClassEnemy.fragment.json",
        "TNT/Production/CharacterAnimation/AnimationClassFemaleFace.fragment",
        "TNT/Production/CharacterAnimation/Other.fragment",
        "TNT/Production/CharacterAnimation/.AnimationClassHidden.fragment",
        "TNT/Other/CharacterAnimation/AnimationClassLarge.fragment.json",
        "TNT/Other/CharacterAnimation/sub/AnimationClassDeep.fragment",
        "TNT/.hidden/CharacterAnimation/AnimationClassNo.fragment",
        "CharacterAnimation/AnimationClassTop.fragment",
        "TNT/Production/Fragments/Enemy/Gimp.fragment",
        "TNT/Production/Fragments/Enemy/Thug[1].fragment",
        "TNT/Production/Fragments/NotEnemy/Gimp.fragment",
        "TNT/Fragments/Enemy/Goon.fragment",
        "A [x]/CharacterVisual/GimpCharVisual.fragment",
        "A [x]/CharacterVisual/GimpCharVisual_2.fragment",
        "Levels/L1/CharacterVisual",  # a FILE with the directory's name
    )
    os.makedirs(os.path.join(root, "TNT", "Empty", "CharacterAnimation"))
    return root


SEARCHES = [
    ("CharacterAnimation", "AnimationClass*.fragment"),
    ("CharacterAnimation", "AnimationClass*.fragment.json"),
    ("CharacterVisual", "*CharVisual*.fragment"),
    ("Fragments", "Enemy", "*.fragment"),
    ("Fragments", "Enemy", "*.fragment.json"),
    ("Nowhere", "*.fragment"),
    ("*.fragment",),
]


def _plain(root, parts):
    return sorted(glob.glob(os.path.join(root, "**", *parts), recursive=True))


def test_outside_a_cache_it_is_glob(tree):
    for parts in SEARCHES:
        assert sorted(kj.glob_tree(tree, *parts)) == _plain(tree, parts)
    assert kj._TREE_DIRS == {}


def test_inside_a_cache_the_paths_are_the_same(tree):
    want = {parts: _plain(tree, parts) for parts in SEARCHES}
    assert len(want[SEARCHES[0]]) == 3 and len(want[SEARCHES[3]]) == 3
    assert len(want[SEARCHES[2]]) == 2 and want[SEARCHES[5]] == []
    with kj.tree_cache(tree):
        for parts in SEARCHES:
            assert sorted(kj.glob_tree(tree, *parts)) == want[parts], parts
    assert kj._TREE_DIRS == {}


def test_the_tree_is_walked_once(tree, monkeypatch):
    real, walks = glob.glob, []

    def counting(pattern, *a, **k):
        if k.get("recursive"):
            walks.append(pattern)
        return real(pattern, *a, **k)

    monkeypatch.setattr(glob, "glob", counting)
    with kj.tree_cache(tree):
        for _ in range(3):
            for parts in SEARCHES:
                kj.glob_tree(tree, *parts)
    assert len(walks) == 1
    del walks[:]
    for parts in SEARCHES:
        kj.glob_tree(tree, *parts)
    assert len(walks) == len(SEARCHES)


def test_cache_lasts_as_long_as_it_is_open_and_nests(tree):
    parts = ("CharacterAnimation", "AnimationClass*.fragment")
    with kj.tree_cache(tree):
        before = sorted(kj.glob_tree(tree, *parts))
        with kj.tree_cache(tree):
            _touch(tree, "New/CharacterAnimation/AnimationClassNew.fragment")
            assert sorted(kj.glob_tree(tree, *parts)) == before  # the list is the open one
        assert sorted(kj.glob_tree(tree, *parts)) == before  # still open
    after = sorted(kj.glob_tree(tree, *parts))
    assert len(after) == len(before) + 1 and after == _plain(tree, parts)
    with kj.tree_cache(tree):  # a new cache sees the new directory
        assert sorted(kj.glob_tree(tree, *parts)) == after
    # another root is not served from this one
    with kj.tree_cache(tree):
        other = os.path.dirname(tree)
        assert sorted(kj.glob_tree(other, "CharacterVisual", "*.fragment")) == _plain(
            other, ("CharacterVisual", "*.fragment")
        )


def test_cache_is_released_when_the_build_raises(tree):
    with pytest.raises(RuntimeError):
        with kj.tree_cache(tree):
            kj.glob_tree(tree, "CharacterVisual", "*")
            raise RuntimeError("build failed")
    assert kj._TREE_DIRS == {}


def test_the_finders_use_it_and_find_the_same(tree):
    import anim_meta
    import face_rule

    out = os.path.dirname(tree)
    plain = (anim_meta.find_class_fragments(out), face_rule.find_face_fragments(out))
    assert sorted(plain[0]) == ["Enemy", "Large", "Top"] and sorted(plain[1]) == ["FemaleFace"]
    with kj.tree_cache(tree):
        assert (anim_meta.find_class_fragments(out), face_rule.find_face_fragments(out)) == plain


def test_a_directory_spelled_in_another_case_follows_the_file_system(tree):
    """glob looks a literal name up with lexists, so whether `characteranimation` is
    found for `CharacterAnimation` is the file system's decision; the cache asks it
    the same way."""
    _touch(tree, "Case/characteranimation/AnimationClassCase.fragment")
    parts = ("CharacterAnimation", "AnimationClass*.fragment")
    want = _plain(tree, parts)
    with kj.tree_cache(tree):
        assert sorted(kj.glob_tree(tree, *parts)) == want


def test_a_root_with_glob_magic_behaves_as_glob_does(tmp_path):
    """glob reads `[1]` in the root as a character class; the cache does not change
    what a search under such a root returns."""
    root = str(tmp_path / "out [1]" / "extracted")
    _touch(root, "TNT/CharacterAnimation/AnimationClassEnemy.fragment")
    parts = ("CharacterAnimation", "AnimationClass*.fragment")
    want = _plain(root, parts)
    with kj.tree_cache(root):
        assert sorted(kj.glob_tree(root, *parts)) == want
