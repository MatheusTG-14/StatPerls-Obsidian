"""Combined agent tagging pass (DEC-21): subcategory where missing, re-check of "Other" buckets, facet tags.

Every answer is stored in the tracked file schema/overrides/tags-agent.yaml with the fingerprint of the exact
minimized input the agent saw, so classify/build reproduce the vault without any agent (spec 2026-11-02 section 6).

Usage: python -I sp.py tags-prepare | tags-collect MODEL
"""
import datetime
import hashlib
import json
import sys
from pathlib import Path

import yaml

from src.common import read_json, read_schema, write_text
from src.enrich.suggest import minimal_view
from src.enrich.system import CATEGORIES, SUBCATEGORIES

FACETS = yaml.safe_load(read_schema("schema/vocab/facets.yaml"))
FACET_KEYS = ("population", "setting", "discipline", "pathogen")
DRUG_VOCAB = yaml.safe_load(read_schema("schema/vocab/drug-classes.yaml"))
DRUG_CLASSES = [d["slug"] for d in DRUG_VOCAB]  # DEC-23
MAB = "monoclonal-antibodies"
DONE_BEFORE = ("cardiovascular", "nervous", "musculoskeletal", "infectious", "oncology", "endocrine-metabolic")  # DEC-20
SPLIT = "neuroanatomy-and-neurophysiology"  # replaced by three subcategories (DEC-21)
CONF = ("high", "medium", "low")


def fingerprint(view):
    return hashlib.sha256(json.dumps(view, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def task_of(primary, sub):
    """recheck: an "Other" bucket (category may be wrong); sub: subcategory still needed; facets: only facet tags."""
    if sub and sub.startswith("other-") and primary in DONE_BEFORE:
        return "recheck"
    if primary not in DONE_BEFORE or sub in (None, SPLIT):
        return "sub"
    return "facets"


def followup_task(primary, sub, entry):
    """Follow-up pass: recheck every "Other" bucket not rechecked yet; full task for articles without a valid answer."""
    if sub and sub.startswith("other-") and (entry or {}).get("task") != "recheck":
        return "recheck"
    if entry is None:
        return task_of(primary, sub)
    return None


def parse_tag_answers(text, tasks, cat):
    """tasks: id -> task in this batch; cat: the batch's category (unused for recheck). -> ({id: entry}, [errors])."""
    cats = {c["slug"] for c in CATEGORIES}
    ok, errors = {}, []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            a = json.loads(line)
            i = a["id"]
            task = tasks[i]
            facets = {k: list(a[k]) for k in FACET_KEYS}
        except (ValueError, KeyError, TypeError):
            errors.append(line[:80])
            continue
        if any(v not in FACETS[k] for k in FACET_KEYS for v in facets[k]):
            errors.append(line[:80])
            continue
        entry = {}
        if task in ("sub", "recheck"):
            c = a.get("category") if task == "recheck" else cat
            subs = {s["slug"] for s in SUBCATEGORIES.get(c, [])}
            if c not in cats or a.get("sub") not in subs or a.get("sub_conf") not in CONF:
                errors.append(line[:80])
                continue
            entry = {"cat": c, "sub": a["sub"], "sub_conf": a["sub_conf"]}
        ok[i] = {**entry, **facets}
    return ok, errors


def _facet_text():
    out = []
    for k in FACET_KEYS:
        out.append(f"- {k}: " + ", ".join(FACETS[k]))
    return "\n".join(out)


HEAD = """You are tagging medical study articles. Work only with your batch file. Do not read any other file, search,
browse the web, or run commands. Each batch line is JSON: {{"id", "title", "headings", "intro", "fp"}}. Read the whole
batch with the Read tool in chunks of 40 lines (offset 1, 41, 81, ...) until every line is seen. Then write the
answers file with the Write tool: exactly one JSON line per input article, in input order, no other text, no fences.
Every input id exactly once; never invent ids.

FACETS (lists; use only these exact values; an empty list is normal):
{facets}
Add a facet value only when the article is ABOUT it (for example an article on pediatric asthma gets
population "pediatric"; an adult article that mentions children once gets nothing). pathogen only for
articles about an infection or an anti-infective drug.
"""

SUB_TASK = """
TASK: choose the ONE subcategory of the category "{folder}" a specialist would file the article under, with
confidence high (obvious), medium (plausible alternative) or low (guess); use the "other-..." slug only when
nothing fits. Answer line:
{{"id": "<id>", "sub": "<slug>", "sub_conf": "high|medium|low", "population": [], "setting": [], "discipline": [], "pathogen": []}}

SUBCATEGORIES of {folder}:
{subs}
"""

RECHECK_TASK = """
TASK: these articles were filed under a broad category's "Other" bucket, and some are in the WRONG category.
Choose the category AND subcategory a specialist would file each one under, from the full list below (the
subcategory must belong to the chosen category). Confidence high (obvious), medium (plausible alternative) or
low (guess); use an "other-..." slug only when nothing fits. Answer line:
{{"id": "<id>", "category": "<category slug>", "sub": "<subcategory slug>", "sub_conf": "high|medium|low", "population": [], "setting": [], "discipline": [], "pathogen": []}}

CATEGORIES AND SUBCATEGORIES:
{full}
"""

FACETS_TASK = """
TASK: facet tags only. Answer line:
{"id": "<id>", "population": [], "setting": [], "discipline": [], "pathogen": []}
"""


def _subs(cat):
    return "\n".join(f"- {s['slug']}  ({s['folder']})" for s in SUBCATEGORIES[cat])


def prepare_tags(l2_json, l1_dir, out_dir, per_batch=200, followup_yaml=None, only=None):
    """followup_yaml: the existing answers file; only articles followup_task selects get batched.
    only: restrict to these article ids (flagged articles): the full task_of task for each, stale answers ignored."""
    sys.stdout.reconfigure(encoding="utf-8")
    side = read_json(l2_json)
    known = yaml.safe_load(Path(followup_yaml).read_text(encoding="utf-8")) if followup_yaml else None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    folder = {c["slug"]: c["folder"] for c in CATEGORIES}
    groups = {}
    for i, e in sorted(side.items()):
        if only is not None and i not in only:
            continue
        t = followup_task(e["primary"], e.get("sub"), known.get(i)) if known is not None and only is None else task_of(e["primary"], e.get("sub"))
        if t is None:
            continue
        groups.setdefault((t, e["primary"] if t == "sub" else "all"), []).append(i)
    head = HEAD.format(facets=_facet_text())
    full = "\n".join(f"{c['slug']}  ({c['folder']})\n" + "\n".join(f"    - {s['slug']}" for s in SUBCATEGORIES[c["slug"]]) for c in CATEGORIES)
    write_text(out / "INSTRUCTIONS_recheck.md", head + RECHECK_TASK.format(full=full))
    write_text(out / "INSTRUCTIONS_facets.md", head + FACETS_TASK)
    n_batches = 0
    for (task, cat), ids in sorted(groups.items()):
        if task == "sub":
            write_text(out / f"INSTRUCTIONS_sub_{cat}.md", head + SUB_TASK.format(folder=folder[cat], subs=_subs(cat)))
        n = max(1, -(-len(ids) // per_batch))
        for k in range(n):
            lines = []
            for i in ids[k::n]:
                v = minimal_view(read_json(Path(l1_dir) / f"{i}.json"))
                lines.append(json.dumps({**v, "fp": fingerprint(v)}, ensure_ascii=False))
            write_text(out / f"{task}__{cat}__{k:02d}.jsonl", "\n".join(lines) + "\n")
            n_batches += 1
        print(f"{task:8} {cat:20} {len(ids):5} articles, {n} batches")
    print(f"total batches {n_batches}")


def collect_tags(batch_dir, out_yaml, model):
    sys.stdout.reconfigure(encoding="utf-8")
    d = Path(batch_dir)
    found, errors, missing = {}, [], []
    for b in sorted(d.glob("*__*__*.jsonl")):
        if b.name.endswith(".answers.jsonl"):
            continue
        task, cat, _ = b.stem.split("__")
        rows = [json.loads(x) for x in b.read_text(encoding="utf-8").splitlines() if x.strip()]
        fps = {r["id"]: r["fp"] for r in rows}
        ans = b.with_name(b.stem + ".answers.jsonl")
        ok, err = parse_tag_answers(ans.read_text(encoding="utf-8") if ans.exists() else "", {i: task for i in fps}, cat)
        found.update({i: {"fp": fps[i], "task": task, **v} for i, v in ok.items()})
        errors += err
        missing += sorted(set(fps) - set(ok))
    _merge_write(out_yaml, found, model, "# Agent tags (DEC-21). Input: title, headings, introduction (rule 10).\n"
                 "# fp = sha256[:12] of the exact input; an entry whose fp no longer matches the article is ignored (stale).\n"
                 "# task: sub | recheck (may change the category) | facets. Only high/medium sub_conf is applied.\n")
    return _report(found, errors, missing)


def _merge_write(out_yaml, found, model, default_head):
    """New answers replace old ones for the same article; every other stored entry is kept."""
    out_yaml = Path(out_yaml)
    old_text = out_yaml.read_text(encoding="utf-8") if out_yaml.exists() else ""
    merged = {**(yaml.safe_load(old_text) or {}), **found}
    head = "".join(x + "\n" for x in old_text.splitlines() if x.startswith("#")) or default_head
    head += f"# Pass: model {model}, {datetime.date.today().isoformat()}, {len(found)} entries written.\n"
    body = yaml.safe_dump(dict(sorted(merged.items())), default_flow_style=None, sort_keys=False, allow_unicode=True, width=200)
    write_text(out_yaml, head + body)


def _report(found, errors, missing):
    print(f"valid {len(found)}  invalid lines {len(errors)}  missing {len(missing)}")
    for e in errors[:10]:
        print("  invalid:", e)
    return missing


# ---------- drug classes (DEC-23) ----------

def parse_drug_answers(text, ids):
    """-> ({id: {"drug_class", "conf"}}, [errors]). One or two classes from the vocabulary, plus monoclonal-antibodies."""
    vocab = set(DRUG_CLASSES)
    ok, errors = {}, []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            a = json.loads(line)
            i, classes, conf = a["id"], list(a["drug_class"]), a["conf"]
        except (ValueError, KeyError, TypeError):
            errors.append(line[:80])
            continue
        main = [c for c in classes if c != MAB]
        if (i not in ids or conf not in CONF or not classes or len(set(classes)) != len(classes)
                or any(c not in vocab for c in classes) or len(main) > 2):
            errors.append(line[:80])
            continue
        ok[i] = {"drug_class": classes, "conf": conf}
    return ok, errors


def apply_drug(entry, fp):
    """Stored drug-class answer -> sorted classes; stale (fp mismatch) or low confidence -> []."""
    if not entry or entry.get("fp") != fp or entry.get("conf") not in ("high", "medium"):
        return []
    return sorted(entry["drug_class"])


DRUG_HEAD = """You are classifying drug articles from a medical reference into drug classes. Work only with your batch file.
Do not read any other file, search, browse the web, or run commands. Each batch line is JSON: {{"id", "title",
"headings", "intro", "fp"}}. Read the whole batch with the Read tool in chunks of 40 lines (offset 1, 41, 81, ...)
until every line is seen. Then write the answers file with the Write tool: exactly one JSON line per input article,
in input order, no other text, no fences. Every input id exactly once; never invent ids.

TASK: give the ONE drug class a pharmacology teacher would file the article under; add a SECOND class only when the
drug genuinely belongs to two (for example valproic acid: antiseizure and mood-stabilizers). Every monoclonal
antibody (name ending in -mab) also gets "monoclonal-antibodies" in addition to its class. Articles about a whole
class get that class. Confidence high (obvious), medium (plausible alternative) or low (guess). Answer line:
{{"id": "<id>", "drug_class": ["<slug>"], "conf": "high|medium|low"}}

DRUG CLASSES (slug: what it includes; use only these slugs):
{classes}
"""


def prepare_drugs(l1_dir, out_dir, per_batch=90, only=None):
    from src.render.tags import article_type
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for p in sorted(Path(l1_dir).glob("*.json")):
        r = read_json(p)
        if r["kind"] in ("live", "nursing") and article_type(r) == "drug" and (only is None or r["id"] in only):
            v = minimal_view(r)
            lines.append(json.dumps({**v, "fp": fingerprint(v)}, ensure_ascii=False))
    classes = "\n".join(f"- {d['slug']}: {d['includes']}" for d in DRUG_VOCAB)
    write_text(out / "INSTRUCTIONS_drugs.md", DRUG_HEAD.format(classes=classes))
    n = max(1, -(-len(lines) // per_batch))
    for k in range(n):
        write_text(out / f"drugs__all__{k:02d}.jsonl", "\n".join(lines[k::n]) + "\n")
    print(f"{len(lines)} drug articles, {n} batches")


def collect_drugs(batch_dir, out_yaml, model):
    sys.stdout.reconfigure(encoding="utf-8")
    found, errors, missing = {}, [], []
    for b in sorted(Path(batch_dir).glob("drugs__*.jsonl")):
        if b.name.endswith(".answers.jsonl"):
            continue
        rows = [json.loads(x) for x in b.read_text(encoding="utf-8").splitlines() if x.strip()]
        fps = {r["id"]: r["fp"] for r in rows}
        ans = b.with_name(b.stem + ".answers.jsonl")
        ok, err = parse_drug_answers(ans.read_text(encoding="utf-8") if ans.exists() else "", set(fps))
        found.update({i: {"fp": fps[i], **v} for i, v in ok.items()})
        errors += err
        missing += sorted(set(fps) - set(ok))
    _merge_write(out_yaml, found, model, "# Agent drug classes (DEC-23). Input: title, headings, introduction (rule 10).\n"
                 "# fp = sha256[:12] of the exact input; stale entries are ignored. Only high/medium conf is applied.\n")
    return _report(found, errors, missing)


def apply_entry(primary, secondary, rule, entry, fp):
    """One stored tagging answer -> (primary, secondary, rule, (cat, sub, conf) or None, facets). Stale (fp mismatch) = ignored."""
    if not entry or entry.get("fp") != fp:
        return primary, secondary, rule, None, {}
    facets = {k: entry[k] for k in FACET_KEYS if entry.get(k)}
    if entry.get("task") not in ("sub", "recheck") or entry.get("sub_conf") not in ("high", "medium"):
        return primary, secondary, rule, None, facets
    if entry["task"] == "recheck" and rule != "override" and entry["cat"] != primary:
        secondary = ([primary] + [c for c in secondary if c not in (primary, entry["cat"])])[:3]
        primary, rule = entry["cat"], "agent-recheck"
    sub = (entry["cat"], entry["sub"], entry["sub_conf"]) if entry["cat"] == primary else None
    return primary, secondary, rule, sub, facets
