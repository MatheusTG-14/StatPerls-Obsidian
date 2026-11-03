"""Regression tests from the independent review of the interface work."""
import io
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

from src import progress
from src.installer import app, archive, dashboard, env, keys, ui
from src.installer.ui import Console, UserError

REPO = Path(__file__).resolve().parents[1]
ANSI = re.compile(chr(27) + r"\[[0-9;?]*[A-Za-z]")


def eof(prompt=""):
    raise EOFError


# 1 ---- no one to ask
def test_questions_without_stdin_are_a_user_error():
    c = Console(out=io.StringIO(), inp=eof, plain=True)
    for call in (lambda: c.confirm("Go?"), lambda: c.ask_path("Where?", "x"),
                 lambda: c.menu([], [("Install", None), ("Quit", None)])):
        with pytest.raises(UserError) as e:
            call()
        assert "no one to ask" in e.value.what and "--yes" in e.value.todo and e.value.log is False


def test_scripted_export_says_add_yes(tmp_path):
    out = io.StringIO()
    folder = tmp_path / "inst"
    (folder / "data" / "meta").mkdir(parents=True)
    (folder / "data" / "meta" / "installed.json").write_text(json.dumps({"archive_updated": "x", "archive_size": 1}), encoding="utf-8")
    c = Console(out=out, inp=eof, plain=True)
    rc = app.main(["export", str(tmp_path / "o.pyz"), "--folder", str(folder)], bundle=app.DirBundle(tmp_path), console=c, use_venv=False)
    assert rc == 1 and "Add --yes" in out.getvalue() and "unexpected" not in out.getvalue()


# 2 ---- ASCII fallback decided from the original stdout encoding
def test_unicode_is_decided_before_stdout_is_reconfigured(monkeypatch):
    seen = {}
    real = app.Console

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)
    monkeypatch.setattr(app, "Console", spy)
    legacy = io.TextIOWrapper(io.BytesIO(), encoding="cp437", newline="")
    monkeypatch.setattr(sys, "stdout", legacy)
    with pytest.raises(SystemExit):
        app.main(["--help"])
    assert seen.get("unicode") is False
    assert ui.detect_unicode(io.StringIO()) is True


def test_spinner_is_ascii_when_symbols_are():
    c = Console(out=io.StringIO(), plain=True, unicode=False)
    assert c.sym["ok"] == "[done]"
    assert dashboard.spinner_name(c) == "line"
    assert dashboard.spinner_name(Console(out=io.StringIO(), plain=True, unicode=True)) == "dots"


# 3 + 10 ---- keys
class FakeMsvcrt:
    def __init__(self, hits, chars):
        self.hits, self.chars, self.polls = list(hits), list(chars), 0

    def kbhit(self):
        self.polls += 1
        return self.hits.pop(0) if self.hits else True

    def getwch(self):
        assert self.polls, "getwch called without checking kbhit first (Ctrl+C would be ignored)"
        return self.chars.pop(0)


def test_windows_reader_polls_instead_of_blocking(monkeypatch):
    fake = FakeMsvcrt([False, False, False, True], ["\r"])
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    sleeps = []
    monkeypatch.setattr(keys.time, "sleep", lambda s: sleeps.append(s))
    assert keys._read_windows(None) == "enter"
    assert len(sleeps) == 3 and max(sleeps) <= 0.06


def test_windows_accented_letter_does_not_hang(monkeypatch):
    fake = FakeMsvcrt([True, False], ["\xe0"])      # a lone lead code: nothing follows
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    assert keys._read_windows(None) == "other"
    assert fake.chars == []
    fake = FakeMsvcrt([True, True], ["\xe0", "H"])  # a real arrow
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    assert keys._read_windows(None) == "up"


def test_posix_session_keeps_raw_mode_for_the_whole_menu(monkeypatch):
    calls = []

    class FakeTermios:
        TCSADRAIN = 1

        @staticmethod
        def tcgetattr(fd):
            return "old"

        @staticmethod
        def tcsetattr(fd, when, attrs):
            calls.append(("restore", attrs))

    class FakeTty:
        @staticmethod
        def setcbreak(fd):
            calls.append(("cbreak",))

    class FakeIn:
        @staticmethod
        def fileno():
            return 0
    monkeypatch.setitem(sys.modules, "termios", FakeTermios)
    monkeypatch.setitem(sys.modules, "tty", FakeTty)
    monkeypatch.setattr(sys, "stdin", FakeIn)
    with pytest.raises(RuntimeError):
        with keys.posix_session():
            assert keys.in_session()
            raise RuntimeError
    assert calls == [("cbreak",), ("restore", "old")] and not keys.in_session()


# 4 ---- export never overwrites the running installer
def test_default_export_name_is_dated():
    p = app.default_export_path()
    assert re.fullmatch(r"statpearls-vault-\d{4}-\d{2}-\d{2}\.pyz", p.name) and p.parent == Path.cwd()


def test_export_refuses_the_running_file(tmp_path, monkeypatch):
    folder = tmp_path / "inst"
    (folder / "data" / "meta").mkdir(parents=True)
    (folder / "data" / "meta" / "installed.json").write_text(json.dumps({"archive_updated": "x", "archive_size": 1}), encoding="utf-8")
    running = tmp_path / "statpearls-vault.pyz"
    running.write_bytes(b"ORIGINAL")
    monkeypatch.setattr(sys, "argv", [str(running)])
    out = io.StringIO()
    c = Console(out=out, inp=lambda p="": "", plain=True, yes=True)
    rc = app.main(["export", str(running), "--folder", str(folder), "--yes"], bundle=app.DirBundle(tmp_path), console=c, use_venv=False)
    assert rc == 1 and running.read_bytes() == b"ORIGINAL"
    assert "running" in out.getvalue().lower() and "unexpected" not in out.getvalue()


# 5 ---- stderr must not print over the panel
def test_stderr_is_routed_through_the_live_display():
    out = io.StringIO()
    c = Console(out=out, plain=False, width=80)
    with dashboard.Dashboard(c, "Installing", Path("C:/V"), "d", ["a"], {1: 1}) as d:
        d.start(1)
        sys.stderr.write("retry 1: timed out\n")
    assert "retry 1: timed out" in ANSI.sub("", out.getvalue())


# 6 ---- reference data progress
def test_mesh_fetch_reports_batches(tmp_path, monkeypatch):
    from src.enrich import mesh
    l1 = tmp_path / "l1"
    l1.mkdir()
    for i in range(1, 4):
        (l1 / f"article-{i}.json").write_text(json.dumps({"id": f"article-{i}", "kind": "live", "title": "T", "references": [{"ids": {"pmid": str(1000 + i)}}]}), encoding="utf-8")
    monkeypatch.setattr(mesh, "BATCH", 2)
    monkeypatch.setattr(mesh, "get", lambda endpoint, **p: b"<PubmedArticleSet/>")
    monkeypatch.setattr(mesh, "_lookup_trees", lambda *a, **k: None)
    got = []
    progress.set_listener(lambda *a: got.append(a))
    try:
        mesh.fetch(str(l1), str(tmp_path / "raw"))
    finally:
        progress.set_listener(None)
    steps = [g for g in got if g[0] == "reference"]
    assert steps and steps[-1][1] == steps[-1][2] == 2 and steps[-1][3] == "batches"


def test_dashboard_labels_reference_data():
    out = io.StringIO()
    c = Console(out=out, plain=True)
    with dashboard.Dashboard(c, "Installing", Path("C:/V"), "d", ["a"] * 6, {}, clock=lambda: 0.0) as d:
        d.start(6)
        progress.tick("reference", 12, 340, "batches")
    assert "Fetching reference data: 12 of 340 batches" in out.getvalue()


# 7 ---- status is capped; one archive-info download per run
def test_status_gives_up_on_a_slow_update_check(tmp_path, monkeypatch):
    folder = tmp_path / "inst"
    (folder / "data" / "meta").mkdir(parents=True)
    (folder / "data" / "meta" / "installed.json").write_text(json.dumps(
        {"archive_updated": "2026-10-25 03:25:13", "archive_size": 1}), encoding="utf-8")
    monkeypatch.setattr(archive, "fetch_info", lambda: time.sleep(10))
    monkeypatch.setattr(app, "UPDATE_CHECK_SECONDS", 0.5)
    out = io.StringIO()
    t0 = time.monotonic()
    rc = app.main(["status", "--folder", str(folder)], bundle=app.DirBundle(tmp_path), console=Console(out=out, plain=True), use_venv=False)
    assert rc == 0 and time.monotonic() - t0 < 4
    assert "unknown (could not reach NLM)" in out.getvalue()


def test_archive_info_is_fetched_once_per_run(tmp_path, monkeypatch):
    calls = []

    def fetch():
        calls.append(1)
        return archive.ArchiveInfo(path="x", updated="2026-11-01 00:00:00", size=5)
    monkeypatch.setattr(archive, "fetch_info", fetch)
    app.forget_latest()
    folder = tmp_path / "inst"
    info = {"archive_updated": "2026-10-25 03:25:13", "archive_size": 1}
    rows, check = app.welcome_state(folder, info)
    check.value(wait=True)
    ctx = app.Ctx(Console(out=io.StringIO(), plain=True), None, folder, type("A", (), {"archive": None})(), False)
    got, local = app.choose_archive(ctx)
    assert got.size == 5 and local is None and len(calls) == 1


# 8 ---- the child cannot start
def test_child_start_failure_restores_hold_open(tmp_path, monkeypatch):
    root = tmp_path / "inst"
    py = env.venv_python(root)
    py.parent.mkdir(parents=True)
    py.write_bytes(b"")
    monkeypatch.setattr(env, "_requirements_text", lambda: "x")
    import hashlib
    (root / ".venv" / ".requirements-hash").write_text(hashlib.sha256(b"x").hexdigest(), encoding="utf-8")

    def boom(*a, **k):
        raise OSError("cannot start")
    monkeypatch.setattr(env.subprocess, "call", boom)
    c = Console(out=io.StringIO(), plain=True, interactive=True)
    c.hold_open = True
    with pytest.raises(UserError) as e:
        env.ensure_venv(root, c, ["status"])
    assert c.hold_open is True and "Traceback" not in e.value.what


# 9 ---- warnings once
def test_child_does_not_repeat_the_parents_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(env, "obsidian_has_vault_open", lambda n: None)
    monkeypatch.setattr(env, "NEEDED_BYTES", 1)
    args = type("A", (), {"archive": None})()

    def run(extra):
        for k, v in extra.items():
            monkeypatch.setenv(k, v)
        out = io.StringIO()
        ctx = app.Ctx(Console(out=out, plain=True), None, tmp_path / "inst", args, False)
        app.preflight(ctx, "update")
        return out.getvalue()
    assert "Could not check whether Obsidian" in run({})
    assert "Could not check whether Obsidian" not in run({"SP_IN_VENV": "1", "SP_WARNED": "1"})


# 11 ---- the build loops that tick write the same bytes with and without a listener
def _build_once(tmp_path, name, listener):
    from src.extract.run import run
    from src.render.build import build
    work = tmp_path / name
    raw = work / "raw"
    raw.mkdir(parents=True)
    shutil.copy(REPO / "tests" / "synthetic" / "article-900001.nxml", raw)
    old = os.getcwd()
    os.chdir(work)
    try:
        for d in ("data/meta", "data/reports", "data/media"):
            Path(d).mkdir(parents=True, exist_ok=True)
        Path("pm.json").write_text("{}", encoding="utf-8")
        run(str(raw), "pm.json", "data/l1", "data/rep.json")
        srcs = {f["src"] for p in Path("data/l1").glob("article-*.json") for f in json.loads(p.read_text(encoding="utf-8")).get("figures", [])}
        Path("data/meta/media_members.json").write_text(json.dumps({s: {"file": s, "size": 3} for s in srcs}), encoding="utf-8")
        for s in srcs:
            Path("data/media", s).write_bytes(b"jpg")
        got = []
        progress.set_listener((lambda *a: got.append(a)) if listener else None)
        try:
            build("data/l1", "vault", "all", "data/media", "data/meta/media_members.json")
        finally:
            progress.set_listener(None)
        files = {p.relative_to("vault").as_posix(): p.read_bytes() for p in Path("vault").rglob("*") if p.is_file()}
        return files, got
    finally:
        os.chdir(old)


def test_build_files_unchanged_by_a_listener(tmp_path):
    plain, _ = _build_once(tmp_path, "a", False)
    listened, got = _build_once(tmp_path, "b", True)
    assert plain and plain == listened
    assert {g[0] for g in got} >= {"notes", "figure-notes", "search"}


def test_legacy_console_keeps_the_rich_ui_with_safe_glyphs():
    out = io.StringIO()
    c = Console(out=out, plain=False, width=80, unicode=False)
    assert c.rich  # code page 850 must not turn the polished interface off
    c.error("Something failed.", "Do this next.", None)
    text = out.getvalue()
    assert "Something failed." in text
    assert not any(ch in text for ch in "╭╮╰╯✓━")  # only glyphs old console fonts have


def test_windows_terminal_or_utf8_means_unicode(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(ui.os, "name", "nt")
    monkeypatch.setenv("WT_SESSION", "x")
    assert ui.detect_unicode(Tty()) is True
