from src.render import hubs

CAT = {"slug": "cardiovascular", "folder": "Cardiovascular", "aliases": ["Cardiology"], "trees": []}


def test_menu_line():
    assert hubs.menu_line("oncology", ["respiratory"], "drug") == (
        "> [!hubs] [[Home (hub)|Home]] › [[Oncology (hub)|Oncology]] · [[Respiratory (hub)|Respiratory]]"
        " · [[Pharmacology (hub)|Pharmacology]]")


def test_menu_line_no_type_hub():
    assert hubs.menu_line("cardiovascular", [], "disease") == "> [!hubs] [[Home (hub)|Home]] › [[Cardiovascular (hub)|Cardiovascular]]"


def test_menu_line_type_hub_not_repeated():
    assert hubs.menu_line("toxicology", [], "toxicology").count("Toxicology (hub)") == 1


def test_category_hub_shape():
    out = hubs.render_category_hub(CAT, {"disease": ["beta", "Alpha"], "drug": [], "procedure": ["Gamma"]}, ["Delta"], ["respiratory"])
    assert out == """---
aliases:
  - "Cardiology"
tags:
  - "type/hub"
---
[[Home (hub)|Home]] › Cardiovascular

Related: [[Respiratory (hub)|Respiratory]]

> [!hub-list]- Diseases (2)
> - [[Alpha]]
> - [[beta]]

> [!hub-list]- Procedures (1)
> - [[Gamma]]

> [!hub-list]- Also relevant (1)
> - [[Delta]]
"""


def test_single_group_hub_is_open():
    out = hubs.render_list_hub("EMS", [("EMS", ["B", "A"])])
    assert "> [!hub-list]+ EMS (2)\n> - [[A]]\n> - [[B]]" in out
    assert out.count("Related:") == 0


def test_related_is_symmetric_and_capped():
    a = {"1": ("cardiovascular", ["respiratory", "nervous"]), "2": ("cardiovascular", ["respiratory", "skin", "eye"]),
         "3": ("digestive", ["cardiovascular"])}
    r = hubs.related(a)
    assert r["cardiovascular"] == ["respiratory", "digestive", "nervous", "skin"]
    assert r["respiratory"] == ["cardiovascular"]


def test_home_lists_every_category():
    out = hubs.render_home(["Anatomy"], ["All articles.base"], {})
    for c in hubs.CATEGORIES:
        assert f"[[{c['folder']} (hub)|{c['folder']}]]" in out
    assert "[[Anatomy (hub)|Anatomy]]" in out and "[[All articles.base|All articles]]" in out


def test_menu_line_with_subcategory():
    out = hubs.menu_line("cardiovascular", [], "disease", "arrhythmias-and-ecg")
    assert out == ("> [!hubs] [[Home (hub)|Home]] › [[Cardiovascular (hub)|Cardiovascular]]"
                   " › [[Cardiovascular (hub)#Arrhythmias and ECG|Arrhythmias and ECG]]")


def test_category_hub_with_subcategories():
    cat = {"slug": "cardiovascular", "folder": "Cardiovascular", "aliases": [], "trees": []}
    members = {"arrhythmias-and-ecg": {"disease": ["B", "A"], "drug": ["C"]}, "other-cardiovascular": {"concept": ["D"]}}
    out = hubs.render_subcategory_hub(cat, members, [], [])
    assert "## Arrhythmias and ECG\n\n> [!hub-list]- Diseases (2)\n> - [[A]]\n> - [[B]]\n\n> [!hub-list]- Drugs (1)\n> - [[C]]" in out
    assert "## Other Cardiovascular\n\n> [!hub-list]+ Concepts (1)\n> - [[D]]" in out
    assert "## Coronary" not in out  # empty subcategories omitted


def test_sectioned_hub_puts_groups_under_headings():
    out = hubs.render_sectioned_hub("Pharmacology", [("Cardiovascular", [("Beta-blockers", ["Metoprolol", "Atenolol"]),
                                                                          ("Diuretics", [])]),
                                                     ("Blood", [("Anticoagulants", ["Warfarin"])]),
                                                     ("Empty", [("X", [])])])
    assert out.endswith("""[[Home (hub)|Home]] › Pharmacology

## Cardiovascular

> [!hub-list]+ Beta-blockers (2)
> - [[Atenolol]]
> - [[Metoprolol]]

## Blood

> [!hub-list]+ Anticoagulants (1)
> - [[Warfarin]]
""")


def test_drug_class_sections_follow_vocabulary_order():
    from src.render.build import drug_class_sections
    secs = drug_class_sections({"A": ["opioids", "antidotes-and-chelators"], "B": ["beta-blockers"], "C": []})
    names = [s for s, _ in secs]
    assert names[0] == "Cardiovascular" and names[-1] == "Unclassified"
    assert dict(secs[0][1])["Beta-blockers"] == ["B"]
    flat = {label: stems for _, groups in secs for label, stems in groups}
    assert flat["Opioids"] == ["A"] and flat["Antidotes and chelators"] == ["A"] and flat["No class"] == ["C"]


def test_home_starts_with_plugin_block():
    import json
    out = hubs.render_home(["Anatomy"], ["All articles.base"], {"cardiovascular": 5})
    body = out.split("---\n", 2)[2].splitlines()
    assert body[0] == "```statpearls-home"
    data = json.loads(body[1])
    assert body[2] == "```"
    assert data["categories"][0] == {"name": "Cardiovascular", "hub": "Cardiovascular (hub)", "count": 5}
    assert data["categories"][1]["count"] == 0 and len(data["categories"]) == len(hubs.CATEGORIES)
    assert data["themes"] == [{"name": "Anatomy", "hub": "Anatomy (hub)"}] and data["tables"] == ["All articles.base"]
    assert out.index("```") < out.index("## Categories")


def test_menu_line_web_links():
    out = hubs.menu_line("oncology", [], "disease", nbk="NBK1", pmid="2")
    assert out.endswith("· [Bookshelf](https://www.ncbi.nlm.nih.gov/books/NBK1/) · [PubMed](https://pubmed.ncbi.nlm.nih.gov/2/)")
    assert hubs.menu_line("oncology", [], "disease", nbk="NBK1").endswith("[Bookshelf](https://www.ncbi.nlm.nih.gov/books/NBK1/)")
    assert hubs.menu_line("oncology", [], "disease") == "> [!hubs] [[Home (hub)|Home]] › [[Oncology (hub)|Oncology]]"
