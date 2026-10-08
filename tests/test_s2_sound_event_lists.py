"""Sound-event lists in sound_meta: every list a state includes is read, whatever the
letter case of its file name, and a list the data does not contain is named.

* The game data spells one list `se_finished_by_NO_victim02.fragment` (all others are
  `SE_...`).  Its events are in the table like any other list's, and `source` is the
  file name as stored: a count of `source` values that start with `SE_` misses them
  (9 events on Part 2, 3 on Part 1), a count without regard to case does not.
* A state can name a list that is not in the data (1 instance on Part 2, 5 on Part 1).
  The game then has nothing to include; `classes.<Class>.missing_event_lists` names it,
  as anim_meta does.

Synthetic data only: no game files.
"""

import json

import sound_meta
import test_anim_meta as ta

DIR = "TNT/CharacterAnimation/SoundEvents/"


def _list(tmp_path, name, events):
    e = ta.Frag()
    for eid, pos in events:
        e.add(
            "AnimationEventWM",
            "",
            m_nplaypos=pos,
            m_ieventtype=0,
            m_ianimationevent=eid,
            m_nvalue=0.0,
        )
    f = tmp_path / "extracted" / (DIR + name + ".json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"instances": [e.cls], "nodes_full": e.nodes}))


def _extract(tmp_path, gone=()):
    h = ta.Frag()
    g = h.add("AnimationStateGroupWM", "Finishers")
    h.state(
        "Finished_by_NiteOwl_B",
        g,
        "EN1_COM_DMG_finish",
        events=[("IMPACT", 0.5)],  # gives the state its `Events` folder; not a sound event
        m_tislooping=False,
    )
    ev = next(n["id"] for n in h.nodes if ["name", "string", "Events"] in n["props"])
    # the class spells the asset as the file is stored
    h.add("FragmentNode", "", ev, assetName="/" + DIR + "se_finished_by_NO_victim02.fragment")
    h.add("FragmentNode", "", ev, assetName="/" + DIR + "SE_EN1_COM_DMG_finish.fragment")
    for name in gone:
        h.add("FragmentNode", "", ev, assetName="/" + DIR + name)
    h.write(tmp_path, "Enemy01")
    ta.write_clip(tmp_path, "EN1_COM_DMG_finish", ((0, 1, 0), (0, 1, 1)))
    _list(tmp_path, "se_finished_by_NO_victim02.fragment", ((9, 0.1), (9, 0.4), (40, 0.6)))
    _list(tmp_path, "SE_EN1_COM_DMG_finish.fragment", ((9, 0.2), (76, 0.8)))
    return str(tmp_path)


def _events(meta, cls="Enemy01"):
    return [e for s in meta["classes"][cls]["states"] for e in s["events"]]


def test_a_list_stored_with_a_lower_case_prefix_is_read(tmp_path):
    m = sound_meta.build(_extract(tmp_path))
    by_source = {}
    for e in _events(m):
        by_source.setdefault(e["source"], []).append((e["event"], e["raw"]))
    assert by_source == {
        "se_finished_by_NO_victim02.fragment": [
            ("SOUND", 0.1),
            ("SOUND", 0.4),
            ("RIGHT_FOOT_DOWN", 0.6),
        ],
        "SE_EN1_COM_DMG_finish.fragment": [("SOUND", 0.2), ("FOOT_DOWN_JUMP", 0.8)],
    }
    # counting list events: by case-blind prefix, never by the literal "SE_"
    assert sum(1 for e in _events(m) if e["source"].startswith("SE_")) == 2
    assert sum(1 for e in _events(m) if e["source"].lower().startswith("se_")) == 5
    assert "missing_event_lists" not in m["classes"]["Enemy01"]


def test_a_list_the_data_does_not_contain_is_named(tmp_path):
    gone = ["SE_RSH_COM_ATT_counter_EN4_B.fragment", "SE_zz.fragment", "SE_zz.fragment"]
    m = sound_meta.build(_extract(tmp_path, gone=gone))
    assert m["classes"]["Enemy01"]["missing_event_lists"] == [
        "/" + DIR + "SE_RSH_COM_ATT_counter_EN4_B.fragment",
        "/" + DIR + "SE_zz.fragment",
        "/" + DIR + "SE_zz.fragment",
    ]
    assert len(_events(m)) == 5  # the lists that are there are still read


def test_anim_meta_and_sound_meta_name_the_same_missing_lists(tmp_path):
    import anim_meta

    out = _extract(tmp_path, gone=["SE_gone.fragment"])
    a = anim_meta.build(out)
    s = sound_meta.build(out, anim=a)
    assert a["classes"]["Enemy01"]["missing_event_lists"] == ["/" + DIR + "SE_gone.fragment"]
    assert s["classes"]["Enemy01"]["missing_event_lists"] == ["/" + DIR + "SE_gone.fragment"]
    lower = [e for st in a["classes"]["Enemy01"]["states"] for e in st["events"]]
    assert sum(1 for e in lower if e.get("source") == "se_finished_by_NO_victim02.fragment") == 3
