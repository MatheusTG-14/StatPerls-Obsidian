import json
from pathlib import Path

from src.render.search_index import build_index, shard_key, tokenize

CASES = json.loads((Path(__file__).parents[1] / "obsidian-plugin" / "test" / "tokenize-cases.json").read_text(encoding="utf-8"))
SECTIONS = [("A", "Intro", "heart failure heart"), ("B", "Treatment", "failure")]


def test_tokenize_matches_shared_cases():
    for c in CASES:
        assert tokenize(c["text"]) == c["tokens"], c["text"]


def test_shard_key_pads_short_terms():
    assert shard_key("heart") == "hea" and shard_key("mg") == "mg_"


def test_build_index_postings():
    out = build_index(SECTIONS)
    assert json.loads(out["docs.json"]) == [["A", "Intro", 3], ["B", "Treatment", 1]]
    assert json.loads(out["terms/k-hea.json"]) == {"heart": [[0, 2]]}
    assert json.loads(out["terms/k-fai.json"]) == {"failure": [[0, 1], [1, 1]]}
    assert json.loads(out["meta.json"]) == {"n": 2, "avgdl": 2.0, "version": 1}


def test_build_index_is_deterministic():
    assert build_index(SECTIONS) == build_index(list(SECTIONS))


def test_shard_files_avoid_windows_device_names():
    out = build_index([("A", "Intro", "consult auxiliary null prnewswire")])
    assert all(p.startswith("terms/k-") for p in out if p.startswith("terms/"))
