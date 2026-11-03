"""Change report for install/update: new, changed, deleted articles, automatic placements, dangling Mine/ links."""
import re
from pathlib import Path

import yaml

from src.common import read_json, write_json
from src.render.names import fold
from src.validate.check import WIKILINK


def content_hashes(l1_index):
    """article id -> content hash of its canonical record (entries without one are skipped)."""
    return {i: e["content_hash"] for i, e in sorted(l1_index.items()) if e.get("content_hash")}


def content_hashes_from_l1(l1_dir):
    """Fallback for an index built before hashes were recorded: read them from the records."""
    return {p.stem: read_json(p)["content_hash"] for p in sorted(Path(l1_dir).glob("article-*.json"))}


def diff(old, new):
    return {
        "new": sorted(set(new) - set(old)),
        "changed": sorted(i for i in set(old) & set(new) if old[i] != new[i]),
        "deleted": sorted(set(old) - set(new)),
    }


def _aliases(path):
    head = path.read_text(encoding="utf-8")[:4000]
    if not head.startswith("---\n") or "\n---" not in head:
        return []
    try:
        fm = yaml.safe_load(head[4:head.index("\n---", 4)]) or {}
    except yaml.YAMLError:
        return []
    return [str(a) for a in fm.get("aliases") or []]


def dangling_mine_links(vault):
    """(Mine note path relative to the vault, link target) for wikilinks that no note, file or alias satisfies."""
    vault = Path(vault)
    mine = vault / "Mine"
    if not mine.exists():
        return []
    known = {fold(p.stem) for p in vault.rglob("*.md")}
    known |= {fold(p.name) for p in vault.rglob("*") if p.is_file() and p.suffix != ".md"}
    pending = []
    for p in sorted(mine.rglob("*.md")):
        for m in WIKILINK.finditer(p.read_text(encoding="utf-8")):
            target = m.group(1).strip()
            if fold(target) not in known and fold(Path(target).name) not in known:
                pending.append((p.relative_to(vault).as_posix(), target))
    if pending:  # aliases are only read when something looks missing (reading every note is slow)
        known_alias = set()
        for p in (vault / "StatPearls").rglob("*.md"):
            known_alias |= {fold(a) for a in _aliases(p)}
        pending = [x for x in pending if fold(x[1]) not in known_alias]
    return pending


def write_report(path, d, auto_ids, dangling, titles):
    rep = {
        "new": d["new"], "changed": d["changed"], "deleted": d["deleted"],
        "auto_classified": sorted(auto_ids),
        "dangling_mine_links": [list(x) for x in dangling],
        "titles": {i: titles[i] for i in sorted(set(d["new"]) | set(d["changed"]) | set(d["deleted"]) | set(auto_ids)) if i in titles},
    }
    write_json(path, rep)
    return rep


def summary_lines(rep):
    lines = []
    n, c, d, a = len(rep["new"]), len(rep["changed"]), len(rep["deleted"]), len(rep["auto_classified"])
    if n or c or d:
        lines.append(f"{n} new articles, {c} updated, {d} removed.")
    else:
        lines.append("No articles changed.")
    if a:
        lines.append(f"{a} placed automatically and tagged status/auto-classified (see the Auto-classified table in Obsidian).")
    dl = rep["dangling_mine_links"]
    if dl:
        lines.append(f"{len(dl)} links in your own notes now point to articles that no longer exist:")
        lines += [f"  {note} -> {target}" for note, target in dl[:10]]
        if len(dl) > 10:
            lines.append(f"  ... and {len(dl) - 10} more (full list in the report file).")
    return lines
