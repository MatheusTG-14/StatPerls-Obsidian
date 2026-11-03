"""One-off migration: point Obsidian bookmarks at notes that moved folders (spec 4.7).

Not a build step: `.obsidian/` is not pipeline-owned. Run with Obsidian closed on this vault.
"""
import copy
import datetime
import shutil
import sys
from pathlib import Path

from src.common import read_json, write_json


def rewrite(bookmarks, moves):
    """moves: {old relpath: new relpath} under StatPearls/. Returns (new bookmarks, count)."""
    new = copy.deepcopy(bookmarks)
    n = 0

    def walk(items):
        nonlocal n
        for it in items:
            path = it.get("path", "")
            if path.startswith("StatPearls/") and path[11:] in moves:
                it["path"] = "StatPearls/" + moves[path[11:]]
                n += 1
            walk(it.get("items", []))
    walk(new.get("items", []))
    return new, n


def run(bookmarks_json, moves_json, backup_dir):
    sys.stdout.reconfigure(encoding="utf-8")
    bm = Path(bookmarks_json)
    if not bm.exists():
        print("no bookmarks file; nothing to do")
        return
    new, n = rewrite(read_json(bm), read_json(moves_json))
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bm, Path(backup_dir) / f"bookmarks-{stamp}.json")
    write_json(bm, new)
    print(f"bookmarks rewritten: {n}")
