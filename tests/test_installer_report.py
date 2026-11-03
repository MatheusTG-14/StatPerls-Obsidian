import json

from src.installer import report


def test_content_hashes_and_diff():
    idx = {"article-1": {"content_hash": "a"}, "article-2": {"content_hash": "b"}, "article-3": {"kind": "live"}}
    assert report.content_hashes(idx) == {"article-1": "a", "article-2": "b"}
    old = {"article-1": "a", "article-2": "b", "article-3": "c"}
    new = {"article-1": "a", "article-2": "B", "article-4": "d"}
    assert report.diff(old, new) == {"new": ["article-4"], "changed": ["article-2"], "deleted": ["article-3"]}


def test_diff_sorts_ids_naturally_by_string():
    assert report.diff({}, {"article-2": "x", "article-1": "y"})["new"] == ["article-1", "article-2"]


def test_dangling_mine_links(tmp_path):
    vault = tmp_path / "vault"
    (vault / "StatPearls" / "Articles" / "Eye").mkdir(parents=True)
    (vault / "StatPearls" / "Articles" / "Eye" / "Pediatric Cataract.md").write_text("x", encoding="utf-8")
    (vault / "Mine").mkdir()
    (vault / "Mine" / "note.md").write_text(
        "See [[Pediatric Cataract]] and [[Gone Article|alias]] and [[Mine own]] and [[Pediatric Cataract#Heading]].\n", encoding="utf-8")
    (vault / "Mine" / "Mine own.md").write_text("hi", encoding="utf-8")
    got = report.dangling_mine_links(vault)
    assert got == [("Mine/note.md", "Gone Article")]


def test_summary_lines_plain_english(tmp_path):
    d = {"new": ["article-1"] * 12, "changed": ["a"] * 40, "deleted": ["b"] * 3}
    rep = report.write_report(tmp_path / "update.json", d, ["x"] * 15, [("Mine/n.md", "Gone")], {})
    assert json.loads((tmp_path / "update.json").read_text(encoding="utf-8")) == rep
    text = "\n".join(report.summary_lines(rep))
    assert "12 new articles, 40 updated, 3 removed" in text
    assert "15 placed automatically and tagged status/auto-classified" in text
    assert "Mine/n.md" in text
    for word in ("L1", "fingerprint", "shard", "sidecar"):
        assert word not in text


def test_summary_lines_nothing_changed(tmp_path):
    rep = report.write_report(tmp_path / "r.json", {"new": [], "changed": [], "deleted": []}, [], [], {})
    assert "No articles changed" in "\n".join(report.summary_lines(rep))
