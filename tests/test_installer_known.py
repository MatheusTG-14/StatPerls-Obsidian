import io
import json
from pathlib import Path

import pytest

from src.installer import app, known
from src.installer.ui import Console


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("SP_CONFIG_DIR", str(tmp_path / "config"))
    return tmp_path / "config"


def make_install(path, articles=9651):
    meta = path / "data" / "meta"
    meta.mkdir(parents=True)
    (path / "vault").mkdir()
    (meta / "installed.json").write_text(json.dumps({"archive_updated": "2026-10-25 03:25:13", "archive_size": 1,
                                                     "articles": articles}), encoding="utf-8")
    return path


def test_remember_keeps_newest_first_without_duplicates(tmp_path):
    a, b = make_install(tmp_path / "A"), make_install(tmp_path / "B")
    known.remember(a)
    known.remember(b)
    known.remember(a)
    assert known.load() == [str(a.resolve()), str(b.resolve())]
    for i in range(10):
        known.remember(tmp_path / f"X{i}")
    assert len(known.load()) == known.MAX_REMEMBERED
    known.forget(tmp_path / "X9")
    assert str((tmp_path / "X9").resolve()) not in known.load()


def test_normalize_accepts_the_install_folder_or_its_vault(tmp_path):
    root = make_install(tmp_path / "Vault ç dir")
    assert known.normalize(root) == root.resolve()
    assert known.normalize(root / "vault") == root.resolve()  # picked the vault itself: one level up
    assert known.normalize(tmp_path) is None
    assert known.normalize(tmp_path / "missing") is None


def test_find_folder_falls_back_to_a_remembered_install(tmp_path, monkeypatch):
    root = make_install(tmp_path / "Far away")
    monkeypatch.chdir(tmp_path)
    assert app.find_folder(None) is None
    known.remember(root)
    assert app.find_folder(None) == root.resolve()
    assert app.find_folder(str(root / "vault")) == root.resolve()


def test_explicit_folder_that_is_not_an_install_says_what_to_pick(tmp_path):
    out = io.StringIO()
    c = Console(out=out, plain=True)
    rc = app.main(["status", "--folder", str(tmp_path)], bundle=None, console=c, use_venv=False)
    assert rc == 1
    assert "contains the vault and data folders" in out.getvalue()


def test_status_remembers_the_folder(tmp_path, monkeypatch):
    root = make_install(tmp_path / "Somewhere")
    monkeypatch.setattr(app, "latest_info", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    c = Console(out=io.StringIO(), plain=True)
    assert app.main(["status", "--folder", str(root)], bundle=None, console=c, use_venv=False) == 0
    assert known.load() == [str(root.resolve())]


def test_menu_can_switch_to_a_remembered_vault(tmp_path, monkeypatch):
    a, b = make_install(tmp_path / "First", 100), make_install(tmp_path / "Second", 200)
    known.remember(a)
    known.remember(b)  # newest first: Second is the default
    known.remember(tmp_path / "Unplugged drive")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app, "latest_info", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    choices = iter(["Choose vault folder...", None, "Quit"])
    seen = []

    def fake_menu(rows, options):
        seen.append((rows, options))
        pick = next(choices)
        if pick is None:  # the picker: choose the remembered "First" install
            return next(label for label, _ in options if label.startswith(str(a.resolve())))
        return pick
    c = Console(out=io.StringIO(), plain=True)
    monkeypatch.setattr(c, "menu", fake_menu)
    assert app.menu(c, None, False) == 0
    first_rows = dict((k, v) for k, v in seen[0][0] if isinstance(k, str))
    assert str(b.resolve()) in str(first_rows["Vault folder"])
    picker = dict(seen[1][1])
    missing = next(label for label in picker if "Unplugged drive" in label)
    assert picker[missing]  # shown but disabled, with a reason
    assert "Another folder..." in picker
    last_rows = dict((k, v) for k, v in seen[2][0] if isinstance(k, str))
    assert str(a.resolve()) in str(last_rows["Vault folder"])


def test_menu_without_any_vault_offers_to_find_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen = []

    def fake_menu(rows, options):
        seen.append(dict(options))
        return "Quit"
    c = Console(out=io.StringIO(), plain=True)
    monkeypatch.setattr(c, "menu", fake_menu)
    assert app.menu(c, None, False) == 0
    assert "Find an existing vault..." in seen[0]
