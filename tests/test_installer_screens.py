"""Every static screen, in rich mode (forced) and in plain mode."""
import io
import re

import pytest

from src.installer.ui import Console, UserError, run_safely

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def make(plain, width=100, inputs=("",), **kw):
    out = io.StringIO()
    it = iter(inputs)
    c = Console(out=out, inp=lambda prompt="": (out.write(prompt + chr(10)), next(it))[1], plain=plain, width=width, **kw)
    return c, out


def show_all(c):
    c.header("StatPearls vault", "Installer 1")
    c.state_panel([("Installed", "yes"), ("Folder", "C:/Vault"), ("Update available", "unknown")])
    assert c.plan_panel(["Download the archive.", "Build the notes."], [("Download", "2.0 GB"), ("Time", "about 30 min")]) is True
    c.done_panel([("New", 12), ("Updated", 3), ("Removed", 0), ("Placed automatically", 40)],
                 ["Full report: C:/Vault/data/reports/update.json", "", "Next steps:", "  1. Open Obsidian."], ok=True)
    c.done_panel([("New", 1)], ["Full report: x"], ok=False)
    c.status_table([("Archive", "25 Oct 2026"), ("Articles", "9,651")])
    c.stopped()
    c.error("Obsidian has this vault open.", "Close it and run update again.", "C:/Vault/logs/installer.log")


@pytest.mark.parametrize("plain", [False, True])
def test_every_screen_has_its_key_strings(plain):
    c, out = make(plain)
    show_all(c)
    text = ANSI.sub("", out.getvalue())
    assert "run the same command again" in text.lower()
    for want in ("StatPearls vault", "Continue?", "Done", "Done with warnings", "New", "Updated", "Placed automatically",
                 "Full report", "Stopped safely", "installer.log", "Obsidian has this vault open.",
                 "Archive", "9,651", "Update available"):
        assert want in text, want
    if plain:
        assert "\x1b[" not in out.getvalue()
    else:
        assert "\x1b[" in out.getvalue()


@pytest.mark.parametrize("plain", [False, True])
def test_screens_fit_60_columns(plain):
    c, out = make(plain, width=60)
    show_all(c)
    for line in ANSI.sub("", out.getvalue()).splitlines():
        assert len(line) <= 60, line


def test_rich_flag_and_redirect():
    out = io.StringIO()
    assert Console(out=out).rich is False            # not a terminal -> plain automatically
    assert Console(out=out, plain=False).rich is True
    assert Console(out=out, plain=True).rich is False


def test_no_color_env_means_plain(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setenv("NO_COLOR", "1")
    assert Console(out=Tty(), unicode=True).rich is False
    monkeypatch.delenv("NO_COLOR")
    assert Console(out=Tty(), unicode=True).rich is True


def test_ascii_fallback():
    buf = io.BytesIO()
    out = io.TextIOWrapper(buf, encoding="cp437", errors="strict", newline="")
    c = Console(out=out)
    assert c.rich is False
    c.step(1, 8, "Checking")
    c.done("Ready")
    c.state_panel([("Folder", "x")])
    c.done_panel([("New", 1)], ["Full report: y"])
    out.flush()
    text = buf.getvalue().decode("cp437")
    assert "[done]" in text and "\u2713" not in text
    assert all(ord(ch) < 128 for ch in text)


def test_plain_output_for_a_redirected_status_has_no_escape_codes():
    c, out = make(None)
    c.status_table([("Archive", "25 Oct 2026")])
    assert "\x1b" not in out.getvalue() and "Archive" in out.getvalue()


def test_plan_declined_returns_false():
    for plain in (False, True):
        c, out = make(plain, inputs=("n",))
        assert c.plan_panel(["x"], [("a", "b")]) is False


def test_help_screen():
    for plain in (False, True):
        c, out = make(plain)
        c.help("statpearls-vault.pyz", "Install, update and report.", [("install", "build a new vault"), ("update", "rebuild")],
               ["python statpearls-vault.pyz install"])
        t = ANSI.sub("", out.getvalue())
        assert "install" in t and "build a new vault" in t and "Install, update" in t and "Examples" in t


def test_error_via_run_safely_in_rich_mode(tmp_path):
    c, out = make(False)

    def fn():
        raise UserError("Not enough disk space.", "Free 12 GB and run again.")
    assert run_safely(fn, c, tmp_path / "l.txt") == 1
    t = ANSI.sub("", out.getvalue())
    assert "Not enough disk space." in t and "Free 12 GB" in t and "Traceback" not in t


# ---- commands: status, export, agent screens ----

def _installed(tmp_path):
    import json
    folder = tmp_path / "inst"
    (folder / "data" / "meta").mkdir(parents=True)
    (folder / "data" / "reports").mkdir(parents=True)
    (folder / "vault" / "StatPearls").mkdir(parents=True)
    (folder / "vault" / "StatPearls" / "n.md").write_text("x" * 2000, encoding="utf-8")
    (folder / "data" / "meta" / "installed.json").write_text(json.dumps(
        {"archive_updated": "2026-10-25 03:25:13", "archive_size": 1, "articles": 9651, "installed_at": "2026-11-02T10:00:00+00:00"}), encoding="utf-8")
    (folder / "data" / "reports" / "system.json").write_text(json.dumps({"auto_classified": ["a"]}), encoding="utf-8")
    return folder


@pytest.mark.parametrize("plain", [False, True])
def test_status_is_a_table(tmp_path, monkeypatch, plain):
    from src.installer import app, archive
    monkeypatch.setattr(archive, "fetch_info", lambda: archive.ArchiveInfo(path="x", updated="2026-10-25 03:25:13", size=1))
    folder = _installed(tmp_path)
    c, out = make(plain)
    rc = app.main(["status", "--folder", str(folder)], bundle=app.DirBundle(tmp_path), console=c, use_venv=False)
    t = ANSI.sub("", out.getvalue())
    assert rc == 0
    for want in ("Archive", "25 Oct 2026", "Articles", "9,651", "Placed automatically", "Last update", "Vault size", "2.0 KB", "Update available", "no"):
        assert want in t, want
    if plain:
        assert "\x1b" not in out.getvalue()


def test_status_offline_says_unknown(tmp_path, monkeypatch):
    from src.installer import app, archive
    monkeypatch.setattr(archive, "fetch_info", lambda: (_ for _ in ()).throw(UserError("offline")))
    c, out = make(True)
    assert app.main(["status", "--folder", str(_installed(tmp_path))], bundle=app.DirBundle(tmp_path), console=c, use_venv=False) == 0
    assert "unknown (could not reach NLM)" in out.getvalue()


def test_export_shows_plan_then_done_panel(tmp_path):
    from src.installer import app
    folder = _installed(tmp_path)
    target = tmp_path / "out.pyz"
    c, out = make(True, inputs=("",))
    rc = app.main(["export", str(target), "--folder", str(folder)], bundle=app.DirBundle(tmp_path), console=c, use_venv=False)
    t = out.getvalue()
    assert rc == 0 and target.exists()
    assert "Continue?" in t and "Done" in t and target.name in t and "private" in t.lower()


def test_export_declined_writes_nothing(tmp_path):
    from src.installer import app
    folder = _installed(tmp_path)
    target = tmp_path / "out.pyz"
    c, out = make(True, inputs=("n",))
    assert app.main(["export", str(target), "--folder", str(folder)], bundle=app.DirBundle(tmp_path), console=c, use_venv=False) == 1
    assert not target.exists()


def test_agent_steps_are_numbered():
    from src.installer import app
    lines = app.agent_prepare_lines(3, "D:/x/l2")
    assert any(l.strip().startswith("1.") for l in lines) and any(l.strip().startswith("3.") for l in lines)
    assert any(l.strip().startswith("1.") for l in app.agent_collect_lines())
