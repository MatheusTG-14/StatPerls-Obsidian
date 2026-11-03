"""Sharded inverted index of article sections for the local Home plugin's content search (DEC-24).

Written under vault/StatPearls/_meta/search/ at build time; deterministic (rule 5). The plugin
(obsidian-plugin/src/content.ts) tokenizes queries with the same rules: tests on both sides read
obsidian-plugin/test/tokenize-cases.json.
"""
import json
import re
import unicodedata
from collections import Counter

STOPWORDS = frozenset(
    "a an and are as at be been being but by can for from has have in into is it its may no not of on or such "
    "than that the their then there these this those to was were which will with would also should".split())
GREEK = {"α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "κ": "kappa", "μ": "mu"}
_SPLIT = re.compile(r"[^a-z0-9]+")


def tokenize(text):
    # Greek map after NFKD so the micro sign (U+00B5, AltGr+M) becomes mu like U+03BC; drop every mark (category M).
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(GREEK.get(ch, ch) for ch in text if not unicodedata.category(ch).startswith("M"))
    return [t for t in _SPLIT.split(text) if len(t) > 1 and t not in STOPWORDS]


def shard_key(term):
    return term[:3].ljust(3, "_")


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def build_index(sections):
    """sections: [(stem, heading, plain_text)] in a fixed order -> {relative path: file text}."""
    docs, shards, total = [], {}, 0
    for doc, (stem, heading, text) in enumerate(sections):
        tokens = tokenize(text)
        docs.append([stem, heading, len(tokens)])
        total += len(tokens)
        for term, tf in sorted(Counter(tokens).items()):
            shards.setdefault(shard_key(term), {}).setdefault(term, []).append([doc, tf])
    out = {"meta.json": _dump({"n": len(docs), "avgdl": round(total / len(docs), 3) if docs else 0.0, "version": 1}),
           "docs.json": _dump(docs)}
    for key in sorted(shards):
        out[f"terms/k-{key}.json"] = _dump(shards[key])  # "k-": con/aux/nul/prn are Windows device names
    return out
