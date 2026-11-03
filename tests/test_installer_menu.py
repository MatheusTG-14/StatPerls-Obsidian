import io
import json
import re
import time

import pytest

from src.installer import app, archive, keys
from src.installer.ui import Console, Pending

ANSI = re.compile(chr(27) + r"\[[0-9;?]*[A-Za-z]")
OPTIONS = [("Install", None), ("Update", None), ("Status", None), ("Export", None), ("Quit", None)]
NOT_INSTALLED = [("Install", None), ("Update", "nothing is installed yet"), ("Status", "nothing is installed yet"),
                 ("Export", "nothing is installed yet"), ("Quit", None)]


def seq(*pressed):
    it = iter(pressed)

    def read(timeout=None):
        return next(it)
    return read


def rich_console(*pressed, inputs=()):
    out = io.StringIO()
    it = iter(inputs)
    return Console(out=out, inp=lambda p="": next(it), plain=False, width=100, keys=seq(*pressed)), out


def test_menu_arrows_and_digits():
    c, out = rich_console("down", "down", "enter")
    assert c.menu([("Installed", "yes")], OPTIONS) == "Status"
    c, out = rich_console("2")
    assert c.menu([("Installed", "yes")], OPTIONS) == "Update"
    c, out = rich_console("up", "enter")                      # wraps around to the last item
    assert c.menu([], OPTIONS) == "Quit"
    for k in ("esc", "q"):
        c, out = rich_console(k)
        assert c.menu([], OPTIONS) == "Quit"
    text = ANSI.sub("", out.getvalue())
    assert "1) Install" in text and "5) Quit" in text


def test_disabled_items_are_skipped_by_arrows_and_refused_by_digits():
    c, out = rich_console("2", "down", "enter")
    assert c.menu([], NOT_INSTALLED) == "Quit"                # "2" refused, down from Install skips to Quit
    text = ANSI.sub("", out.getvalue())
    assert "Update is not available: nothing is installed yet" in text
    c, out = rich_console("2", "enter")
    assert c.menu([], NOT_INSTALLED) == "Install"             # still on the first enabled item


def test_typed_menu_in_plain_mode_refuses_disabled():
    out = io.StringIO()
    answers = iter(["2", "x", "1"])
    c = Console(out=out, inp=lambda p="": next(answers), plain=True)
    assert c.menu([("Installed", "no")], NOT_INSTALLED) == "Install"
    assert "nothing is installed yet" in out.getvalue() and "1) Install" in out.getvalue()


def test_key_mappings():
    assert keys.map_windows("\xe0", "H") == "up" and keys.map_windows("\x00", "P") == "down"
    assert keys.map_windows("\r") == "enter" and keys.map_windows("\x1b") == "esc" and keys.map_windows("3") == "3"
    assert keys.map_posix("\x1b[A") == "up" and keys.map_posix("\x1b[B") == "down" and keys.map_posix("\x1b") == "esc"
    assert keys.map_posix("\n") == "enter" and keys.map_posix("Q") == "q"
    with pytest.raises(KeyboardInterrupt):
        keys.map_windows("\x03")


def test_pending_gives_up_after_its_timeout():
    p = Pending(lambda: time.sleep(5), timeout=0.3)
    t0 = time.monotonic()
    ready, val = p.value(wait=True)
    assert time.monotonic() - t0 < 2 and ready and val is None
    assert Pending(lambda: "ok", timeout=2).value(wait=True) == (True, "ok")


def installed_folder(tmp_path):
    folder = tmp_path / "inst"
    (folder / "data" / "meta").mkdir(parents=True)
    (folder / "data" / "reports").mkdir(parents=True)
    (folder / "data" / "meta" / "installed.json").write_text(json.dumps(
        {"archive_updated": "2026-10-25 03:25:13", "archive_size": 1, "articles": 9651}), encoding="utf-8")
    (folder / "data" / "reports" / "system.json").write_text(json.dumps({"auto_classified": ["a", "b"]}), encoding="utf-8")
    return folder


def test_update_check_timeout(tmp_path, monkeypatch):
    folder = installed_folder(tmp_path)
    monkeypatch.setattr(archive, "fetch_info", lambda: time.sleep(5))
    monkeypatch.setattr(app, "UPDATE_CHECK_SECONDS", 0.3)
    rows, _ = app.welcome_state(folder, app.installed_info(folder))
    out = io.StringIO()
    c = Console(out=out, plain=True)
    t0 = time.monotonic()
    resolved, _ = c._resolved_rows(rows, wait=True)
    assert time.monotonic() - t0 < 5
    assert ("Update available", "unknown (could not reach NLM)") in resolved
    assert ("Articles", "9,651") in resolved and ("Placed automatically", "2") in resolved


def test_update_check_reports_a_newer_archive(tmp_path, monkeypatch):
    folder = installed_folder(tmp_path)
    monkeypatch.setattr(archive, "fetch_info", lambda: archive.ArchiveInfo(path="x", updated="2026-12-01 00:00:00", size=2))
    rows, _ = app.welcome_state(folder, app.installed_info(folder))
    resolved, _ = Console(out=io.StringIO(), plain=True)._resolved_rows(rows, wait=True)
    assert any(k == "Update available" and v.startswith("yes") for k, v in resolved)


def test_menu_options_disable_what_needs_an_install():
    assert app.menu_options(None)[1] == ("Update", "no vault chosen yet")
    assert all(r is None for _, r in app.menu_options({"archive_updated": "x"}))


# ---- hold the window open only when it would vanish ----

def run_main(argv, tmp_path, typed=(), interactive=True):
    out = io.StringIO()
    prompts = []
    it = iter(typed)

    def inp(prompt=""):
        prompts.append(prompt)
        return next(it, "")
    c = Console(out=out, inp=inp, plain=True, interactive=interactive)
    rc = app.main(argv, bundle=app.DirBundle(tmp_path), console=c, use_venv=False)
    return rc, out.getvalue(), prompts


def test_hold_open_only_from_menu(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app, "default_bundle", lambda: None)
    # menu start (a double-click gives this): Install into a cloud-synced folder -> error screen, then waits
    cloud = str(tmp_path / "OneDrive" / "v")
    rc, text, prompts = run_main([], tmp_path, typed=["1", cloud])
    assert rc == 1 and any("Press Enter" in p for p in prompts)
    # a typed command never waits
    rc, text, prompts = run_main(["status", "--folder", str(tmp_path / "nothing")], tmp_path)
    assert rc == 1 and not any("Press Enter" in p for p in prompts)
    # --yes never waits
    rc, text, prompts = run_main(["update", "--folder", str(tmp_path / "nothing"), "--yes"], tmp_path)
    assert not any("Press Enter" in p for p in prompts)
    # a menu start without a terminal never waits
    rc, text, prompts = run_main([], tmp_path, typed=["1", cloud], interactive=False)
    assert not any("Press Enter" in p for p in prompts)


def test_quitting_the_menu_closes_at_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(app, "default_bundle", lambda: None)
    rc, text, prompts = run_main([], tmp_path, typed=["6"])  # 5 is "Find an existing vault..."
    assert rc == 0 and not any("Press Enter" in p for p in prompts)
