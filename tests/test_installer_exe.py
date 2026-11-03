"""The Windows .exe (DEC-28): the compilable source folder, corrections files and the frozen-mode behaviour."""
import io
import json
import sys
import zipfile

import pytest

from src.installer import app, bundle, exe
from src.installer.ui import Console
from tests.test_installer_bundle import make_root


def test_stage_writes_a_compilable_folder(tmp_path):
    root = make_root(tmp_path)
    src = tmp_path / "exe-source"
    manifest = exe.stage(root, src)
    for name in ("entry.py", "statpearls-vault.spec", "build.cmd", "build-requirements.txt", "README.md",
                 "src/installer/app.py", "schema/vocab/facets.yaml", "state/registry.json", "_vendor/rich/__init__.py",
                 "obsidian-config/app.json", "plugin/main.js", exe.MARKER):
        assert (src / name).is_file(), name
    assert "__main__.py" not in manifest
    assert b"\r\n" in (src / "build.cmd").read_bytes()
    assert "pyinstaller==" in (src / "build-requirements.txt").read_text(encoding="utf-8")
    compile((src / "statpearls-vault.spec").read_text(encoding="utf-8"), "spec", "exec")  # valid Python
    text = " ".join(manifest)
    assert "PROSE" not in text and "Mine" not in text and "workspace" not in text and "l1/" not in text


def test_stage_replaces_its_own_folder_and_keeps_build_caches(tmp_path):
    root = make_root(tmp_path)
    src = tmp_path / "exe-source"
    exe.stage(root, src)
    (src / "stale.txt").write_text("old", encoding="utf-8")
    (src / ".build").mkdir()
    (src / ".build" / "cache").write_text("c", encoding="utf-8")
    exe.stage(root, src)
    assert not (src / "stale.txt").exists() and (src / ".build" / "cache").is_file()


def test_stage_refuses_a_folder_it_did_not_write(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        exe.stage(make_root(tmp_path), other)
    assert (other / "keep.txt").is_file()


def test_corrections_file_carries_data_only(tmp_path):
    root = make_root(tmp_path)
    out = tmp_path / "c.zip"
    bundle.corrections(root, out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert z.read("schema/overrides/system.yaml") == b"article-1: skin\n"
    assert names and all(n.startswith(bundle.DATA_PREFIXES) for n in names)
    assert "state/registry.json" in names and "plugin/main.js" in names


def test_layered_bundle_prefers_the_corrections(tmp_path):
    base, top = tmp_path / "base", tmp_path / "top"
    (base / "schema" / "overrides").mkdir(parents=True)
    (top / "schema" / "overrides").mkdir(parents=True)
    (base / "schema" / "overrides" / "a.yaml").write_text("old", encoding="utf-8")
    (base / "schema" / "overrides" / "b.yaml").write_text("b", encoding="utf-8")
    (top / "schema" / "overrides" / "a.yaml").write_text("new", encoding="utf-8")
    lb = app.LayeredBundle([app.DirBundle(top), app.DirBundle(base)])
    assert lb.read("schema/overrides/a.yaml") == b"new" and lb.read("schema/overrides/b.yaml") == b"b"
    assert lb.read("missing") is None
    assert lb.names("schema/overrides/") == ["schema/overrides/a.yaml", "schema/overrides/b.yaml"]


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """Pretend to be the .exe: built-in data in a folder, the program in another."""
    meipass = tmp_path / "meipass"
    (meipass / "schema" / "overrides").mkdir(parents=True)
    (meipass / "schema" / "overrides" / "system.yaml").write_text("built-in", encoding="utf-8")
    prog = tmp_path / "usb" / "statpearls-vault.exe"
    prog.parent.mkdir()
    prog.write_bytes(b"MZ")
    monkeypatch.setattr(app, "FROZEN", True)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(prog))
    return prog


def test_frozen_bundle_reads_built_in_data_and_a_corrections_file_beside_it(frozen):
    b = app.default_bundle()
    assert b.read("schema/overrides/system.yaml") == b"built-in"
    with zipfile.ZipFile(frozen.parent / app.CORRECTIONS_NAME, "w") as z:
        z.writestr("schema/overrides/system.yaml", "corrected")
    b = app.default_bundle()
    assert isinstance(b, app.LayeredBundle) and b.read("schema/overrides/system.yaml") == b"corrected"


def test_frozen_messages_name_the_exe_and_never_use_a_venv(frozen, tmp_path, monkeypatch):
    assert app.prog() == "statpearls-vault.exe"
    assert app.default_export_path() == frozen.parent / app.CORRECTIONS_NAME
    seen = {}
    monkeypatch.setattr(app, "dispatch", lambda args, console, bundle, use_venv: seen.setdefault("venv", use_venv) and 0)
    app.main(["status"], console=Console(out=io.StringIO(), plain=True))
    assert seen["venv"] is False


def installed(tmp_path):
    root = make_root(tmp_path)
    (root / "data" / "meta" / "installed.json").write_text(json.dumps({"archive_updated": "x", "archive_size": 1}), encoding="utf-8")
    return root


def test_frozen_export_writes_corrections_and_refuses_a_pyz(frozen, tmp_path):
    root = installed(tmp_path)
    out = io.StringIO()
    c = Console(out=out, inp=lambda p="": "", plain=True, yes=True)
    rc = app.main(["export", str(tmp_path / "x.pyz"), "--folder", str(root), "--yes"], console=c)
    assert rc == 1 and not (tmp_path / "x.pyz").exists() and ".zip" in out.getvalue()
    target = tmp_path / "fix.zip"
    rc = app.main(["export", str(target), "--folder", str(root), "--yes"], console=Console(out=io.StringIO(), plain=True, yes=True))
    assert rc == 0
    with zipfile.ZipFile(target) as z:
        assert all(n.startswith(bundle.DATA_PREFIXES) for n in z.namelist())


def test_check_build_python_names_what_is_wrong(monkeypatch):
    monkeypatch.setattr(exe, "requirements", lambda: ["surely-not-installed-pkg==1.0"])
    with pytest.raises(SystemExit, match="surely-not-installed-pkg missing"):
        exe.check_build_python()
