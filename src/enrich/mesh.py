"""Reference MeSH -> article categories (spec 4.3, DEC-18).

fetch: MeSH headings of every reference PMID (PubMed efetch, PMIDs only, rule 10)
       and tree numbers of every descriptor (MeSH esummary). Resumable.
classify: votes + rules -> L2 sidecar data/l2/system.json and a report.

Usage: python -I sp.py mesh | classify
"""
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

import yaml
from lxml import etree

from src import progress
from src.acquire.eutils import PARSER, get
from src.common import read_json, write_json
from src.enrich.system import CATEGORIES, apply_agent, assign, pick_sub, vote
from src.enrich.suggest import minimal_view
from src.enrich.tagging import apply_drug, apply_entry, fingerprint
from src.render.tags import anatomy_region, article_type

BATCH = 200


def parse_pubmed(xml):
    out = {}
    for a in etree.fromstring(xml, PARSER).iter("PubmedArticle"):
        pmid = a.findtext("MedlineCitation/PMID")
        pairs = []
        for h in a.iter("MeshHeading"):
            d = h.find("DescriptorName")
            if d is None:
                continue
            major = d.get("MajorTopicYN") == "Y" or any(q.get("MajorTopicYN") == "Y" for q in h.findall("QualifierName"))
            pairs.append((d.get("UI"), major))
        out[pmid] = pairs
    return out


def parse_mesh_summary(js):
    out = {}
    for uid in js["result"].get("uids", []):
        r = js["result"][uid]
        out["D" + uid[2:]] = [t["treenum"] for t in r.get("ds_idxlinks", []) if t.get("treenum")]
    return out


def _records(l1_dir):
    for p in sorted(Path(l1_dir).glob("*.json")):
        r = read_json(p)
        if r["kind"] in ("live", "nursing"):
            yield r


def _pmids(rec):
    return [x["ids"]["pmid"] for x in rec["references"] if x["ids"].get("pmid")]


def _load_pubmed(raw):
    m = {}
    for f in sorted(list(raw.glob("pm_*.xml")) + list(raw.glob("pmx_*.xml"))):
        m.update(parse_pubmed(f.read_bytes()))
    return m


def _lookup_trees(uis, trees, save):
    """Fetch tree numbers for descriptors not yet in `trees` (mutates it; save() after each batch)."""
    uis = sorted(set(uis) - set(trees))
    print("descriptors to look up", len(uis), flush=True)
    for start in range(0, len(uis), BATCH):
        ids = ",".join("68" + u[1:] for u in uis[start:start + BATCH])
        trees.update(parse_mesh_summary(json.loads(get("esummary.fcgi", db="mesh", id=ids, retmode="json"))))
        save()
    save()


def fetch(l1_dir, raw_dir, cache=None):
    sys.stdout.reconfigure(encoding="utf-8")
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    pmids = sorted({p for r in _records(l1_dir) for p in _pmids(r)}, key=int)
    print("reference pmids", len(pmids), flush=True)
    if cache is not None:
        from src.enrich.mesh_cache import cache_date, load_cache, save_cache
        pubmed, trees = load_cache(cache)
        date = cache_date(cache) or datetime.date.today().isoformat()

        def save():
            save_cache(cache, pubmed, trees, date)
        todo = [p for p in pmids if p not in pubmed]
        print("pmids not in cache", len(todo), flush=True)
        batches = -(-len(todo) // BATCH)
        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            out = raw / f"pmx_{chunk[0]}.xml"
            xml = get("efetch.fcgi", db="pubmed", id=",".join(chunk), retmode="xml")
            out.write_bytes(xml)
            pubmed.update(parse_pubmed(xml))
            for p in chunk:  # PMIDs PubMed did not return are remembered as empty
                pubmed.setdefault(p, [])
            save()
            print("saved", out.name, flush=True)
            progress.tick("reference", start // BATCH + 1, batches, "batches")
        if todo:
            date = datetime.date.today().isoformat()
        _lookup_trees({u for p in pmids for u, _ in pubmed.get(p, [])}, trees, save)
        return
    batches = -(-len(pmids) // BATCH)
    for start in range(0, len(pmids), BATCH):
        out = raw / f"pm_{start:06d}.xml"
        if not out.exists():
            out.write_bytes(get("efetch.fcgi", db="pubmed", id=",".join(pmids[start:start + BATCH]), retmode="xml"))
            print("saved", out.name, flush=True)
        progress.tick("reference", start // BATCH + 1, batches, "batches")
    tf = raw / "trees.json"
    trees = read_json(tf) if tf.exists() else {}
    _lookup_trees({u for pairs in _load_pubmed(raw).values() for u, _ in pairs}, trees,
                  lambda: write_json(tf, dict(sorted(trees.items()))))


def classify(l1_dir, raw_dir, overrides, out_json, report_json, cache=None):
    sys.stdout.reconfigure(encoding="utf-8")
    raw = Path(raw_dir)
    if cache is not None:
        from src.enrich.mesh_cache import cache_date, load_cache
        pubmed, trees = load_cache(cache)
        source = "pubmed-mesh:" + cache_date(cache)
    else:
        pubmed = _load_pubmed(raw)
        trees = read_json(raw / "trees.json")
        newest = max((f.stat().st_mtime for f in raw.glob("pm_*.xml")), default=0)
        source = "pubmed-mesh:" + datetime.date.fromtimestamp(newest).isoformat()
    over = yaml.safe_load(Path(overrides).read_text(encoding="utf-8")) or {}
    slugs = {c["slug"] for c in CATEGORIES}
    bad = {k: v for k, v in over.items() if v not in slugs}
    if bad:
        raise SystemExit(f"override slugs not in vocabulary: {bad}")
    agent_file = Path(overrides).with_name("system-agent.yaml")
    agent = {k: tuple(v) for k, v in (yaml.safe_load(agent_file.read_text(encoding="utf-8")) or {}).items()} if agent_file.exists() else {}
    tags_file = Path(overrides).with_name("tags-agent.yaml")
    tags = (yaml.safe_load(tags_file.read_text(encoding="utf-8")) or {}) if tags_file.exists() else {}
    drug_file = Path(overrides).with_name("drug-class-agent.yaml")
    drugs = (yaml.safe_load(drug_file.read_text(encoding="utf-8")) or {}) if drug_file.exists() else {}
    sub_agent_file = Path(overrides).with_name("subsystem-agent.yaml")
    sub_agent = {k: tuple(v) for k, v in (yaml.safe_load(sub_agent_file.read_text(encoding="utf-8")) or {}).items()} if sub_agent_file.exists() else {}
    sub_user_file = Path(overrides).with_name("subsystem.yaml")
    sub_user = (yaml.safe_load(sub_user_file.read_text(encoding="utf-8")) or {}) if sub_user_file.exists() else {}
    side, per_cat, per_rule, fallback = {}, Counter(), Counter(), []
    stale, untagged, auto_ids = Counter(), [], []
    total = sum(1 for _ in Path(l1_dir).glob("*.json"))
    for k, r in enumerate(_records(l1_dir), 1):
        progress.tick("classify", min(k, total), total, "articles")
        i, atype = r["id"], article_type(r)
        fp = fingerprint(minimal_view(r))  # every stored agent answer is valid only for this exact input (DEC-21)

        def fresh(entry, kind):
            if entry is None:
                return None
            if entry[-1] != fp:
                stale[kind] += 1
                return None
            return entry[:-1]
        shares, n = vote([pubmed.get(p, []) for p in _pmids(r)], trees)
        primary, secondary, rule = assign(r["title"], atype, anatomy_region(r["title"]), shares, n, over.get(i))
        primary, secondary, rule = apply_agent(primary, secondary, rule, fresh(agent.get(i), "system-agent"))
        if i in tags and tags[i].get("fp") != fp:
            stale["tags-agent"] += 1
        elif i not in tags:
            untagged.append(i)
        primary, secondary, rule, tag_sub, facets = apply_entry(primary, secondary, rule, tags.get(i), fp)
        if i in drugs and drugs[i].get("fp") != fp:
            stale["drug-class-agent"] += 1
        if apply_drug(drugs.get(i), fp):
            facets = {**facets, "drug-class": apply_drug(drugs[i], fp)}
        auto = i not in tags or tags[i].get("fp") != fp or (i in drugs and drugs[i].get("fp") != fp)
        if auto:  # no valid agent answer: deterministic heuristics, flagged (installer spec 3.4)
            from src.enrich.heuristics import drug_classes, facets_from_title
            facets = {**facets_from_title(r["title"]), **{k: v for k, v in facets.items() if k == "drug-class"}}
            if "drug-class" not in facets and atype == "drug" and drug_classes(r["title"]):
                facets["drug-class"] = drug_classes(r["title"])
            auto_ids.append(i)
        subs_here = {i: tag_sub} if tag_sub else ({i: fresh(sub_agent[i], "subsystem-agent")} if i in sub_agent and fresh(sub_agent[i], "x") else {})
        sub, sub_rule = pick_sub(i, primary, subs_here, sub_user)
        if primary == "basic-science" and sub_rule == "fallback" and atype == "anatomy":
            sub, sub_rule = "gross-anatomy", "type"
        side[i] = {"primary": primary, "secondary": secondary, "shares": shares, "n_voting": n, "rule": rule, "source": source,
                   "sub": sub, "sub_rule": sub_rule, "facets": facets}
        if auto:
            side[i]["auto"] = True
        per_cat[primary] += 1
        per_rule[rule] += 1
        if rule == "fallback":
            fallback.append([r["id"], r["title"]])
    progress.tick("classify", total, total, "articles")
    write_json(out_json, dict(sorted(side.items())))
    report = {"articles": len(side), "per_category": dict(per_cat.most_common()), "per_rule": dict(per_rule.most_common()),
              "stale_agent_answers": dict(stale), "needs_agent_pass": len(untagged), "auto_classified": auto_ids, "fallback": fallback, "needs_agent_pass_ids": untagged}
    write_json(report_json, report)
    shown = {k: v for k, v in report.items() if k not in ("fallback", "needs_agent_pass_ids", "auto_classified")}
    print(json.dumps({**shown, "auto_classified": len(auto_ids)}, indent=1))
