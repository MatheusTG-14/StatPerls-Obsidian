from src import progress


def test_tick_is_noop_without_listener():
    progress.set_listener(None)
    progress.tick("read", 1, 10, "articles")  # must not raise
    with progress.stage("search"):
        pass


def test_tick_throttles():
    got = []
    progress.set_listener(lambda *a: got.append(a))
    try:
        for k in range(1, 1001):
            progress.tick("notes", k, 1000, "notes")
    finally:
        progress.set_listener(None)
    assert len(got) <= 25
    assert got[-1][1] == got[-1][2] == 1000


def test_stage_announces_start_and_end():
    got = []
    progress.set_listener(lambda *a: got.append(a))
    try:
        with progress.stage("search"):
            pass
    finally:
        progress.set_listener(None)
    assert got[0][:2] == ("search", 0) and got[-1][1] == got[-1][2]


def test_a_broken_listener_never_stops_the_pipeline():
    def bad(*a):
        raise RuntimeError("display")
    progress.set_listener(bad)
    try:
        progress.tick("read", 1, 1)
    finally:
        progress.set_listener(None)


def test_build_bytes_unchanged_with_listener():
    from pathlib import Path
    from src.extract.nxml import extract
    from src.render import markdown as md
    from src.render.build import render_article
    from src.render.links import TitleIndex
    from src.render.names import Registry
    from src.render.build import Media
    rec = extract(Path(__file__).parent / "synthetic" / "article-900001.nxml")

    def render():
        ctx = md.Ctx(rec["id"], TitleIndex([]), {})
        media = Media({rec["id"]: rec}, Registry(Path("nonexistent-registry.json")), {f["src"]: {"file": "x.jpg"} for f in rec["figures"]})
        return render_article(rec, "Stem", ctx, media, "disease", ("cardiovascular", [], "r", None, {}, False))
    plain = render()
    progress.set_listener(lambda *a: None)
    try:
        listened = render()
    finally:
        progress.set_listener(None)
    assert plain == listened


def test_extract_reports_reading(tmp_path):
    import json
    import shutil
    from pathlib import Path
    from src.extract.run import run
    raw = tmp_path / "raw"
    raw.mkdir()
    shutil.copy(Path(__file__).parent / "synthetic" / "article-900001.nxml", raw)
    (tmp_path / "pm.json").write_text("{}", encoding="utf-8")
    got = []
    progress.set_listener(lambda *a: got.append(a))
    try:
        run(str(raw), str(tmp_path / "pm.json"), str(tmp_path / "l1"), str(tmp_path / "rep.json"))
    finally:
        progress.set_listener(None)
    assert got and got[-1][:3] == ("read", 1, 1)
