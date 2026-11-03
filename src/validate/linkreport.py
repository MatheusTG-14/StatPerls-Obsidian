"""Dry-run of Tier 1 linking over all live articles (no vault writes).

Reports density, most-linked targets (noise candidates) and a fixed random
sample of matches with context for hand-checking precision.
Usage (from sp.py): python -I sp.py linkreport
"""
import random
import sys
from collections import Counter
from pathlib import Path

from src.common import read_json, write_json
from src.extract.nxml import inline_text
from src.render.links import TitleIndex
from src.render.tags import anatomy_structure


def texts(rec):
    for s in rec["sections"]:
        for b in s["blocks"]:
            yield from _block(b)


def _block(b):
    if b["t"] == "p" and not b.get("bold_only"):
        yield inline_text([n for n in b["c"] if n["t"] not in ("link", "cite", "code")])
    elif b["t"] == "list":
        for item in b["items"]:
            for x in item:
                yield from _block(x)
    elif b["t"] == "table":
        for row in b["rows"]:
            for c in row:
                yield inline_text(c)


def report(l1_dir, out_json, sample=40):
    sys.stdout.reconfigure(encoding="utf-8")
    idx = read_json(Path(l1_dir).parent / "l1_index.json")
    live = {i for i, e in idx.items() if e["kind"] == "live"}
    entries = [(idx[i]["title"], i) for i in live]
    entries += [(st, i) for i in live if (st := anatomy_structure(idx[i]["title"])) and len(st.split()) >= 2]
    index = TitleIndex(entries)
    per_note, targets, contexts = Counter(), Counter(), []
    for i in sorted(live, key=lambda x: int(x.rsplit("-", 1)[1])):
        rec = read_json(Path(l1_dir) / f"{i}.json")
        seen = set()
        for t in texts(rec):
            for a, b, target in index.find(t):
                if target == i or target in seen:
                    continue
                seen.add(target)
                targets[target] += 1
                contexts.append((i, target, t[max(0, a - 60):b + 60], t[a:b]))
        per_note[i] = len(seen)
    rnd = random.Random(20261027)
    picks = rnd.sample(contexts, min(sample, len(contexts)))
    vals = sorted(per_note.values())
    res = {
        "notes": len(per_note),
        "links_total": sum(vals),
        "per_note_median": vals[len(vals) // 2],
        "per_note_p95": vals[int(len(vals) * 0.95)],
        "per_note_max": vals[-1],
        "zero_link_notes": sum(1 for v in vals if v == 0),
        "ambiguous_keys": len(index.ambiguous),
        "top_targets": [[idx[t]["title"], n] for t, n in targets.most_common(40)],
        "sample": [{"from": idx[a]["title"], "to": idx[b]["title"], "surface": s, "context": c} for a, b, c, s in picks],
    }
    write_json(out_json, res)
    print({k: v for k, v in res.items() if k not in ("top_targets", "sample")})
    print("top targets:", res["top_targets"][:40])
    for s in res["sample"]:
        print(f"- [{s['to']}] ...{s['context']}...")
