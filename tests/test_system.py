from src.enrich.system import CATEGORIES, assign, category_of_tree, vote


def test_vocabulary_has_22_unique_categories():
    slugs = [c["slug"] for c in CATEGORIES]
    assert len(slugs) == 22 == len(set(slugs))
    assert {"oncology", "infectious", "general", "basic-science"} <= set(slugs)


def test_tree_prefixes():
    assert category_of_tree("C14.280.647") == "cardiovascular"
    assert category_of_tree("C12.050.703") == "obgyn"
    assert category_of_tree("C12.950.419") == "kidney-urinary"
    assert category_of_tree("C12.050.351.968.419") == "kidney-urinary"  # kidney diseases also sit under the female branch
    assert category_of_tree("C12.050.351.500.242") == "obgyn"
    assert category_of_tree("F03.600") == "mental-health"
    assert category_of_tree("A01.236") is None
    assert category_of_tree("D27.505") is None
    assert category_of_tree("C12.100.937.640.400") is None  # STDs under male urogenital: counted via C01 only


def test_vote_weights_and_missing_data():
    trees = {"D1": ["C14.1"], "D2": ["C08.1"], "D3": []}
    refs = [[("D1", True), ("D2", False)], [("D1", False)], [("D3", True)], [("DX", False)], []]
    shares, n = vote(refs, trees)
    assert n == 2
    assert shares == {"cardiovascular": round((2 / 3 + 1) / 2, 4), "respiratory": round((1 / 3) / 2, 4)}


def test_vote_no_references():
    assert vote([], {}) == ({}, 0)


def test_assign_order():
    s = {"respiratory": 0.5, "oncology": 0.31, "immunology": 0.05}
    assert assign("Lung Cancer", "disease", None, s, 10, None) == ("oncology", ["respiratory"], "mesh-vote")
    assert assign("Lung Cancer", "disease", None, s, 10, "respiratory")[0] == "respiratory"
    pit = {"endocrine-metabolic": 0.30, "oncology": 0.289, "nervous": 0.288}
    assert assign("Pituitary Cancer", "disease", None, pit, 20, None)[0] == "oncology"
    assert assign("Colonoscopy", "procedure", None, {"digestive": 0.5, "oncology": 0.27}, 20, None)[0] == "digestive"
    assert assign("Neuroanatomy, Pons", "anatomy", None, s, 10, None)[2] == "title"
    assert assign("Nickel Toxicology", "toxicology", None, s, 10, None)[:1] == ("toxicology",)
    assert assign("X", "disease", None, {"nervous": 0.48, "mental-health": 0.46}, 10, None)[0] == "mental-health"
    assert assign("X", "disease", None, {"cardiovascular": 0.30, "respiratory": 0.29}, 10, None)[0] == "general"
    assert assign("Optic Atrophy", "disease", None, {"eye": 0.44, "nervous": 0.44}, 18, None)[0] == "eye"
    assert assign("PKU", "disease", None, {"congenital-genetic": 0.32, "endocrine-metabolic": 0.32, "nervous": 0.29}, 45, None)[0] == "endocrine-metabolic"
    assert assign("Lifestyle", "concept", None, {"cardiovascular": 0.27, "oncology": 0.16}, 23, None)[0] == "general"
    assert assign("Facial Nerve Trauma", "disease", None, {"nervous": 0.32, "oral-dental": 0.23}, 46, None)[0] == "nervous"
    assert assign("Anatomy, Back, Muscles", "anatomy", "back", {}, 0, None) == ("musculoskeletal", [], "fallback")
    assert assign("Anatomy, Head and Neck, Ear", "anatomy", "head-and-neck", {"ent": 0.7}, 8, None)[0] == "ent"
    assert assign("Physiology, Bile", "basic-science", None, {}, 2, None)[0] == "basic-science"


def test_apply_agent_only_on_general_fallback():
    from src.enrich.system import apply_agent
    assert apply_agent("general", ["oncology"], "fallback", ("oncology", "high")) == ("oncology", [], "agent")
    assert apply_agent("general", [], "fallback", ("skin", "medium")) == ("skin", [], "agent")
    assert apply_agent("general", [], "fallback", ("skin", "low")) == ("general", [], "fallback")
    assert apply_agent("general", [], "fallback", ("general", "high")) == ("general", [], "fallback")
    assert apply_agent("cardiovascular", [], "mesh-vote", ("skin", "high")) == ("cardiovascular", [], "mesh-vote")
    assert apply_agent("general", [], "override", ("skin", "high")) == ("general", [], "override")
    assert apply_agent("general", [], "fallback", None) == ("general", [], "fallback")


def test_subcategory_vocabulary():
    from src.enrich.system import SUBCATEGORIES, sub_slug
    assert set(SUBCATEGORIES) <= {c["slug"] for c in CATEGORIES}
    assert sub_slug("Heart Failure, Cardiomyopathy and Pericardium") == "heart-failure-cardiomyopathy-and-pericardium"
    for cat, subs in SUBCATEGORIES.items():
        slugs = [s["slug"] for s in subs]
        assert len(slugs) == len(set(slugs)) and subs[-1]["folder"].startswith("Other ")


def test_pick_sub():
    from src.enrich.system import pick_sub
    agent = {"a1": ("cardiovascular", "arrhythmias-and-ecg", "high"), "a2": ("cardiovascular", "sleep", "low"),
             "a3": ("nervous", "sleep", "high")}
    user = {"a4": "cardiovascular/congenital-heart-disease"}
    assert pick_sub("a1", "cardiovascular", agent, user) == ("arrhythmias-and-ecg", "agent")
    assert pick_sub("a2", "cardiovascular", agent, user) == ("other-cardiovascular", "fallback")
    assert pick_sub("a3", "cardiovascular", agent, user) == ("other-cardiovascular", "fallback")  # category changed since
    assert pick_sub("a4", "cardiovascular", agent, user) == ("congenital-heart-disease", "override")
    assert pick_sub("a1", "skin", agent, user) == ("other-skin", "fallback")  # every category has subcategories now (DEC-21)
