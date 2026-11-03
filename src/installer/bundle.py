"""Build statpearls-vault.pyz: code, vocabularies, corrections, metadata state, Obsidian settings and the plugin.

Never includes StatPearls prose, figures or archive files, nor personal files (rule 2): no data/l1, no vault/StatPearls,
no vault/Mine, no workspace or bookmarks. Deterministic: sorted entries, fixed timestamps, same bytes for the same inputs.
A corrections file (.zip) is the data part alone, for the Windows .exe, which cannot rewrite itself (DEC-28).
"""
import json
import sys
import zipfile
from pathlib import Path

MAIN = '''import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor"))  # Rich, shipped inside the .pyz

from src.installer.app import main

sys.exit(main(sys.argv[1:]))
'''
OBSIDIAN_FILES = ("app.json", "appearance.json", "core-plugins.json", "community-plugins.json", "graph.json", "snippets/statpearls.css")
STATE = (("data/registry.json", "state/registry.json"), ("data/meta/pubmed_map.json", "state/pubmed_map.json"),
         ("data/meta/mesh_cache.json.gz", "state/mesh_cache.json.gz"))
STAMP = (1980, 1, 1, 0, 0, 0)
# Rich modules that import Pygments or markdown-it (or only serve what the installer never shows) are left out.
RICH_SKIP = {"syntax.py", "markdown.py", "traceback.py", "logging.py", "diagnose.py", "__main__.py"}


# what a corrections file carries: everything that is not code
DATA_PREFIXES = ("state/", "schema/overrides/", "obsidian-config/", "plugin/")


def _running_zip():
    p = Path(sys.argv[0])
    return p if p.is_file() and zipfile.is_zipfile(p) else None


def _zip_entries(prefix):
    """Files under `prefix` in the program that is running: the .pyz, or the folder the .exe unpacked itself into."""
    if getattr(sys, "frozen", False):
        return _tree(Path(sys._MEIPASS) / prefix.rstrip("/"), prefix.rstrip("/"))
    z = _running_zip()
    if z is None:
        return {}
    with zipfile.ZipFile(z) as zf:
        return {n: zf.read(n) for n in zf.namelist() if n.startswith(prefix) and not n.endswith("/")}


def _tree(base, rel_prefix, keep=lambda p: True):
    out = {}
    base = Path(base)
    if base.is_dir():
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(base).as_posix()
            if p.is_file() and "__pycache__" not in p.parts and keep(p.relative_to(base)):
                out[f"{rel_prefix}/{rel}"] = p.read_bytes()
    return out


def _vendor_rich():
    """{path in the zip: bytes} for the Rich package (minus RICH_SKIP) and its licence; from the running .pyz when exporting."""
    inside = _zip_entries("_vendor/")
    if inside:
        return inside
    import rich
    pkg = Path(rich.__file__).parent
    out = _tree(pkg, "_vendor/rich", lambda p: p.suffix in (".py", ".typed") and not (len(p.parts) == 1 and p.name in RICH_SKIP))
    lic = next(iter(sorted(pkg.parent.glob("rich-*.dist-info/licenses/LICENSE*"))), None) or pkg.parent / "rich" / "LICENSE"
    if lic.is_file():
        out["_vendor/rich/LICENSE"] = lic.read_bytes()
    return out


def _first(*candidates):
    for c in candidates:
        if c is not None and Path(c).is_file():
            return Path(c).read_bytes()
    return None


def collect(root, plugin_dir=None):
    """Everything a .pyz carries: code, Rich, vocabularies and the data part (collect_data)."""
    root = Path(root)
    files = {"__main__.py": MAIN.encode("utf-8")}
    files.update(_vendor_rich())
    # code and vocabularies: this checkout, or the .pyz that is running (export from an install)
    if (root / "src").is_dir():
        files.update(_tree(root / "src", "src", lambda p: p.suffix in (".py", ".txt") and p.parts[0] != "census"))
        files.update(_tree(root / "schema" / "vocab", "schema/vocab"))
        files.update(_tree(root / "schema" / "bases", "schema/bases"))
    else:
        for prefix in ("src/", "schema/vocab/", "schema/bases/"):
            files.update(_zip_entries(prefix))
    files.update(collect_data(root, plugin_dir))
    return files


def collect_data(root, plugin_dir=None):
    """Corrections, metadata state, Obsidian settings and the plugin (DATA_PREFIXES)."""
    from src.installer import report  # needs yaml; only for hashes
    root = Path(root)
    files = _tree(root / "schema" / "overrides", "schema/overrides")
    for src, dest in STATE:
        data = _first(root / src, root / dest)  # working data folders, or state/ as in the public repository
        if data is not None:
            files[dest] = data
    hashes = None
    hp = root / "data" / "meta" / "content_hashes.json"
    if hp.is_file():
        hashes = json.loads(hp.read_text(encoding="utf-8"))
    else:
        ip = root / "data" / "l1_index.json"
        if ip.is_file():
            hashes = report.content_hashes(json.loads(ip.read_text(encoding="utf-8")))
        if not hashes and (root / "data" / "l1").is_dir():
            hashes = report.content_hashes_from_l1(root / "data" / "l1")
    files["state/content_hashes.json"] = (json.dumps(hashes or {}, sort_keys=True, indent=1) + "\n").encode("utf-8")
    dot = root / "vault" / ".obsidian"
    zipped = _zip_entries("obsidian-config/")
    for name in OBSIDIAN_FILES:
        data = _first(dot / name, root / "obsidian-config" / name)
        if data is None:
            data = zipped.get("obsidian-config/" + name)
        if data is not None:
            files["obsidian-config/" + name] = data
    pdirs = [Path(plugin_dir)] if plugin_dir else [root / "obsidian-plugin", root / "plugin", dot / "plugins" / "statpearls"]
    zp = _zip_entries("plugin/")
    for f in ("main.js", "manifest.json"):
        data = _first(*[d / f for d in pdirs])
        if data is None:
            data = zp.get("plugin/" + f)
        if data is not None:
            files["plugin/" + f] = data
    return files


def bundle(root, out, plugin_dir=None):
    """Write `out` (a zipapp). -> {path in the zip: size}."""
    return write_zip(collect(root, plugin_dir), out)


def corrections(root, out, plugin_dir=None):
    """Write `out`, a corrections file (the data part only). -> {path in the zip: size}."""
    return write_zip(collect_data(root, plugin_dir), out)


def write_zip(files, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(files):
            zi = zipfile.ZipInfo(name, STAMP)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, files[name], compresslevel=9)
    tmp.replace(out)
    return {n: len(files[n]) for n in sorted(files)}
