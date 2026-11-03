"""Extract every article in the archive to data/l1/<id>.json and report.

Each record gets nbk/pmid from the PubMed map (DEC-11). The fidelity check
compares whitespace-free body text against the XML for every article.
"""
import sys
from collections import Counter
from pathlib import Path

from src import progress
from src.common import no_ws, read_json, write_json
from src.extract.nxml import UnknownElement, body_text, extract, nbk_links, source_body_text


def run(extracted_dir, pubmed_map, out_dir, report_path):
    sys.stdout.reconfigure(encoding="utf-8")
    pm = read_json(pubmed_map)
    out_dir = Path(out_dir)
    stats, problems = Counter(), []
    index = {}
    files = [p for p in sorted(Path(extracted_dir).glob("*.nxml")) if p.name not in ("TOC.nxml", "contributors.nxml")]
    for k, p in enumerate(files, 1):
        progress.tick("read", k, len(files), "articles")
        try:
            rec = extract(p)
        except UnknownElement as e:
            problems.append({"file": p.name, "error": str(e)})
            stats["unknown_element"] += 1
            continue
        ids = pm.get(rec["id"], {})
        rec["nbk"], rec["pmid"] = ids.get("nbk"), ids.get("pmid")
        if not rec["nbk"]:
            problems.append({"file": p.name, "error": "no NBK in PubMed map"})
        if no_ws(body_text(rec)) != no_ws(source_body_text(p)):
            problems.append({"file": p.name, "error": "fidelity mismatch"})
            stats["fidelity_fail"] += 1
        stats[rec["kind"]] += 1
        stats["figures"] += len(rec["figures"])
        stats["references"] += len(rec["references"])
        stats["excluded_sections"] += len(rec["excluded"]["sections"])
        stats["promo_paragraphs"] += rec["excluded"]["promo_paragraphs"]
        write_json(out_dir / f"{rec['id']}.json", rec)
        index[rec["id"]] = {
            "kind": rec["kind"], "title": rec["title"], "nbk": rec["nbk"],
            "h2": [s["title"] for s in rec["sections"]],
            "fig_kinds": [f["kind"] for f in rec["figures"]],
            "fig_where": [f["where"] for f in rec["figures"]],
            "has_table": any(b["t"] == "table" for s in rec["sections"] for b in s["blocks"]),
            "has_code": any(b["t"] == "code" for s in rec["sections"] for b in s["blocks"]),
            "nbk_links": nbk_links(rec),
            "content_hash": rec["content_hash"],
        }
    write_json(out_dir.parent / "l1_index.json", index)
    report = {"stats": dict(sorted(stats.items())), "problems": problems}
    write_json(report_path, report)
    print(report["stats"], "problems:", len(problems))
