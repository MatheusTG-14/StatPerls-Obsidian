"""Pipeline stages, runnable with any install folder as working directory (used by sp.py and the installer)."""
import contextlib
import os
import sys
from pathlib import Path

RAW = "data/raw/extracted/statpearls_NBK430685"
TAR = "data/raw/archive/statpearls_NBK430685.tar.gz"
PUBMED = "data/meta/pubmed_map.json"
MESH_CACHE = "data/meta/mesh_cache.json.gz"
L1 = "data/l1"


def _run(argv):
    stage = argv[0] if argv else ""
    if stage == "extract":
        from src.extract.run import run
        run(RAW, PUBMED, L1, "data/reports/extract.json")
    elif stage == "media":
        from src.acquire.media import unpack
        unpack(TAR, "data/media", "data/meta/media_members.json", "data/registry.json")
    elif stage == "build":
        from src.render.build import build
        build(L1, "vault", mode=argv[1].lstrip("-") if len(argv) > 1 else "pilot")
    elif stage == "linkreport":
        from src.validate.linkreport import report
        report(L1, "data/reports/links.json")
    elif stage == "mesh":
        from src.enrich.mesh import fetch
        fetch(L1, "data/raw/mesh", cache=MESH_CACHE if Path(MESH_CACHE).exists() else None)
    elif stage == "mesh-cache":
        import datetime
        from src.enrich.mesh_cache import cache_from_raw, save_cache
        raw = Path("data/raw/mesh")
        pubmed, trees = cache_from_raw(raw)
        newest = max((f.stat().st_mtime for f in raw.glob("pm_*.xml")), default=0)
        save_cache(MESH_CACHE, pubmed, trees, datetime.date.fromtimestamp(newest).isoformat())
        print("wrote", MESH_CACHE, len(pubmed), "pmids", len(trees), "descriptors")
    elif stage == "classify":
        from src.enrich.mesh import classify
        classify(L1, "data/raw/mesh", "schema/overrides/system.yaml", "data/l2/system.json", "data/reports/system.json",
                 cache=MESH_CACHE if Path(MESH_CACHE).exists() else None)
    elif stage == "suggest-prepare":
        from src.enrich.suggest import prepare
        prepare("data/l2/system.json", L1, "data/l2/agent", int(argv[1]))
    elif stage == "suggest-collect":
        from src.enrich.suggest import collect
        collect("data/l2/agent", "schema/overrides/system-agent.yaml", argv[1])
    elif stage == "harvest":
        from src.enrich.harvest import run
        run("vault", "data/registry.json", "data/l1_index.json", "schema/overrides/system.yaml")
    elif stage == "subsuggest-prepare":
        from src.enrich.suggest import prepare_sub
        prepare_sub("data/l2/system.json", L1, "data/l2/agent-sub")
    elif stage == "subsuggest-collect":
        from src.enrich.suggest import collect_sub
        collect_sub("data/l2/agent-sub", "schema/overrides/subsystem-agent.yaml", argv[1])
    elif stage == "tags-prepare":
        from src.enrich.tagging import prepare_tags
        if "--followup" in argv:
            prepare_tags("data/l2/system.json", L1, "data/l2/agent-tags-followup",
                         followup_yaml="schema/overrides/tags-agent.yaml")
        else:
            prepare_tags("data/l2/system.json", L1, "data/l2/agent-tags")
    elif stage == "tags-collect":
        from src.enrich.tagging import collect_tags
        batch_dir = "data/l2/agent-tags-followup" if "--followup" in argv else "data/l2/agent-tags"
        collect_tags(batch_dir, "schema/overrides/tags-agent.yaml", argv[1])
    elif stage == "drugs-prepare":
        from src.enrich.tagging import prepare_drugs
        prepare_drugs(L1, "data/l2/agent-drugs")
    elif stage == "drugs-collect":
        from src.enrich.tagging import collect_drugs
        collect_drugs("data/l2/agent-drugs", "schema/overrides/drug-class-agent.yaml", argv[1])
    elif stage == "migrate-bookmarks":
        from src.migrate.bookmarks import run
        run("vault/.obsidian/bookmarks.json", "data/reports/moves.json", "backups")
    elif stage == "bundle":
        from src.installer.bundle import bundle
        manifest = bundle(".", argv[1], None)
        print(f"wrote {argv[1]} ({Path(argv[1]).stat().st_size} bytes, {len(manifest)} files)")
    elif stage == "bundle-exe":  # bundle-exe OUT.exe SOURCE_DIR (DEC-28)
        from src.installer.exe import build
        size, n = build(".", argv[1], argv[2])
        print(f"wrote {argv[2]} ({n} files) and {argv[1]} ({size} bytes)")
    elif stage == "validate":
        from src.validate.check import check
        return check("vault")
    else:
        return None
    return 0


@contextlib.contextmanager
def working_dir(root):
    old = os.getcwd()
    os.chdir(root)
    try:
        yield
    finally:
        os.chdir(old)


def run(argv, root=None):
    """Run one stage; -> exit code (None for an unknown stage). With `root`, paths resolve inside that folder."""
    if root is None:
        return _run(argv)
    with working_dir(root):
        return _run(argv)
