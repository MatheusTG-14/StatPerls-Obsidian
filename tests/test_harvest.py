from src.enrich.harvest import user_changes, merge_overrides

FM = '---\ntitle: "X"\nsystem: "{s}"\n---\nbody\n'


def test_user_changes_property_beats_folder(tmp_path):
    arts = tmp_path / "StatPearls" / "Articles"
    for folder, stem, prop in [("General and Professional", "Moved by drag", "general"),
                               ("General and Professional", "Edited property", "skin"),
                               ("Skin", "Untouched", "skin")]:
        (arts / folder).mkdir(parents=True, exist_ok=True)
        (arts / folder / f"{stem}.md").write_text(FM.format(s=prop), encoding="utf-8")
    (arts / "Oncology").mkdir()
    (arts / "General and Professional" / "Moved by drag.md").rename(arts / "Oncology" / "Moved by drag.md")
    stems = {"a1": "Moved by drag", "a2": "Edited property", "a3": "Untouched"}
    current = {"a1": "general", "a2": "general", "a3": "skin"}
    assert user_changes(tmp_path / "StatPearls", stems, current) == {"a1": "oncology", "a2": "skin"}


def test_merge_overrides_keeps_header_and_sorts(tmp_path):
    p = tmp_path / "system.yaml"
    p.write_text("# header line\narticle-9: skin   # old note\n", encoding="utf-8")
    merge_overrides(p, {"article-1": "oncology"}, {"article-1": "Some Title"}, "2026-11-02")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# header line\n")
    assert text.index("article-1:") < text.index("article-9:")
    assert "article-1: oncology   # Some Title (user, 2026-11-02)" in text
    assert "article-9: skin   # old note" in text


def test_user_changes_reads_only_files_newer_than_since(tmp_path):
    import os
    d = tmp_path / "StatPearls" / "Articles" / "Skin"
    d.mkdir(parents=True)
    p = d / "Old edit.md"
    p.write_text(FM.format(s="oncology"), encoding="utf-8")
    os.utime(p, (1000, 1000))
    assert user_changes(tmp_path / "StatPearls", {"a1": "Old edit"}, {"a1": "skin"}, since=2000) == {}
    assert user_changes(tmp_path / "StatPearls", {"a1": "Old edit"}, {"a1": "skin"}, since=500) == {"a1": "oncology"}


def test_sub_changes_from_edited_property(tmp_path):
    from src.enrich.harvest import sub_changes
    d = tmp_path / "StatPearls" / "Articles" / "Cardiovascular"
    d.mkdir(parents=True)
    fm = '---\nsystem: "cardiovascular"\nsubsystem: "{}"\n---\n'
    (d / "Edited.md").write_text(fm.format("arrhythmias-and-ecg"), encoding="utf-8")
    (d / "Same.md").write_text(fm.format("other-cardiovascular"), encoding="utf-8")
    (d / "Bad.md").write_text(fm.format("glaucoma"), encoding="utf-8")
    built = {"Edited": "cardiovascular/other-cardiovascular", "Same": "cardiovascular/other-cardiovascular",
             "Bad": "cardiovascular/other-cardiovascular"}
    stems = {"a1": "Edited", "a2": "Same", "a3": "Bad"}
    assert sub_changes(tmp_path / "StatPearls", stems, built) == {"a1": "cardiovascular/arrhythmias-and-ecg"}


def test_pending_ignores_new_classification_not_yet_built(tmp_path):
    from src.enrich.harvest import pending_changes
    d = tmp_path / "StatPearls" / "Articles" / "General and Professional"
    d.mkdir(parents=True)
    (d / "Waiting.md").write_text(FM.format(s="general"), encoding="utf-8")
    built = {"Waiting": "general/other-general-and-professional"}
    pinned_at_last_build = {"a1": "general"}
    assert pending_changes(tmp_path / "StatPearls", {"a1": "Waiting"}, pinned_at_last_build, built, since=None) == {}


def test_user_changes_reads_category_from_top_folder(tmp_path):
    d = tmp_path / "StatPearls" / "Articles" / "Cardiovascular" / "Arrhythmias and ECG"
    d.mkdir(parents=True)
    (d / "Nested.md").write_text(FM.format(s="cardiovascular"), encoding="utf-8")
    assert user_changes(tmp_path / "StatPearls", {"a1": "Nested"}, {"a1": "cardiovascular"}) == {}
    assert user_changes(tmp_path / "StatPearls", {"a1": "Nested"}, {"a1": "skin"}) == {"a1": "cardiovascular"}
