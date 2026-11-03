from pathlib import Path

from src.common import no_ws
from src.extract.nxml import body_text, extract, inline_text, nbk_links, source_body_text

FIX = Path(__file__).parent / "synthetic" / "article-900001.nxml"


def rec():
    return extract(FIX)


def test_metadata():
    r = rec()
    assert r["id"] == "article-900001"
    assert r["kind"] == "live"
    assert r["title"] == "Synthetic Disease: Test"
    assert r["updated"] == "2025-03-05"
    assert [a["name"] for a in r["authors"]] == ["Jane A. Doe", "Rick Roe"]
    assert r["authors"][0]["aff"] == "Test University"
    assert r["license_url"].endswith("by-nc-nd/4.0/")


def test_exclusions_counted():
    r = rec()
    assert r["excluded"] == {"sections": ["Review Questions"], "promo_paragraphs": 1}
    assert [s["title"] for s in r["sections"]] == ["Continuing Education Activity", "Introduction"]


def test_whitespace_collapsed_text_kept():
    first = rec()["sections"][0]["blocks"][0]
    assert first == {"t": "p", "c": [{"t": "text", "v": "Alpha beta gamma."}]}


def test_bold_only_flag_and_nested_list():
    blocks = rec()["sections"][0]["blocks"]
    assert blocks[1]["bold_only"] is True
    lst = blocks[2]
    assert lst["t"] == "list" and not lst["ordered"]
    assert lst["items"][1][1]["t"] == "list" and lst["items"][1][1]["ordered"]


def test_inlines_and_citations():
    p = rec()["sections"][1]["blocks"][0]
    kinds = [n["t"] for n in p["c"]]
    assert {"link", "i", "sup", "sub", "cite"} <= set(kinds)
    assert inline_text(p["c"]).endswith("pipe.[1][2]")


def test_figures_body_and_back():
    figs = rec()["figures"]
    assert [(f["id"].rsplit(".", 1)[1], f["where"], f["kind"], f["src"]) for f in figs] == [
        ("f1", "article-900001.s2", "image", "Case_Image.jpg"),
        ("f2", "back", "image", "case_image.jpg"),
        ("f3", "back", "video", "clip.mp4"),
    ]
    assert inline_text(figs[0]["caption"]) == "Inline Histology. H&E stain at 40x. Contributed by J Doe, MD"


def test_table_and_code():
    blocks = rec()["sections"][1]["blocks"]
    table = next(b for b in blocks if b["t"] == "table")
    assert len(table["rows"]) == 2 and inline_text(table["rows"][1][1]) == "None | nil"
    code = next(b for b in blocks if b["t"] == "code")
    assert code["v"] == "  keep   this"


def test_references():
    refs = rec()["references"]
    assert refs[0]["text"] == "Smith A, Jones B. A study of things. J Test. 2020;12(3):45-50."
    assert refs[0]["ids"] == {"pmid": "11111111"}
    assert refs[1]["text"].startswith("Some Committee. A chapter. A Book. City: Pub;")


def test_fidelity_round_trip():
    assert no_ws(body_text(rec())) == no_ws(source_body_text(FIX))


def test_nbk_links():
    assert nbk_links(rec()) == ["NBK900002"]


def test_deterministic_hash():
    assert rec()["content_hash"] == rec()["content_hash"]
