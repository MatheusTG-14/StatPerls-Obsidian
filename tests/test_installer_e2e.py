"""End-to-end: install, then update, against a fake LitArch server and stubbed E-utilities (no real network)."""
import gzip
import io
import json
import re
import tarfile
from pathlib import Path

import pytest

from src.installer import app, env
from src.installer.ui import Console
from tests.httpserver import serve

SYN = Path(__file__).parent / "synthetic" / "article-900001.nxml"
TITLES = {900001: "Synthetic Alpha Disease: Test", 900002: "Synthetic Beta Disease: Test",
          900003: "Synthetic Gamma Disease: Test", 900004: "Synthetic Delta Disease: Test"}
HEADER = "File,Title,Publisher,Publication Year,Accession ID,Last Updated (YYYY-MM-DD HH:MM:SS)\n"


def nxml(n, extra="", swap=False):
    s = SYN.read_text(encoding="utf-8").replace("article-900001", f"article-{n}").replace("Synthetic Disease: Test", TITLES[n])
    if swap:  # same byte length, different text
        s = s.replace("Synthetic Other Topic", "Synthetic Other Tapic")
    return s.replace("a | pipe.", f"a | pipe.{extra}").encode("utf-8")


def make_tar(path, numbers, changed=(), swapped=()):
    with tarfile.open(path, "w:gz") as t:
        members = [(f"statpearls_NBK430685/article-{n}.nxml", nxml(n, " Changed text." if n in changed else "", n in swapped)) for n in numbers]
        members += [("statpearls_NBK430685/Case_Image.jpg", b"JPG-A"), ("statpearls_NBK430685/case_image.jpg", b"JPG-B"),
                    ("statpearls_NBK430685/clip.mp4", b"MP4")]
        for name, body in members:
            ti = tarfile.TarInfo(name)
            ti.size = len(body)
            t.addfile(ti, io.BytesIO(body))


def publish(lit, numbers, updated, changed=(), swapped=()):
    (lit / "3d" / "12").mkdir(parents=True, exist_ok=True)
    make_tar(lit / "3d" / "12" / "statpearls_NBK430685.tar.gz", numbers, changed, swapped)
    (lit / "file_list.csv").write_text(
        HEADER + f"3d/12/statpearls_NBK430685.tar.gz,StatPearls,StatPearls Publishing,2026,NBK430685,{updated}\n", encoding="utf-8")


def make_bundle(tmp_path):
    b = tmp_path / "bundle"
    files = {
        "state/registry.json": "{}", "state/pubmed_map.json": "{}", "state/content_hashes.json": "{}",
        "schema/overrides/system.yaml": "{}\n",
        "obsidian-config/app.json": '{"userIgnoreFilters": ["StatPearls/_meta/"]}',
        "obsidian-config/community-plugins.json": '["statpearls"]',
        "obsidian-config/snippets/statpearls.css": "/* css */",
        "plugin/main.js": "// plugin", "plugin/manifest.json": '{"id": "statpearls"}',
    }
    for name, body in files.items():
        p = b / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return app.DirBundle(b)


def eutils_book_xml(numbers):
    books = "".join(
        f'<PubmedBookArticle><BookDocument><PMID>{9000 + n}</PMID><ArticleIdList><ArticleId IdType="bookaccession">NBK{n}</ArticleId></ArticleIdList>'
        f'<ArticleTitle part="article-{n}">{TITLES[n]}</ArticleTitle></BookDocument></PubmedBookArticle>' for n in numbers)
    return f"<PubmedBookArticleSet>{books}</PubmedBookArticleSet>".encode("utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch):
    from src.acquire import eutils
    from src.enrich import mesh
    lit = tmp_path / "lit"
    publish(lit, [900001, 900002, 900003], "2026-10-25 03:25:13")
    base, log, stop = serve(lit)
    monkeypatch.setenv("SP_LITARCH_BASE", base)
    state = {"numbers": [900001, 900002, 900003]}

    def fake_eutils(endpoint, **params):
        if endpoint == "esearch.fcgi":
            return f"<eSearchResult><Count>{len(state['numbers'])}</Count><WebEnv>w</WebEnv><QueryKey>1</QueryKey></eSearchResult>".encode()
        return eutils_book_xml(state["numbers"])
    monkeypatch.setattr(eutils, "get", fake_eutils)
    monkeypatch.setattr(mesh, "get", lambda endpoint, **p: b"<PubmedArticleSet/>")
    monkeypatch.setattr(env, "obsidian_has_vault_open", lambda name: False)
    monkeypatch.setattr(env, "NEEDED_BYTES", 1)
    out = io.StringIO()
    console = Console(out=out, inp=lambda prompt="": "", color=False, yes=True)
    yield {"lit": lit, "state": state, "bundle": make_bundle(tmp_path), "console": console, "out": out, "log": log}
    stop()


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.stat().st_mtime_ns for p in Path(folder).rglob("*") if p.is_file()}


@pytest.mark.slow
def test_install_then_update(tmp_path, world):
    folder = tmp_path / "Vault ç dir"
    rc = app.main(["install", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False)
    assert rc == 0, world["out"].getvalue()
    vault = folder / "vault"
    notes = sorted((vault / "StatPearls" / "Articles").rglob("*.md"))
    assert len(notes) == 3
    assert (vault / "StatPearls" / "Hubs" / "Home (hub).md").exists()
    assert (vault / ".obsidian" / "app.json").exists() and (vault / ".obsidian" / "plugins" / "statpearls" / "main.js").exists()
    assert (vault / "Mine").is_dir()
    assert all("status/auto-classified" in n.read_text(encoding="utf-8") for n in notes)
    assert (vault / "StatPearls" / "Hubs" / "Auto-classified.base").exists()
    rep = json.loads((folder / "data" / "reports" / "update.json").read_text(encoding="utf-8"))
    assert rep["new"] == ["article-900001", "article-900002", "article-900003"]
    inst = json.loads((folder / "data" / "meta" / "installed.json").read_text(encoding="utf-8"))
    assert inst["archive_updated"] == "2026-10-25 03:25:13"

    # the user works in the vault
    stem1 = next(n for n in notes if "Alpha" in n.name)
    (vault / "Mine").mkdir(exist_ok=True)
    mine = vault / "Mine" / "note.md"
    mine.write_text("Study [[" + next(n.stem for n in notes if "Gamma" in n.name) + "]] later.\n", encoding="utf-8")
    appjson = vault / ".obsidian" / "app.json"
    appjson.write_text('{"mine": true}', encoding="utf-8")
    from src.render import hubs
    target = vault / "StatPearls" / "Articles" / hubs.FOLDER["cardiovascular"]
    target.mkdir(parents=True, exist_ok=True)
    moved = target / stem1.name
    stem1.rename(moved)
    mine_bytes, app_bytes = mine.read_bytes(), appjson.read_bytes()

    # NLM publishes a new archive: 900002 changed, 900003 removed, 900004 added
    publish(world["lit"], [900001, 900002, 900004], "2026-11-20 01:00:00", changed=(900002,))
    world["state"]["numbers"] = [900001, 900002, 900004]
    rc = app.main(["update", "--folder", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False)
    assert rc == 0, world["out"].getvalue()
    assert mine.read_bytes() == mine_bytes and appjson.read_bytes() == app_bytes
    assert "article-900001" in (folder / "schema" / "overrides" / "system.yaml").read_text(encoding="utf-8")
    assert moved.exists() and not stem1.exists()  # filename unchanged, the user's move kept
    rep = json.loads((folder / "data" / "reports" / "update.json").read_text(encoding="utf-8"))
    assert rep["new"] == ["article-900004"] and rep["changed"] == ["article-900002"] and rep["deleted"] == ["article-900003"]
    assert ["Mine/note.md", next(n.stem for n in notes if "Gamma" in n.name)] in rep["dangling_mine_links"]
    assert list((folder / "backups").iterdir())

    before = snapshot(folder)
    world["out"].truncate(0)
    rc = app.main(["update", "--folder", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False)
    assert rc == 0 and "Already up to date" in world["out"].getvalue()
    assert snapshot(folder) == before


def test_update_refuses_when_obsidian_open(tmp_path, world, monkeypatch):
    folder = tmp_path / "inst"
    (folder / "data" / "meta").mkdir(parents=True)
    (folder / "data" / "meta" / "installed.json").write_text(json.dumps({"archive_updated": "old", "archive_size": 1}), encoding="utf-8")
    monkeypatch.setattr(env, "obsidian_has_vault_open", lambda name: True)
    before = snapshot(folder)
    rc = app.main(["update", "--folder", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False)
    assert rc == 1 and "Obsidian" in world["out"].getvalue() and "Traceback" not in world["out"].getvalue()
    assert {k: v for k, v in snapshot(folder).items() if not k.startswith("logs/")} == before


def test_update_without_install_says_so(tmp_path, world):
    rc = app.main(["update", "--folder", str(tmp_path / "nothing"), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False)
    assert rc == 1 and "install" in world["out"].getvalue().lower()
    assert not (tmp_path / "nothing").exists()


def test_install_refuses_cloud_folder(tmp_path, world):
    rc = app.main(["install", str(tmp_path / "OneDrive" / "v"), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False)
    assert rc == 1 and "OneDrive" in world["out"].getvalue()
    assert not (tmp_path / "OneDrive").exists()


def test_help_lists_commands(capsys):
    with pytest.raises(SystemExit) as e:
        app.main(["--help"])
    assert e.value.code == 0
    text = capsys.readouterr().out
    for cmd in ("install", "update", "status", "export"):
        assert cmd in text


def test_prepare_limited_to_flagged(tmp_path):
    from src.enrich.tagging import prepare_tags
    l1 = tmp_path / "l1"
    l1.mkdir()
    side = {}
    for i in ("article-1", "article-2", "article-3"):
        (l1 / f"{i}.json").write_text(json.dumps({
            "id": i, "kind": "live", "title": f"T {i}", "sections": [{"title": "Etiology", "blocks": []}]}), encoding="utf-8")
        side[i] = {"primary": "cardiovascular", "sub": None}
    (tmp_path / "system.json").write_text(json.dumps(side), encoding="utf-8")
    out = tmp_path / "out"
    prepare_tags(str(tmp_path / "system.json"), str(l1), str(out), only={"article-2"})
    ids = [json.loads(line)["id"] for f in out.glob("*.jsonl") for line in f.read_text(encoding="utf-8").splitlines()]
    assert ids == ["article-2"]


@pytest.mark.slow
def test_update_detects_same_size_change(tmp_path, world):
    folder = tmp_path / "inst"
    assert app.main(["install", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False) == 0
    publish(world["lit"], [900001, 900002, 900003], "2026-11-20 01:00:00", swapped=(900002,))
    assert app.main(["update", "--folder", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False) == 0
    rep = json.loads((folder / "data" / "reports" / "update.json").read_text(encoding="utf-8"))
    assert rep["changed"] == ["article-900002"] and rep["new"] == [] and rep["deleted"] == []
    note = next((folder / "vault" / "StatPearls" / "Articles").rglob("*Beta*.md"))
    assert "Synthetic Other Tapic" in note.read_text(encoding="utf-8")


@pytest.mark.slow
def test_interrupted_build_does_not_harvest_its_own_placements(tmp_path, world, monkeypatch):
    import inspect
    from src.render.names import Registry
    folder = tmp_path / "inst"
    assert app.main(["install", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False) == 0
    system = folder / "schema" / "overrides" / "system.yaml"
    system.write_bytes(b"article-900002: eye   # hand-made, not a user move\n")
    real_save = Registry.save

    def interrupted(self):
        if any(f.function == "build" for f in inspect.stack()):
            raise KeyboardInterrupt
        return real_save(self)
    monkeypatch.setattr(Registry, "save", interrupted)
    rc = app.main(["update", "--force", "--folder", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False)
    assert rc == 130
    monkeypatch.setattr(Registry, "save", real_save)
    before = system.read_bytes()
    rc = app.main(["update", "--force", "--folder", str(folder), "--yes"], bundle=world["bundle"], console=world["console"], use_venv=False)
    assert rc == 0, world["out"].getvalue()
    assert system.read_bytes() == before  # harvest was skipped: nothing was recorded as a user move


def test_plan_confirmed_before_step_1(tmp_path, world, monkeypatch):
    calls = []
    monkeypatch.setattr(env, "ensure_venv", lambda *a, **k: calls.append(a))
    out = io.StringIO()
    asked = []
    console = Console(out=out, inp=lambda prompt="": (asked.append(prompt), "n")[1], plain=True)
    folder = tmp_path / "inst"
    rc = app.main(["install", str(folder)], bundle=world["bundle"], console=console, use_venv=True)
    assert rc == 1 and "Cancelled" in out.getvalue()
    assert any("Continue?" in a for a in asked)
    assert not calls and not folder.exists()
    assert "Step 1 of 8" not in out.getvalue()


@pytest.mark.slow
@pytest.mark.parametrize("plain", [False, True])
def test_child_does_not_ask_again(tmp_path, world, monkeypatch, plain):
    monkeypatch.setenv("SP_IN_VENV", "1")
    monkeypatch.setenv("SP_PLAN_CONFIRMED", "1")
    monkeypatch.setenv("SP_DONE_STEPS", "1:3.0,2:61.0")
    out = io.StringIO()

    def no_questions(prompt=""):
        raise AssertionError("asked: " + prompt)
    console = Console(out=out, inp=no_questions, plain=plain, width=100)
    rc = app.main(["install", str(tmp_path / "inst")], bundle=world["bundle"], console=console, use_venv=False)
    text = re.sub(r"\[[0-9;?]*[A-Za-z]", "", out.getvalue())
    assert rc == 0, text
    assert "Continue?" not in text
    if plain:
        assert "Step 1 of 8" not in text and "Step 3 of 8" in text   # the parent already printed steps 1 and 2 in this window
    else:
        assert "Checking this computer" in text and "3 s" in text and "1 min 1 s" in text  # shown done, with the first process's times
