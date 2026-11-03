"""Deterministic placement heuristics for articles without a valid agent answer (installer spec 3.4).

Code only, no LLM. Drug classes come from an ordered suffix table; facets from title cues.
Vocabulary membership is checked, so the heuristics can never invent a tag (rule 6).
"""
import re
from pathlib import Path

import yaml

from src.common import read_schema
from src.enrich.tagging import DRUG_CLASSES, FACETS

RULES_PATH = "schema/vocab/drug-class-rules.yaml"

# (regex on the title, family, value)
FACET_CUES = [
    (r"\b(pediatric|paediatric|child|children|infant)", "population", "pediatric"),
    (r"\b(neonatal|newborn)", "population", "neonatal"),
    (r"\b(pregnancy|obstetric)", "population", "pregnancy"),
    (r"\b(geriatric|elderly)", "population", "geriatric"),
    (r"\bemergency\b", "setting", "emergency"),
    (r"\bEMS\b", "setting", "prehospital"),
    (r"\(Nursing\)", "discipline", "nursing"),
]


def load_rules(path=RULES_PATH):
    p = Path(path)
    rules = yaml.safe_load(p.read_text(encoding="utf-8") if p.is_absolute() else read_schema(path)) or []
    out = []
    for r in rules:
        if r["class"] not in DRUG_CLASSES:
            raise ValueError(f"drug-class rule uses unknown class: {r['class']}")
        out.append((re.compile(r["pattern"], re.I), r["class"]))
    return out


_RULES = None


def drug_classes(title):
    global _RULES
    if _RULES is None:
        _RULES = load_rules()
    for rx, cls in _RULES:
        if rx.search(title):
            return [cls]
    return []


def facets_from_title(title):
    out = {}
    for pattern, family, value in FACET_CUES:
        assert value in FACETS[family], value
        flags = 0 if pattern in (r"\bEMS\b", r"\(Nursing\)") else re.I
        if re.search(pattern, title, flags) and value not in out.get(family, []):
            out.setdefault(family, []).append(value)
    return out
