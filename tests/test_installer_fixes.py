"""Regression tests for the independent review of the installer (C1, I1-I5, M3)."""
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from src.installer import app, env
from src.installer.ui import Console

REPO = Path(__file__).resolve().parents[1]


# ---- C1: the first thing the .pyz does must work on a clean Python (no yaml, no lxml) ----

def test_import_chain_is_stdlib_only():
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "try:\n    import yaml\n    sys.exit(3)\nexcept ImportError:\n    pass\n"
        "try:\n    import lxml\n    sys.exit(4)\nexcept ImportError:\n    pass\n"
        "import src.installer.app, src.installer.env, src.installer.ui, src.installer.archive\n"
    )
    r = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _installed_folder(tmp_path):
    folder = tmp_path / "inst"
    (folder / "data" / "meta").mkdir(parents=True)
    (folder / "data" / "meta" / "installed.json").write_text(
        json.dumps({"archive_updated": "2026-10-25 03:25:13", "archive_size": 1}), encoding="utf-8")
    return folder


@pytest.mark.parametrize("argv,expect", [
    (["status"], ["status", "--folder"]),
    (["export", "out.pyz"], ["export"]),
    (["agent-prepare"], ["agent-prepare", "--folder"]),
    (["agent-collect", "m1"], ["agent-collect"]),
])
def test_every_command_goes_through_the_venv(tmp_path, monkeypatch, argv, expect):
    folder = _installed_folder(tmp_path)
    calls = []

    def fake(root, console, child_args=None, **kw):
        calls.append((Path(root), list(child_args)))
        raise SystemExit(0)
    monkeypatch.setattr(env, "ensure_venv", fake)
    console = Console(out=io.StringIO(), inp=lambda p="": "", color=False, yes=True)
    with pytest.raises(SystemExit):
        app.main(argv + ["--folder", str(folder)], bundle=app.DirBundle(tmp_path), console=console, use_venv=True)
    assert calls and calls[0][0] == folder
    assert all(x in calls[0][1] for x in expect) and str(folder) in calls[0][1]


# ---- I4: the child must get the answers the parent already collected ----

def test_menu_choice_and_prompted_folder_reach_the_child(tmp_path, monkeypatch):
    calls = []

    def fake(root, console, child_args=None, **kw):
        calls.append((Path(root), list(child_args)))
        raise SystemExit(0)
    monkeypatch.setattr(env, "ensure_venv", fake)
    monkeypatch.setattr(env, "obsidian_has_vault_open", lambda n: False)
    monkeypatch.setattr(env, "NEEDED_BYTES", 1)
    from src.installer import archive
    monkeypatch.setattr(archive, "fetch_info", lambda: archive.ArchiveInfo(path="x", updated="2026-10-25 03:25:13", size=1))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app, "default_bundle", lambda: None)
    target = tmp_path / "chosen"
    answers = iter(["1", str(target), ""])  # menu: Install, the folder, then Continue? (plan first)
    console = Console(out=io.StringIO(), inp=lambda p="": next(answers), color=False, yes=False)
    from src.installer.app import DirBundle
    (tmp_path / "b").mkdir()
    with pytest.raises(SystemExit):
        app.main([], bundle=DirBundle(tmp_path / "b"), console=console, use_venv=True)
    assert calls[0][0] == target
    assert calls[0][1][:2] == ["install", str(target)]
    assert "--yes" not in calls[0][1]  # the plan is still confirmed by the user in the child


def test_child_argv_keeps_flags():
    import argparse
    ns = argparse.Namespace(cmd="update", folder=None, force=True, archive="a.tgz", yes=True)
    assert app.child_argv(ns, Path("F")) == ["update", "--folder", str(Path("F")), "--force", "--archive", "a.tgz", "--yes"]


# ---- I5: atomic writes ----

def test_write_text_is_atomic(tmp_path):
    from src.common import write_json, write_text
    p = tmp_path / "registry.json"
    write_text(p, "old")
    with pytest.raises(TypeError):
        write_text(p, object())  # fails after the file is opened for writing
    assert p.read_text(encoding="utf-8") == "old"
    assert [x.name for x in tmp_path.iterdir()] == ["registry.json"]
    write_json(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_app_json_helper_is_atomic(tmp_path):
    p = tmp_path / "s.json"
    app.write_json_file(p, {"k": 1})
    with pytest.raises(TypeError):
        app.write_json_file(p, {"k": object()})
    assert json.loads(p.read_text(encoding="utf-8")) == {"k": 1}
    assert [x.name for x in tmp_path.iterdir()] == ["s.json"]


# ---- M3: Obsidian window titles ----

@pytest.mark.parametrize("title,vault,want", [
    ("vault - Obsidian 1.12.7", "vault", True),
    ("New tab - vault - Obsidian 1.12.7", "vault", True),
    ("Doenças biliares - __Obsidian - Obsidian 1.12.7", "vault", False),
    ("A - B - vault - Obsidian 1.12.7", "vault", True),
    ("x - vault - other - Obsidian 1.12.7", "vault", False),
    ("Untitled", "vault", False),
])
def test_title_matches_variants(title, vault, want):
    assert env.title_matches(title, vault) is want


# ---- I3: the build guard compares categories and subcategories separately ----

def test_recorded_overrides_are_kept_apart(tmp_path, monkeypatch):
    from src.enrich.harvest import pending_changes
    from src.render import build
    ov = tmp_path / "schema" / "overrides"
    ov.mkdir(parents=True)
    (ov / "system.yaml").write_bytes(b"article-1: skin\n")
    (ov / "subsystem.yaml").write_bytes(b"article-1: skin/skin-infections-and-infestations\n")
    monkeypatch.chdir(tmp_path)
    cats, subs = build.recorded_overrides()
    assert cats == {"article-1": "skin"} and subs == {"article-1": "skin/skin-infections-and-infestations"}
    root = tmp_path / "StatPearls"
    (root / "Articles" / "Skin").mkdir(parents=True)
    (root / "Articles" / "Skin" / "Note.md").write_bytes(b'---\nsubsystem: "skin-infections-and-infestations"\n---\nx\n')
    got = pending_changes(root, {"article-1": "Note"}, {"article-1": "skin"}, {"Note": "skin/inflammatory-dermatoses"}, since=0,
                          recorded=cats, recorded_subs=subs)
    assert got == {}


# ---- I1: a changed article of the same size must still be re-extracted ----

def _tar(path, body, jpg):
    with tarfile.open(path, "w:gz") as t:
        for name, data in (("s/a.nxml", body), ("s/Pic.jpg", jpg)):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))


def test_same_size_change_is_extracted(tmp_path):
    from src.acquire.media import unpack
    from src.installer import archive
    v1, v2 = tmp_path / "v1.tgz", tmp_path / "v2.tgz"
    _tar(v1, b"<x>AAAA</x>", b"JPG-1")
    _tar(v2, b"<x>BBBB</x>", b"JPG-2")
    out, media = tmp_path / "raw", tmp_path / "media"
    archive.extract_articles(v1, out)
    unpack(str(v1), str(media), str(tmp_path / "m.json"), str(tmp_path / "reg.json"))
    archive.extract_articles(v2, out)
    unpack(str(v2), str(media), str(tmp_path / "m.json"), str(tmp_path / "reg.json"))
    assert (out / "a.nxml").read_bytes() == b"<x>BBBB</x>"
    assert (media / "Pic.jpg").read_bytes() == b"JPG-2"
