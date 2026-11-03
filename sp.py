"""Pipeline entry point. Run from the repo root: python -I sp.py <stage> ...

  extract                 archive NXML -> data/l1/*.json (+ data/l1_index.json, data/reports/extract.json)
  media                   archive images/videos -> data/media/ (once per archive refresh)
  build [--pilot|--all]   L1 -> vault/StatPearls (Obsidian closed, rule 8)
  validate                checks on vault/StatPearls
  linkreport              dry-run Tier 1 linking over all live articles (data/reports/links.json)
  mesh-cache              reduce data/raw/mesh to data/meta/mesh_cache.json.gz (used by mesh/classify when present)
  mesh                    reference MeSH from PubMed -> data/raw/mesh/ (PMIDs only; resumable)
  classify                votes + rules -> data/l2/system.json (+ data/reports/system.json)
  suggest-prepare N       minimized batches of General articles for agent classification (data/l2/agent/)
  suggest-collect MODEL   validate agent answers -> schema/overrides/system-agent.yaml
  subsuggest-prepare      minimized batches per large category for subcategory agents (data/l2/agent-sub/)
  subsuggest-collect M    validate subcategory answers -> schema/overrides/subsystem-agent.yaml
  tags-prepare [--followup]  minimized batches for the combined tagging pass (data/l2/agent-tags/); --followup:
                          only unchecked "Other" buckets + articles without an answer (data/l2/agent-tags-followup/)
  tags-collect MODEL [--followup]  validate tagging answers, merge into schema/overrides/tags-agent.yaml
  drugs-prepare           minimized batches of drug articles for drug-class agents (data/l2/agent-drugs/)
  drugs-collect MODEL     validate drug-class answers, merge into schema/overrides/drug-class-agent.yaml
  harvest                 record notes moved / `system` edited in Obsidian -> schema/overrides/system.yaml
  bundle OUT.pyz          write the portable installer (code, schema, state snapshots, Obsidian settings; no StatPearls text)
  bundle-exe OUT.exe SRC  write the compilable folder SRC for the Windows .exe, then compile it to OUT.exe (DEC-28)
  migrate-bookmarks       rewrite vault/.obsidian/bookmarks.json after notes move (Obsidian closed)
"""
import sys
from pathlib import Path

# -I implies -P: put the repo root (trusted code) on sys.path explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main(argv):
    from src.stages import run
    rc = run(argv)
    if rc is None:
        print(__doc__)
        sys.exit(2)
    sys.exit(rc)


if __name__ == "__main__":
    main(sys.argv[1:])
