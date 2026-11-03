"""Article categories from reference MeSH votes plus frozen rules (spec 4.1-4.2, DEC-18)."""
import re
from collections import Counter
from pathlib import Path

import yaml

from src.common import read_schema

CATEGORIES = yaml.safe_load(read_schema("schema/vocab/system.yaml"))
ORDER = {c["slug"]: k for k, c in enumerate(CATEGORIES)}


def sub_slug(folder):
    return re.sub(r"[^a-z0-9]+", "-", folder.lower()).strip("-")


SUBCATEGORIES = {cat: [{"slug": sub_slug(f), "folder": f} for f in folders] for cat, folders in
                 yaml.safe_load(read_schema("schema/vocab/subsystem.yaml")).items()}
IGNORE_TREES = ("C12.100.937",)  # sexually transmitted diseases filed under male urogenital; they count via C01
_PREFIXES = sorted([(p, c["slug"]) for c in CATEGORIES for p in c["trees"]] + [(p, None) for p in IGNORE_TREES], key=lambda x: -len(x[0]))
CROSS_PRIORITY = ("oncology", "infectious")
CROSS_THRESHOLD = 0.30  # oncology / infectious take the folder at this share (DEC-18 tuning)
CROSS_THRESHOLD_DISEASE = 0.25  # lower for disease articles: cancers and infections are diseases
MIN_VOTING, MIN_TOP, MIN_LEAD, MIN_SECONDARY, MAX_SECONDARY = 5, 0.28, 0.03, 0.20, 3
# broad co-tags (one MeSH term often sits in these and in a specific organ branch): they lose near-ties
BROAD = ("nervous", "congenital-genetic", "immunology")
LIMB_REGIONS = {"shoulder-and-upper-limb", "bony-pelvis-and-lower-limb", "back"}


def category_of_tree(treenum):
    for p, slug in _PREFIXES:
        if treenum == p or treenum.startswith(p + "."):
            return slug
    return None


def vote(refs, trees):
    """refs: per reference, its (descriptor UI, major) pairs. Returns (shares, n_voting)."""
    total, n = Counter(), 0
    for ref in refs:
        w = {}
        for ui, major in ref:
            for t in trees.get(ui, []):
                c = category_of_tree(t)
                if c:
                    w[c] = max(w.get(c, 0), 2 if major else 1)
        if w:
            n += 1
            s = sum(w.values())
            for c, x in w.items():
                total[c] += x / s
    return {c: round(v / n, 4) for c, v in sorted(total.items(), key=lambda kv: ORDER[kv[0]])}, n


def _ranked(shares):
    return sorted(shares.items(), key=lambda kv: (-kv[1], ORDER[kv[0]]))


def assign(title, atype, region, shares, n_voting, override):
    """-> (primary, secondary, rule); rule in override|title|type|mesh-vote|fallback."""
    ranked = _ranked(shares)
    primary = rule = None
    if override:
        primary, rule = override, "override"
    elif title.startswith("Neuroanatomy,"):
        primary, rule = "nervous", "title"
    elif atype == "toxicology":
        primary, rule = "toxicology", "type"
    elif n_voting >= MIN_VOTING:
        th = CROSS_THRESHOLD_DISEASE if atype == "disease" else CROSS_THRESHOLD
        cross = [(c, s) for c, s in ranked if c in CROSS_PRIORITY and s >= th]
        if cross:
            primary, rule = cross[0][0], "mesh-vote"
        elif ranked and ranked[0][1] >= MIN_TOP:
            top = [c for c, x in ranked if ranked[0][1] - x < MIN_LEAD]
            if len(top) > 1:
                top = [c for c in top if c not in BROAD]
            if len(top) == 1:
                primary, rule = top[0], "mesh-vote"
    if primary is None:
        rule = "fallback"
        if region in LIMB_REGIONS:
            primary = "musculoskeletal"
        elif atype in ("anatomy", "basic-science"):
            primary = "basic-science"
        else:
            primary = "general"
    secondary = [c for c, s in ranked if c != primary and s >= MIN_SECONDARY][:MAX_SECONDARY]
    return primary, secondary, rule


def apply_agent(primary, secondary, rule, suggestion):
    """Agent suggestion (slug, confidence) replaces only a General fallback, and only at high or medium confidence."""
    if rule != "fallback" or primary != "general" or not suggestion:
        return primary, secondary, rule
    slug, conf = suggestion
    if slug == "general" or conf not in ("high", "medium"):
        return primary, secondary, rule
    return slug, [c for c in secondary if c != slug], "agent"


def pick_sub(article_id, primary, agent, user):
    """Subcategory for an article in `primary`: user override "cat/sub" > agent (same category, high/medium) > Other.
    agent: id -> (category, sub, confidence). Returns (sub slug, rule) or (None, None) without subcategories."""
    subs = SUBCATEGORIES.get(primary)
    if not subs:
        return None, None
    valid = {s["slug"] for s in subs}
    u = user.get(article_id, "")
    if u.startswith(primary + "/") and u.split("/", 1)[1] in valid:
        return u.split("/", 1)[1], "override"
    a = agent.get(article_id)
    if a and a[0] == primary and a[1] in valid and a[2] in ("high", "medium"):
        return a[1], "agent"
    return subs[-1]["slug"], "fallback"
