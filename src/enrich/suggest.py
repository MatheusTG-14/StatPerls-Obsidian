"""Agent category suggestions for articles the vote left in General (rules 6 and 10).

prepare: minimized batches (title, headings, introduction only) for agents to read.
collect: schema-check the agents' answers into schema/overrides/system-agent.yaml (tracked, with provenance).

Usage: python -I sp.py suggest-prepare <n_batches> | suggest-collect <model>
"""
import datetime
import json
import sys
from pathlib import Path

import yaml

from src.common import read_json, write_text
from src.enrich.system import CATEGORIES, SUBCATEGORIES
from src.extract.nxml import block_text

SKIP = {"Continuing Education Activity", "Review Questions"}
CONFIDENCE = ("high", "medium", "low")


def minimal_view(rec, max_chars=1500):
    secs = [s for s in rec["sections"] if s["title"] not in SKIP]
    intro = " ".join(block_text(b) for b in secs[0]["blocks"]) if secs else ""
    return {"id": rec["id"], "title": rec["title"], "headings": [s["title"] for s in secs], "intro": intro[:max_chars]}


def parse_answers(text, batch_ids, slugs=None):
    """-> ({id: (slug, confidence)}, [error lines]). Only known ids, vocabulary slugs, known confidence levels."""
    slugs = slugs or {c["slug"] for c in CATEGORIES}
    ok, errors = {}, []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            a = json.loads(line)
            i, c, conf = a["id"], a["category"], a["confidence"]
        except (ValueError, KeyError, TypeError):
            errors.append(line[:80])
            continue
        if i not in batch_ids or c not in slugs or conf not in CONFIDENCE:
            errors.append(line[:80])
            continue
        ok[i] = (c, conf)
    return ok, errors


def prepare(l2_json, l1_dir, out_dir, n_batches):
    sys.stdout.reconfigure(encoding="utf-8")
    side = read_json(l2_json)
    ids = sorted(i for i, e in side.items() if e["primary"] == "general" and e["rule"] == "fallback")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for k in range(n_batches):
        part = ids[k::n_batches]
        lines = [json.dumps(minimal_view(read_json(Path(l1_dir) / f"{i}.json")), ensure_ascii=False) for i in part]
        write_text(out / f"batch_{k:02d}.jsonl", "\n".join(lines) + "\n")
    print(f"{len(ids)} articles in {n_batches} batches -> {out}")


def collect(batch_dir, out_yaml, model):
    sys.stdout.reconfigure(encoding="utf-8")
    d = Path(batch_dir)
    found, errors, missing = {}, [], []
    for b in sorted(d.glob("batch_*.jsonl")):
        ids = {json.loads(x)["id"] for x in b.read_text(encoding="utf-8").splitlines() if x.strip()}
        ans = d / b.name.replace("batch_", "answers_")
        ok, err = parse_answers(ans.read_text(encoding="utf-8") if ans.exists() else "", ids)
        found.update(ok)
        errors += err
        missing += sorted(ids - set(ok))
    head = (f"# Agent category suggestions (DEC-19): model {model}, {datetime.date.today().isoformat()}.\n"
            "# Input per article: title, headings, introduction (rule 10). Applied only where the vote fell back.\n"
            "# User overrides in system.yaml always win. Format: article_id: [category, confidence]\n")
    body = yaml.safe_dump({i: list(v) for i, v in sorted(found.items())}, default_flow_style=None, sort_keys=False, allow_unicode=True)
    write_text(out_yaml, head + body)
    print(f"valid {len(found)}  invalid lines {len(errors)}  missing {len(missing)}")
    return missing


SUB_INSTRUCTIONS = """You are sorting medical study articles of the category "{folder}" into its subcategories.
Work only with your batch file. Do not read any other file, search, browse the web, or run commands.

Each batch line is JSON: {{"id", "title", "headings", "intro"}}. Read the whole batch with the Read tool in
chunks of 40 lines (offset 1, 41, 81, ...) until every line is seen. Then write the answers file with the Write
tool: exactly one line per input article, in input order, each exactly
{{"id": "<id>", "category": "<subcategory slug>", "confidence": "high|medium|low"}}
No other text, no markdown fences. Every input id exactly once; never invent ids.

SUBCATEGORIES (use the slug exactly):
{subs}

RULES: pick the ONE subcategory a specialist would file the article under. Drug monographs go to the
pharmacology subcategory when one exists, unless a disease-specific subcategory clearly owns the drug.
Anatomy, histology and physiology articles go to the anatomy/physiology subcategory when one exists, else to the
body-region subcategory. Use the "other-..." slug only when nothing fits. confidence: high = obvious,
medium = plausible alternative exists, low = guess. When done, reply with one line: the number of lines written.
"""


def prepare_sub(l2_json, l1_dir, out_dir, per_batch=200):
    sys.stdout.reconfigure(encoding="utf-8")
    side = read_json(l2_json)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    folder = {c["slug"]: c["folder"] for c in CATEGORIES}
    for cat, subs in SUBCATEGORIES.items():
        ids = sorted(i for i, e in side.items() if e["primary"] == cat)
        n = max(1, -(-len(ids) // per_batch))
        write_text(out / f"INSTRUCTIONS_{cat}.md", SUB_INSTRUCTIONS.format(
            folder=folder[cat], subs="\n".join(f"- {x['slug']}  ({x['folder']})" for x in subs)))
        for k in range(n):
            part = ids[k::n]
            lines = [json.dumps(minimal_view(read_json(Path(l1_dir) / f"{i}.json")), ensure_ascii=False) for i in part]
            write_text(out / f"{cat}__{k:02d}.jsonl", "\n".join(lines) + "\n")
        print(f"{cat}: {len(ids)} articles in {n} batches")


def collect_sub(batch_dir, out_yaml, model):
    sys.stdout.reconfigure(encoding="utf-8")
    d = Path(batch_dir)
    found, errors, missing = {}, [], []
    for b in sorted(d.glob("*__*.jsonl")):
        if b.name.endswith(".answers.jsonl"):
            continue
        cat = b.name.split("__")[0]
        ids = {json.loads(x)["id"] for x in b.read_text(encoding="utf-8").splitlines() if x.strip()}
        ans = b.with_name(b.stem + ".answers.jsonl")
        ok, err = parse_answers(ans.read_text(encoding="utf-8") if ans.exists() else "", ids, {x["slug"] for x in SUBCATEGORIES[cat]})
        found.update({i: (cat, sub, conf) for i, (sub, conf) in ok.items()})
        errors += err
        missing += sorted(ids - set(ok))
    head = (f"# Agent subcategory assignments (DEC-20): model {model}, {datetime.date.today().isoformat()}.\n"
            "# Input per article: title, headings, introduction (rule 10). Applies only while the article's category matches.\n"
            "# Format: article_id: [category, subcategory, confidence]\n")
    body = yaml.safe_dump({i: list(v) for i, v in sorted(found.items())}, default_flow_style=None, sort_keys=False, allow_unicode=True)
    write_text(out_yaml, head + body)
    print(f"valid {len(found)}  invalid lines {len(errors)}  missing {len(missing)}")
    return missing
