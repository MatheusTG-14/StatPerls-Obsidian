import json

import yaml

from src.common import read_schema

from src.enrich import heuristics, mesh
from src.enrich.tagging import DRUG_CLASSES


def test_drug_rules():
    assert heuristics.drug_classes("Metoprolol") == ["beta-blockers"]
    assert heuristics.drug_classes("Lisinopril") == ["ace-inhibitors-and-arbs"]
    assert heuristics.drug_classes("Losartan") == ["ace-inhibitors-and-arbs"]
    assert heuristics.drug_classes("Adalimumab") == ["monoclonal-antibodies"]
    assert heuristics.drug_classes("Aspirin") == []
    assert heuristics.drug_classes("Cefazolin") == ["cephalosporins"]
    assert heuristics.drug_classes("Amoxicillin") == ["penicillins"]
    assert heuristics.drug_classes("Nystatin") == ["antifungals"]  # before the -statin rule
    assert heuristics.drug_classes("Aripiprazole") == ["antipsychotics"]  # before the -prazole rule


def test_rules_file_uses_known_classes():
    rules = yaml.safe_load(read_schema(heuristics.RULES_PATH))
    assert len(rules) >= 14
    assert {r["class"] for r in rules} <= set(DRUG_CLASSES)


def test_unknown_class_in_rules_is_rejected(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("- {pattern: 'x', class: made-up}\n", encoding="utf-8")
    try:
        heuristics.load_rules(p)
    except ValueError as e:
        assert "made-up" in str(e)
    else:
        raise AssertionError("accepted an unknown class")


def test_facets_from_title():
    assert heuristics.facets_from_title("Pediatric Asthma") == {"population": ["pediatric"]}
    got = heuristics.facets_from_title("Neonatal Jaundice (Nursing)")
    assert got == {"population": ["neonatal"], "discipline": ["nursing"]}
    assert heuristics.facets_from_title("Emergency Airway") == {"setting": ["emergency"]}
    assert heuristics.facets_from_title("EMS Triage") == {"setting": ["prehospital"]}
    assert heuristics.facets_from_title("Hypertension") == {}


def _rec(i, title):
    return {"id": i, "kind": "live", "title": title, "references": [],
            "sections": [{"title": "Mechanism of Action", "blocks": []}, {"title": "Administration", "blocks": []}]}


def _setup(tmp_path):
    from src.enrich.suggest import minimal_view
    from src.enrich.tagging import fingerprint
    l1 = tmp_path / "l1"
    l1.mkdir()
    recs = [_rec("article-1", "Metoprolol"), _rec("article-2", "Pediatric Lisinopril")]
    for r in recs:
        (l1 / f"{r['id']}.json").write_text(json.dumps(r), encoding="utf-8")
    ov = tmp_path / "ov"
    ov.mkdir()
    (ov / "system.yaml").write_text("{}\n", encoding="utf-8")
    fp1 = fingerprint(minimal_view(recs[0]))
    (ov / "tags-agent.yaml").write_text(yaml.safe_dump(
        {"article-1": {"fp": fp1, "task": "facets", "population": ["geriatric"], "setting": [], "discipline": [], "pathogen": []}}), encoding="utf-8")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "trees.json").write_text("{}", encoding="utf-8")
    return l1, ov, raw


def test_classify_flags_only_unanswered(tmp_path):
    l1, ov, raw = _setup(tmp_path)
    out = tmp_path / "s.json"
    mesh.classify(str(l1), str(raw), str(ov / "system.yaml"), str(out), str(tmp_path / "r.json"))
    side = json.loads(out.read_text(encoding="utf-8"))
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert "auto" not in side["article-1"]
    assert side["article-1"]["facets"] == {"population": ["geriatric"]}
    assert side["article-2"]["auto"] is True
    assert side["article-2"]["facets"] == {"population": ["pediatric"], "drug-class": ["ace-inhibitors-and-arbs"]}
    assert report["auto_classified"] == ["article-2"]


def test_auto_tag_renders_and_validates():
    from src.validate.check import TAG_OK
    assert any(f("status/auto-classified") for f in TAG_OK)
    import src.render.build as b
    assert "status/auto-classified" in b.auto_tags(True)
    assert b.auto_tags(False) == []
