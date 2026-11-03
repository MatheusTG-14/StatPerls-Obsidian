import io
import tarfile

import pytest

from src.installer import archive
from tests.httpserver import serve

HEADER = "File,Title,Publisher,Publication Year,Accession ID,Last Updated (YYYY-MM-DD HH:MM:SS)\n"
ROW = "3d/12/statpearls_NBK430685.tar.gz,StatPearls,StatPearls Publishing,2026,NBK430685,2026-10-25 03:25:13\n"
OTHER = 'ca/84/gene_NBK1116.tar.gz,GeneReviews&#174;,"University of Washington, Seattle",1993,NBK1116,2026-10-25 03:29:28\n'


def test_find_archive_dedupes():
    info = archive.find_archive(HEADER + OTHER + ROW + ROW)
    assert info.path == "3d/12/statpearls_NBK430685.tar.gz"
    assert info.updated == "2026-10-25 03:25:13"
    assert info.size is None


def test_find_archive_missing():
    with pytest.raises(archive.ArchiveError) as e:
        archive.find_archive(HEADER + OTHER)
    assert "StatPearls is not in NLM's file list" in str(e.value)


def test_fetch_info_uses_row_and_content_length(tmp_path, monkeypatch):
    (tmp_path / "3d" / "12").mkdir(parents=True)
    (tmp_path / "3d" / "12" / "statpearls_NBK430685.tar.gz").write_bytes(b"x" * 1234)
    (tmp_path / "file_list.csv").write_text(HEADER + ROW, encoding="utf-8")
    base, log, stop = serve(tmp_path)
    monkeypatch.setenv("SP_LITARCH_BASE", base)
    try:
        info = archive.fetch_info()
    finally:
        stop()
    assert info.size == 1234 and info.updated == "2026-10-25 03:25:13"
    assert archive.archive_url(info) == base + "3d/12/statpearls_NBK430685.tar.gz"


def _payload():
    return bytes(range(256)) * 4096  # 1 MiB


def test_download_resumes(tmp_path):
    data = _payload()
    srv = tmp_path / "srv"
    srv.mkdir()
    (srv / "a.bin").write_bytes(data)
    base, log, stop = serve(srv)
    dest = tmp_path / "out" / "a.bin"
    dest.parent.mkdir()
    part = dest.with_suffix(".part")
    part.write_bytes(data[: len(data) * 4 // 10])
    seen = []
    try:
        archive.download(base + "a.bin", dest, len(data), lambda d, t: seen.append((d, t)))
    finally:
        stop()
    assert dest.read_bytes() == data and not part.exists()
    assert any(m == "GET" and r == f"bytes={len(data) * 4 // 10}-" for m, _, r in log)
    assert seen[-1] == (len(data), len(data))


def test_download_restarts_when_server_ignores_range(tmp_path):
    data = _payload()
    srv = tmp_path / "srv"
    srv.mkdir()
    (srv / "a.bin").write_bytes(data)
    base, log, stop = serve(srv, ignore_range=True)
    dest = tmp_path / "a.bin"
    dest.with_suffix(".part").write_bytes(b"junk" * 1000)
    try:
        archive.download(base + "a.bin", dest, len(data), lambda d, t: None)
    finally:
        stop()
    assert dest.read_bytes() == data


def test_download_size_mismatch_raises(tmp_path):
    data = _payload()
    srv = tmp_path / "srv"
    srv.mkdir()
    (srv / "a.bin").write_bytes(data)
    base, log, stop = serve(srv)
    dest = tmp_path / "a.bin"
    try:
        with pytest.raises(archive.ArchiveError):
            archive.download(base + "a.bin", dest, len(data) + 5, lambda d, t: None)
    finally:
        stop()
    assert not dest.exists()


def test_download_skips_when_already_complete(tmp_path):
    dest = tmp_path / "a.bin"
    dest.write_bytes(b"12345")
    archive.download("http://127.0.0.1:1/never", dest, 5, lambda d, t: None)  # no network touched
    assert dest.read_bytes() == b"12345"


def test_extract_only_nxml(tmp_path):
    tar = tmp_path / "a.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        for name, body in [("statpearls_NBK1/a.nxml", b"<x/>"), ("statpearls_NBK1/b.jpg", b"JPG"), ("statpearls_NBK1/sub/c.NXML".lower(), b"<y/>")]:
            ti = tarfile.TarInfo(name)
            ti.size = len(body)
            t.addfile(ti, io.BytesIO(body))
    out = tmp_path / "out"
    n = archive.extract_articles(tar, out)
    assert n == 2 and sorted(p.name for p in out.iterdir()) == ["a.nxml", "c.nxml"]
    assert archive.extract_articles(tar, out) == 2  # idempotent; existing equal-size files are skipped
