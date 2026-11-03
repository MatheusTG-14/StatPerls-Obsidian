"""Harvest the user's category changes made in Obsidian into schema/overrides/system.yaml (DEC-19).

A change is a note dragged into another category folder, or an edited `system` property
(the property wins when both differ). Run before `build`; build refuses while changes are pending.

Usage: python -I sp.py harvest
"""
import datetime
import re
import sys
from pathlib import Path

import yaml

from src.common import write_text
from src.enrich.system import CATEGORIES

BY_FOLDER = {c["folder"]: c["slug"] for c in CATEGORIES}
SLUGS = {c["slug"] for c in CATEGORIES}


def _prop(path, key="system", valid=SLUGS):
    with open(path, encoding="utf-8") as fh:
        text = fh.read(8192)  # frontmatter only
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        return None
    fm = yaml.safe_load(text[4:text.index("\n---", 4)]) or {}
    v = fm.get(key)
    return v if v in valid else None


def user_changes(root, stems, current, since=None):
    """root: vault/StatPearls; stems: id -> stem (live articles); current: id -> assigned slug. -> {id: new slug}.
    since: only notes modified after this timestamp can carry an edited property (skips reading the rest)."""
    where = {p.stem: p for p in (Path(root) / "Articles").rglob("*.md")}
    out = {}
    for i, stem in sorted(stems.items()):
        p = where.get(stem)
        if p is None:
            continue
        prop = _prop(p) if since is None or p.stat().st_mtime > since else None
        folder = BY_FOLDER.get(p.relative_to(Path(root) / "Articles").parts[0])
        new = prop if prop and prop != current[i] else folder if folder and folder != current[i] else None
        if new:
            out[i] = new
    return out


def sub_changes(root, stems, built, since=None):
    """Edited `subsystem` properties since the last build. built: stem -> "cat/sub" as last rendered. -> {id: "cat/sub"}."""
    from src.enrich.system import SUBCATEGORIES
    where = {p.stem: p for p in (Path(root) / "Articles").rglob("*.md")}
    out = {}
    for i, stem in sorted(stems.items()):
        p, was = where.get(stem), built.get(stem)
        if p is None or not was or (since is not None and p.stat().st_mtime <= since):
            continue
        cat, sub = was.split("/", 1)
        prop = _prop(p, "subsystem", {x["slug"] for x in SUBCATEGORIES.get(cat, [])})
        if prop and prop != sub:
            out[i] = f"{cat}/{prop}"
    return out


def pending_changes(root, stems, pinned, built, since, recorded=None, recorded_subs=None):
    """Category and subcategory changes the user made since the last build (pinned = categories as last built).
    recorded / recorded_subs: {id: slug} / {id: "cat/sub"} already harvested into system.yaml / subsystem.yaml
    (compared separately: an id may be in both files); those are not pending any more."""
    cats = user_changes(root, {i: s for i, s in stems.items() if i in pinned}, pinned, since)
    subs = sub_changes(root, {i: s for i, s in stems.items() if i not in cats}, built, since)
    return {**{i: v for i, v in cats.items() if (recorded or {}).get(i) != v},
            **{i: v for i, v in subs.items() if (recorded_subs or {}).get(i) != v}}


def merge_overrides(path, changes, titles, date):
    """Add or replace `article-id: slug   # Title (user, date)` lines; keep the header comments and other lines."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    head = [x for x in lines if x.startswith("#") or not x.strip()]
    entries = {x.split(":", 1)[0]: x for x in lines if re.match(r"^[\w-]+:", x) and not x.startswith("{")}
    for i, slug in changes.items():
        entries[i] = f"{i}: {slug}   # {titles.get(i, '')} (user, {date})"
    write_text(path, "\n".join(head + [entries[k] for k in sorted(entries)]) + "\n")


def run(vault, registry_json, l1_index, overrides):
    sys.stdout.reconfigure(encoding="utf-8")
    from src.common import read_json
    reg = read_json(registry_json)
    idx = read_json(l1_index)
    live = {i: s for i, s in reg["articles"].items() if idx.get(i, {}).get("kind") == "live"}
    current = reg.get("system", {})
    stems = {i: s for i, s in live.items() if i in current}
    manifest = Path(vault) / "StatPearls" / "_meta" / "build-manifest.json"
    changes = user_changes(Path(vault) / "StatPearls", stems, current, manifest.stat().st_mtime if manifest.exists() else None)
    today = datetime.date.today().isoformat()
    if changes:
        merge_overrides(overrides, changes, {i: idx[i]["title"] for i in changes}, today)
    built = read_json(manifest).get("subs", {}) if manifest.exists() else {}
    subs = sub_changes(Path(vault) / "StatPearls", {i: s for i, s in live.items() if i not in changes}, built,
                       manifest.stat().st_mtime if manifest.exists() else None)
    sub_file = Path(overrides).with_name("subsystem.yaml")
    if subs:
        merge_overrides(sub_file, subs, {i: idx[i]["title"] for i in subs}, today)
    print(f"harvested {len(changes)} category changes -> {overrides}; {len(subs)} subcategory changes -> {sub_file}")
    return changes
