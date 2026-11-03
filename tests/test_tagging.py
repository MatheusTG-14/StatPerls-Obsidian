from src.enrich.tagging import FACETS, fingerprint, parse_tag_answers, task_of


def test_fingerprint_is_stable_and_input_sensitive():
    v = {"id": "a1", "title": "T", "headings": ["Introduction"], "intro": "x"}
    assert fingerprint(v) == fingerprint(dict(reversed(list(v.items()))))
    assert len(fingerprint(v)) == 12 and fingerprint(v) != fingerprint({**v, "intro": "y"})


def test_task_of():
    assert task_of("cardiovascular", "other-cardiovascular") == "recheck"
    assert task_of("nervous", "neuroanatomy-and-neurophysiology") == "sub"
    assert task_of("skin", None) == "sub"
    assert task_of("cardiovascular", "arrhythmias-and-ecg") == "facets"


def test_parse_tag_answers_validates_every_field():
    lines = "\n".join([
        '{"id": "a1", "sub": "glaucoma", "sub_conf": "high", "population": ["geriatric"], "setting": [], "discipline": ["surgery"], "pathogen": []}',
        '{"id": "a2", "sub": "glaucoma", "sub_conf": "high", "population": ["teen"], "setting": [], "discipline": [], "pathogen": []}',
        '{"id": "a3", "category": "nervous", "sub": "sleep", "sub_conf": "medium", "population": [], "setting": [], "discipline": [], "pathogen": ["virus/rna"]}',
        '{"id": "a4", "category": "nervous", "sub": "glaucoma", "sub_conf": "medium", "population": [], "setting": [], "discipline": [], "pathogen": []}',
    ])
    ok, errors = parse_tag_answers(lines, {"a1": "sub", "a2": "sub", "a3": "recheck", "a4": "recheck"}, "eye")
    assert ok["a1"] == {"cat": "eye", "sub": "glaucoma", "sub_conf": "high", "population": ["geriatric"], "setting": [],
                        "discipline": ["surgery"], "pathogen": []}
    assert ok["a3"]["cat"] == "nervous" and ok["a3"]["pathogen"] == ["virus/rna"]
    assert set(ok) == {"a1", "a3"} and len(errors) == 2
    assert "pediatric" in FACETS["population"]


def test_facets_only_answer_has_no_sub():
    ok, errors = parse_tag_answers('{"id": "a1", "population": [], "setting": ["emergency"], "discipline": [], "pathogen": []}',
                                   {"a1": "facets"}, "cardiovascular")
    assert ok == {"a1": {"population": [], "setting": ["emergency"], "discipline": [], "pathogen": []}} and not errors


def test_apply_entry():
    from src.enrich.tagging import apply_entry
    e = {"fp": "abc", "task": "recheck", "cat": "nervous", "sub": "stroke-and-cerebrovascular-disease", "sub_conf": "high",
         "population": [], "setting": ["emergency"], "discipline": [], "pathogen": []}
    assert apply_entry("cardiovascular", ["respiratory"], "mesh-vote", e, "abc") == (
        "nervous", ["cardiovascular", "respiratory"], "agent-recheck", ("nervous", "stroke-and-cerebrovascular-disease", "high"),
        {"setting": ["emergency"]})
    assert apply_entry("cardiovascular", [], "override", e, "abc")[:3] == ("cardiovascular", [], "override")  # user wins
    assert apply_entry("cardiovascular", [], "mesh-vote", e, "zzz") == ("cardiovascular", [], "mesh-vote", None, {})  # stale
    low = {**e, "sub_conf": "low"}
    assert apply_entry("cardiovascular", [], "mesh-vote", low, "abc")[:4] == ("cardiovascular", [], "mesh-vote", None)


def test_followup_task_rechecks_unchecked_other_and_fills_missing():
    from src.enrich.tagging import followup_task
    assert followup_task("toxicology", "other-toxicology", {"task": "sub"}) == "recheck"
    assert followup_task("cardiovascular", "other-cardiovascular", {"task": "recheck"}) is None  # done in DEC-21
    assert followup_task("skin", "acne", {"task": "sub"}) is None
    assert followup_task("skin", None, None) == "sub"  # no valid answer yet
    assert followup_task("eye", "other-eye", None) == "recheck"


def test_collect_tags_merges_into_existing_file(tmp_path):
    import json
    import yaml
    from src.enrich.tagging import collect_tags
    out = tmp_path / "tags.yaml"
    out.write_text(yaml.safe_dump({"a1": {"fp": "111", "task": "facets", "population": [], "setting": [], "discipline": [],
                                          "pathogen": []},
                                   "a2": {"fp": "old", "task": "facets", "population": [], "setting": [], "discipline": [],
                                          "pathogen": []}}), encoding="utf-8")
    b = tmp_path / "batches"
    b.mkdir()
    (b / "facets__all__00.jsonl").write_text(json.dumps({"id": "a2", "fp": "222"}) + "\n", encoding="utf-8")
    (b / "facets__all__00.answers.jsonl").write_text(
        '{"id": "a2", "population": [], "setting": ["emergency"], "discipline": [], "pathogen": []}\n', encoding="utf-8")
    collect_tags(b, out, "m")
    got = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert set(got) == {"a1", "a2"} and got["a1"]["fp"] == "111"
    assert got["a2"]["fp"] == "222" and got["a2"]["setting"] == ["emergency"]


def test_drug_class_vocabulary_is_frozen_and_unique():
    from src.enrich.tagging import DRUG_CLASSES
    assert len(DRUG_CLASSES) == 78 and len(set(DRUG_CLASSES)) == 78
    assert "beta-blockers" in DRUG_CLASSES and "monoclonal-antibodies" in DRUG_CLASSES


def test_parse_drug_answers():
    from src.enrich.tagging import parse_drug_answers
    lines = "\n".join([
        '{"id": "d1", "drug_class": ["beta-blockers"], "conf": "high"}',
        '{"id": "d2", "drug_class": ["immunomodulators-and-dmards", "dermatologic-agents", "monoclonal-antibodies"], "conf": "medium"}',
        '{"id": "d3", "drug_class": ["made-up-class"], "conf": "high"}',
        '{"id": "d4", "drug_class": [], "conf": "high"}',
        '{"id": "d5", "drug_class": ["opioids", "antidotes-and-chelators", "nsaids-and-analgesics"], "conf": "high"}',
        '{"id": "d6", "drug_class": ["opioids"], "conf": "sure"}',
        '{"id": "zz", "drug_class": ["opioids"], "conf": "high"}',
    ])
    ok, errors = parse_drug_answers(lines, {"d1", "d2", "d3", "d4", "d5", "d6"})
    assert ok == {"d1": {"drug_class": ["beta-blockers"], "conf": "high"},
                  "d2": {"drug_class": ["immunomodulators-and-dmards", "dermatologic-agents", "monoclonal-antibodies"],
                         "conf": "medium"}}
    assert len(errors) == 5


def test_apply_drug():
    from src.enrich.tagging import apply_drug
    e = {"fp": "abc", "drug_class": ["opioids", "antidotes-and-chelators"], "conf": "high"}
    assert apply_drug(e, "abc") == ["antidotes-and-chelators", "opioids"]
    assert apply_drug(e, "zzz") == [] and apply_drug(None, "abc") == []
    assert apply_drug({**e, "conf": "low"}, "abc") == []


def test_collect_drugs_merges(tmp_path):
    import json
    import yaml
    from src.enrich.tagging import collect_drugs
    out = tmp_path / "drugs.yaml"
    out.write_text(yaml.safe_dump({"d1": {"fp": "111", "drug_class": ["opioids"], "conf": "high"}}), encoding="utf-8")
    b = tmp_path / "b"
    b.mkdir()
    (b / "drugs__all__00.jsonl").write_text(json.dumps({"id": "d2", "fp": "222"}) + "\n", encoding="utf-8")
    (b / "drugs__all__00.answers.jsonl").write_text('{"id": "d2", "drug_class": ["insulins"], "conf": "high"}\n',
                                                     encoding="utf-8")
    assert collect_drugs(b, out, "m") == []
    got = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert got == {"d1": {"fp": "111", "drug_class": ["opioids"], "conf": "high"},
                   "d2": {"fp": "222", "drug_class": ["insulins"], "conf": "high"}}


def test_validator_accepts_drug_class_tags():
    from src.validate.check import TAG_OK
    assert any(f("drug-class/beta-blockers") for f in TAG_OK)
    assert not any(f("drug-class/made-up") for f in TAG_OK)


def test_facet_tags_include_drug_classes():
    from src.render.build import facet_tags
    assert facet_tags({"setting": ["emergency"], "drug-class": ["opioids", "antidotes-and-chelators"]}) == [
        "setting/emergency", "drug-class/antidotes-and-chelators", "drug-class/opioids"]
