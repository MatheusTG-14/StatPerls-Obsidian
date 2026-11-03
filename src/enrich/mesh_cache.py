"""Compact reference-MeSH cache (PMID -> descriptor/major pairs, descriptor -> tree numbers).

Replaces the 3.6 GB of raw efetch XML for the portable installer (spec 3.1). Metadata only, no article text.
Deterministic bytes: sorted keys, compact separators, gzip mtime 0.
"""
import gzip
import json
from pathlib import Path


def load_cache(path):
    """-> (pubmed, trees); a missing file gives ({}, {})."""
    return _load(path)[:2]


def cache_date(path):
    """ISO date the reference data was fetched ('' if unknown)."""
    return _load(path)[2]


def _load(path):
    p = Path(path)
    if not p.exists():
        return {}, {}, ""
    with gzip.open(p, "rb") as fh:
        d = json.loads(fh.read().decode("utf-8"))
    pubmed = {k: [(u, bool(m)) for u, m in v] for k, v in d.get("pubmed", {}).items()}
    return pubmed, d.get("trees", {}), d.get("date", "")


def save_cache(path, pubmed, trees, date=""):
    body = {"pubmed": pubmed, "trees": trees}
    if date:
        body["date"] = date
    data = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
        gz.write(data)
    tmp.replace(p)


def cache_from_raw(raw_dir):
    """Reduce raw pm_*.xml + trees.json to cache dicts."""
    from src.common import read_json
    from src.enrich.mesh import _load_pubmed
    raw = Path(raw_dir)
    tf = raw / "trees.json"
    return _load_pubmed(raw), (read_json(tf) if tf.exists() else {})
