from pathlib import Path

from src.extract.nxml import extract
from src.render import markdown as md
from src.render.links import TitleIndex
from src.render.names import Registry, sanitize
from src.render.tags import anatomy_region, anatomy_structure, modality
from src.validate.check import strip_markup
from src.common import no_ws
from src.extract.nxml import block_text

FIX = Path(__file__).parent / "synthetic" / "article-900001.nxml"


def test_sanitize():
    assert sanitize("Anatomy, Shoulder and Upper Limb: Supraclavicular Fossa") == "Anatomy, Shoulder and Upper Limb - Supraclavicular Fossa"
    assert sanitize('A/B "C" [D] #E? ^F.') == "A-B -C- -D- -E- -F"


def test_registry_is_sticky_and_case_insensitive(tmp_path):
    r = Registry(tmp_path / "reg.json")
    assert r.assign("articles", "a1", "Foo", "NBK1") == "Foo"
    assert r.assign("articles", "a2", "foo", "NBK2") == "foo (NBK2)"
    r.save()
    r2 = Registry(tmp_path / "reg.json")
    assert r2.assign("articles", "a1", "Renamed", "NBK1") == "Foo"
    assert r2.assign_with("att", "A.jpg", lambda n: "a.jpg" if n == 1 else f"a__{n}.jpg") == "a.jpg"
    assert r2.assign_with("att", "a.jpg", lambda n: "a.jpg" if n == 1 else f"a__{n}.jpg") == "a__2.jpg"


def test_title_index_longest_first_and_policy():
    idx = TitleIndex([("Erythema Nodosum", "t1"), ("Erythema", "t2"), ("Pain", "t3"), ("MRSA", "t4"), ("Crohn Disease", "t5")])
    hits = list(idx.find("Painful erythema nodosum with MRSA and Crohn disease. Erythema again"))
    assert [(t) for _, _, t in hits] == ["t1", "t5", "t2"]
    assert list(idx.find("crohn. disease")) == []


def test_links_first_mention_and_no_self():
    idx = TitleIndex([("Synthetic Other Topic", "o"), ("Synthetic Disease", "self")])
    ctx = md.Ctx("self", idx, {"o": "Synthetic Other Topic", "self": "Me"})
    out = md.text_with_links("Synthetic Other Topic and synthetic other topic; Synthetic Disease", ctx)
    assert out == "[[Synthetic Other Topic]] and synthetic other topic; Synthetic Disease"


def test_escape_round_trip_and_line_start():
    s = "*a* _b_ [1] | $x <y> #tag 1. ok == =="
    assert md.unesc(md.esc(s)) == s
    assert md.esc_line_start("1. not a list") == "1\\. not a list"


def test_blocks_render_and_strip_back_to_source():
    rec = extract(FIX)
    ctx = md.Ctx(rec["id"])
    for s in rec["sections"]:
        for b in s["blocks"]:
            if b["t"] == "figref":
                continue
            out = md.block(b, ctx, 0)
            assert no_ws(block_text(b)) in strip_markup(out), out


def test_subheading_rule():
    assert md.is_subheading({"t": "p", "bold_only": True, "c": [{"t": "b", "c": [{"t": "text", "v": "Pharmacokinetics"}]}]})
    assert not md.is_subheading({"t": "p", "bold_only": True, "c": [{"t": "b", "c": [{"t": "text", "v": "A full sentence."}]}]})


def test_tags():
    assert anatomy_region("Anatomy, Shoulder and Upper Limb: Supraclavicular Fossa") == "shoulder-and-upper-limb"
    assert anatomy_structure("Anatomy, Thorax: Heart Valves") == "Heart Valves"
    assert modality("H&E stain, 40x. Contributed by X", "image") == "histology"
    assert modality("Axial CT of the abdomen", "image") == "ct"
    assert modality("Computed tomography scan", "image") == "ct"
    assert modality("anything", "video") == "video"


def test_head_of_longer_term_not_linked():
    idx = TitleIndex([("Adenosine", "a"), ("Interferon", "i"), ("Incidence", "n"), ("Digoxin", "d")])
    text = "cyclic adenosine monophosphate, adenosine triphosphate, interferon regulatory factor, the incidence, digoxin toxicity, adenosine."
    assert [t for _, _, t in idx.find(text)] == ["d", "a"]


def test_list_item_text_that_looks_like_a_marker_is_escaped():
    b = {"t": "list", "ordered": False, "items": [[{"t": "p", "c": [{"t": "text", "v": "1. Family history"}]}]]}
    assert md.block(b, md.Ctx("x"), 0) == r"- 1\. Family history"


def test_citations_link_to_their_reference():
    ctx = md.Ctx("x")
    ctx.refs = {"x.r13": 13, "x.r14": 14}
    nodes = [{"t": "text", "v": "rash."}, {"t": "cite", "rid": "x.r13", "v": "[13]"},
             {"t": "cite", "rid": "x.r14", "v": "[14]"}, {"t": "cite", "rid": "x.r99", "v": "[99]"},
             {"t": "cite", "rid": "x.r13", "v": ""}]
    out = md.inl(nodes, ctx)
    assert out == r"rash.[\[13\]](#^ref-13)[\[14\]](#^ref-14)\[99\]"
    assert no_ws("rash.[13][14][99]") in strip_markup(out)


def test_registry_sticky_category(tmp_path):
    r = Registry(tmp_path / "reg.json")
    assert r.sticky("system", "a1", "cardiovascular") == "cardiovascular"
    r.save()
    r2 = Registry(tmp_path / "reg.json")
    assert r2.sticky("system", "a1", "respiratory") == "cardiovascular"
    assert r2.sticky("system", "a1", "respiratory", force=True) == "respiratory"


def test_mine_path_links():
    from src.validate.check import mine_path_links
    assert mine_path_links("[[StatPearls/Articles/X]] [[Y]] ![[StatPearls/_attachments/a.jpg|300]]") == [
        "StatPearls/Articles/X", "StatPearls/_attachments/a.jpg"]


def test_hub_collision():
    from src.validate.check import hub_collisions
    assert hub_collisions({"Oncology (hub)", "Eye (hub)"}, {"oncology (hub)", "eye"}) == {"Oncology (hub)"}


def test_missing_sidecar_pins_nothing(tmp_path):
    from src.render.build import load_systems
    r = Registry(tmp_path / "reg.json")
    out = load_systems({"a1"}, r, path=str(tmp_path / "none.json"))
    assert out == {"a1": ("general", [], "fallback", None, {}, False)}
    assert r.get("system", "a1") is None


def test_agent_recheck_moves_a_pinned_article(tmp_path):
    import json
    from src.render.build import load_systems
    r = Registry(tmp_path / "reg.json")
    r.sticky("system", "a1", "toxicology")
    side = {"a1": {"primary": "eye", "secondary": ["toxicology"], "rule": "agent-recheck", "sub": "lens-and-cataract", "facets": {}},
            "a2": {"primary": "eye", "secondary": [], "rule": "mesh-vote", "sub": None, "facets": {}}}
    r.sticky("system", "a2", "skin")
    p = tmp_path / "system.json"
    p.write_text(json.dumps(side), encoding="utf-8")
    out = load_systems({"a1", "a2"}, r, path=str(p))
    assert out["a1"][0] == "eye" and out["a1"][3] == "lens-and-cataract"
    assert out["a2"][0] == "skin"  # a plain vote never moves a pinned note
