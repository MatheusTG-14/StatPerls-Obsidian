import json
import subprocess
import sys
import zipfile
from pathlib import Path

from src.installer.bundle import bundle

REPO = Path(__file__).resolve().parents[1]


def make_root(tmp_path):
    """A tiny development-style root: real code and schema, fake state and vault."""
    root = tmp_path / "root"
    (root / "data" / "meta").mkdir(parents=True)
    (root / "data" / "l1").mkdir()
    (root / "data" / "registry.json").write_text('{"articles": {"article-1": "Some Title"}}', encoding="utf-8")
    (root / "data" / "meta" / "pubmed_map.json").write_text("{}", encoding="utf-8")
    (root / "data" / "meta" / "mesh_cache.json.gz").write_bytes(b"gz")
    (root / "data" / "l1_index.json").write_text(json.dumps({"article-1": {"content_hash": "h1"}}), encoding="utf-8")
    (root / "data" / "l1" / "article-1.json").write_text("{}", encoding="utf-8")
    (root / "data" / "raw").mkdir()
    (root / "data" / "raw" / "a.nxml").write_text("<x/>", encoding="utf-8")
    (root / "data" / "media").mkdir()
    (root / "data" / "media" / "pic.jpg").write_bytes(b"jpg")
    dot = root / "vault" / ".obsidian"
    (dot / "snippets").mkdir(parents=True)
    (dot / "plugins" / "statpearls").mkdir(parents=True)
    for name, body in {"app.json": '{"a": 1}', "appearance.json": "{}", "core-plugins.json": "{}", "community-plugins.json": '["statpearls"]',
                       "graph.json": "{}", "workspace.json": "SECRET", "bookmarks.json": "SECRET"}.items():
        (dot / name).write_text(body, encoding="utf-8")
    (dot / "snippets" / "statpearls.css").write_text("/* css */", encoding="utf-8")
    (dot / "plugins" / "statpearls" / "main.js").write_text("// js", encoding="utf-8")
    (dot / "plugins" / "statpearls" / "manifest.json").write_text('{"id": "statpearls"}', encoding="utf-8")
    (root / "vault" / "StatPearls" / "Articles").mkdir(parents=True)
    (root / "vault" / "StatPearls" / "Articles" / "N.md").write_text("PROSE", encoding="utf-8")
    (root / "vault" / "Mine").mkdir()
    (root / "vault" / "Mine" / "mine.md").write_text("PRIVATE", encoding="utf-8")
    ov = root / "schema" / "overrides"
    ov.mkdir(parents=True)
    (ov / "system.yaml").write_bytes(b"article-1: skin\n")
    # the real code and vocabulary, as a development checkout has them
    import shutil
    shutil.copytree(REPO / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__", "census"))
    shutil.copytree(REPO / "schema" / "vocab", root / "schema" / "vocab")
    shutil.copytree(REPO / "schema" / "bases", root / "schema" / "bases")
    (root / "obsidian-plugin").mkdir()
    return root


def names_in(out):
    with zipfile.ZipFile(out) as z:
        return z.namelist()


def test_bundle_contents(tmp_path):
    root = make_root(tmp_path)
    out = tmp_path / "x.pyz"
    manifest = bundle(root, out, None)
    names = names_in(out)
    assert set(manifest) == set(names)
    for want in ("__main__.py", "src/installer/app.py", "src/installer/requirements.txt", "schema/vocab/facets.yaml",
                 "schema/bases/Auto-classified.base", "schema/overrides/system.yaml", "state/registry.json", "state/pubmed_map.json",
                 "state/mesh_cache.json.gz", "state/content_hashes.json", "obsidian-config/app.json",
                 "obsidian-config/community-plugins.json", "obsidian-config/snippets/statpearls.css", "plugin/main.js", "plugin/manifest.json"):
        assert want in names, want
    assert not any(n.endswith((".nxml", ".jpg", ".md")) for n in names)
    assert not any("__pycache__" in n or n.startswith("src/census") for n in names)
    assert not any(n.startswith(("data/", "vault/")) for n in names)
    assert "obsidian-config/workspace.json" not in names and "obsidian-config/bookmarks.json" not in names
    with zipfile.ZipFile(out) as z:
        assert json.loads(z.read("state/content_hashes.json")) == {"article-1": "h1"}
        assert z.read("schema/overrides/system.yaml") == b"article-1: skin\n"
        blob = b"".join(z.read(n) for n in z.namelist())
    assert b"PROSE" not in blob and b"PRIVATE" not in blob and b"SECRET" not in blob


def test_bundle_deterministic(tmp_path):
    root = make_root(tmp_path)
    a, b = tmp_path / "a.pyz", tmp_path / "b.pyz"
    bundle(root, a, None)
    bundle(root, b, None)
    assert a.read_bytes() == b.read_bytes()


def test_bundle_runs(tmp_path):
    root = make_root(tmp_path)
    out = tmp_path / "x.pyz"
    bundle(root, out, None)
    r = subprocess.run([sys.executable, str(out), "--help"], capture_output=True, text=True, encoding="utf-8", cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    for cmd in ("install", "update", "status", "export"):
        assert cmd in r.stdout


def test_bundled_vocabulary_is_readable_inside_the_zip(tmp_path):
    root = make_root(tmp_path)
    out = tmp_path / "x.pyz"
    bundle(root, out, None)
    code = "import sys; sys.path.insert(0, sys.argv[1]); from src.enrich.heuristics import drug_classes; print(drug_classes('Metoprolol'))"
    r = subprocess.run([sys.executable, "-c", code, str(out)], capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "beta-blockers" in r.stdout


def test_export_from_an_install_uses_installed_state(tmp_path):
    root = make_root(tmp_path)
    plugin = tmp_path / "plug"
    plugin.mkdir()
    (plugin / "main.js").write_text("// new", encoding="utf-8")
    (plugin / "manifest.json").write_text("{}", encoding="utf-8")
    out = tmp_path / "y.pyz"
    bundle(root, out, plugin)
    with zipfile.ZipFile(out) as z:
        assert z.read("plugin/main.js") == b"// new"


def test_bundle_vendors_rich(tmp_path):
    root = make_root(tmp_path)
    out = tmp_path / "x.pyz"
    bundle(root, out, None)
    names = names_in(out)
    assert "_vendor/rich/console.py" in names and "_vendor/rich/LICENSE" in names
    assert not any("pygments" in n.lower() or "markdown_it" in n for n in names)
    assert not any(n.startswith("_vendor/rich/") and n.endswith(("syntax.py", "markdown.py", "traceback.py")) for n in names)


def test_rich_imports_from_zip_without_site(tmp_path):
    root = make_root(tmp_path)
    out = tmp_path / "x.pyz"
    bundle(root, out, None)
    code = ("import sys; sys.path.insert(0, sys.argv[1] + '/_vendor');"
            "import rich.console, rich.live, rich.panel, rich.table, rich.layout, rich.progress_bar, rich.spinner, rich.rule;"
            "print(rich.console.__file__)")
    r = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "x.pyz" in r.stdout
    r = subprocess.run([sys.executable, "-I", "-S", str(out), "--help"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "Install" in r.stdout
