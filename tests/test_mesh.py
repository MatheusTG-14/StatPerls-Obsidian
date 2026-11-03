import json

import pytest

from src.enrich import mesh

PUBMED = b"""<PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>111</PMID><MeshHeadingList>
<MeshHeading><DescriptorName UI="D1" MajorTopicYN="N">A</DescriptorName><QualifierName UI="Q1" MajorTopicYN="Y">q</QualifierName></MeshHeading>
<MeshHeading><DescriptorName UI="D2" MajorTopicYN="N">B</DescriptorName></MeshHeading>
</MeshHeadingList></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation><PMID>222</PMID></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


def test_parse_pubmed():
    assert mesh.parse_pubmed(PUBMED) == {"111": [("D1", True), ("D2", False)], "222": []}


def test_parse_mesh_summary():
    js = {"result": {"uids": ["68003920"], "68003920": {"ds_idxlinks": [{"treenum": "C19.246"}, {"treenum": ""}]}}}
    assert mesh.parse_mesh_summary(js) == {"D003920": ["C19.246"]}


def test_fetch_skips_existing_batches(tmp_path, monkeypatch):
    l1 = tmp_path / "l1"
    l1.mkdir()
    (l1 / "article-1.json").write_text(json.dumps({"id": "article-1", "kind": "live", "references": [{"ids": {"pmid": "111"}}]}), encoding="utf-8")
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "pm_000000.xml").write_bytes(PUBMED)
    (raw / "trees.json").write_text(json.dumps({"D1": ["C14.1"], "D2": []}), encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("network call")
    monkeypatch.setattr(mesh, "get", boom)
    mesh.fetch(str(l1), str(raw))
