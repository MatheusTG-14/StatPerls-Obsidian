import json

from src.enrich import mesh, mesh_cache

PM_A = b"""<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>1</PMID><MeshHeadingList>
<MeshHeading><DescriptorName UI="D000001" MajorTopicYN="Y">A</DescriptorName></MeshHeading>
</MeshHeadingList></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""
PM_B = b"""<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>2</PMID><MeshHeadingList>
<MeshHeading><DescriptorName UI="D000002" MajorTopicYN="N">B</DescriptorName></MeshHeading>
</MeshHeadingList></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def _l1(tmp_path, pmids):
    l1 = tmp_path / "l1"
    l1.mkdir(exist_ok=True)
    refs = [{"ids": {"pmid": p}} for p in pmids]
    (l1 / "article-1.json").write_text(json.dumps(
        {"id": "article-1", "kind": "live", "title": "Some Disease", "references": refs,
         "sections": [{"title": "Etiology", "blocks": []}]}), encoding="utf-8")
    return l1


def test_cache_round_trip_is_deterministic(tmp_path):
    pubmed = {"2": [("D000002", False)], "1": [("D000001", True)]}
    trees = {"D000002": ["C08.1"], "D000001": ["C14.1"]}
    a, b = tmp_path / "a.gz", tmp_path / "b.gz"
    mesh_cache.save_cache(a, pubmed, trees)
    mesh_cache.save_cache(b, pubmed, trees)
    assert a.read_bytes() == b.read_bytes()
    got_p, got_t = mesh_cache.load_cache(a)
    assert got_p == pubmed and got_t == trees
    assert mesh_cache.load_cache(tmp_path / "missing.gz") == ({}, {})


def test_fetch_skips_cached_pmids(tmp_path, monkeypatch):
    l1 = _l1(tmp_path, ["1", "2"])
    cache = tmp_path / "cache.json.gz"
    mesh_cache.save_cache(cache, {"1": [("D000001", True)]}, {"D000001": ["C14.1"]})
    calls = []

    def fake_get(endpoint, **params):
        calls.append((endpoint, params))
        if endpoint == "efetch.fcgi":
            return PM_B
        return json.dumps({"result": {"uids": ["68000002"], "68000002": {"ds_idxlinks": [{"treenum": "C08.1"}]}}}).encode()
    monkeypatch.setattr(mesh, "get", fake_get)
    raw = tmp_path / "raw"
    mesh.fetch(str(l1), str(raw), cache=cache)
    efetch = [p for e, p in calls if e == "efetch.fcgi"]
    assert len(efetch) == 1 and efetch[0]["id"] == "2"
    assert (raw / "pmx_2.xml").exists()
    pubmed, trees = mesh_cache.load_cache(cache)
    assert set(pubmed) == {"1", "2"} and trees["D000002"] == ["C08.1"] and trees["D000001"] == ["C14.1"]
    # a second run with everything cached makes no call
    monkeypatch.setattr(mesh, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    mesh.fetch(str(l1), str(raw), cache=cache)


def test_classify_same_with_cache_or_raw(tmp_path):
    l1 = _l1(tmp_path, ["1", "2"])
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "pm_000000.xml").write_bytes(PM_A)
    (raw / "pm_000001.xml").write_bytes(PM_B)
    (raw / "trees.json").write_text(json.dumps({"D000001": ["C14.1"], "D000002": ["C14.2"]}), encoding="utf-8")
    cache = tmp_path / "cache.json.gz"
    pubmed, trees = mesh_cache.cache_from_raw(raw)
    mesh_cache.save_cache(cache, pubmed, trees)
    ov = tmp_path / "ov"
    ov.mkdir()
    (ov / "system.yaml").write_text("{}\n", encoding="utf-8")
    mesh.classify(str(l1), str(raw), str(ov / "system.yaml"), str(tmp_path / "a.json"), str(tmp_path / "ra.json"))
    empty = tmp_path / "empty"
    mesh.classify(str(l1), str(empty), str(ov / "system.yaml"), str(tmp_path / "b.json"), str(tmp_path / "rb.json"), cache=cache)
    a = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    # source stamps differ only in date source; compare the rest
    for d in (a, b):
        for v in d.values():
            v.pop("source", None)
    assert a == b and a["article-1"]["shares"]
