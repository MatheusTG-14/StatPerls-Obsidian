"""NLM LitArch archive: look up the StatPearls row, download with resume, unpack the article files.

Only the FTP service's HTTPS mirror (ftp.ncbi.nlm.nih.gov/pub/litarch/) is used (rule 1).
"""
import csv
import io
import os
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from src import progress
from src.installer.ui import UserError

DEFAULT_BASE = "https://ftp.ncbi.nlm.nih.gov/pub/litarch/"
BASE_URL = DEFAULT_BASE
ACCESSION = "NBK430685"
CHUNK = 1 << 20
UA = {"User-Agent": "statpearls-vault"}


class ArchiveError(UserError):
    """Plain-English problem with the archive; the message says what to do."""

    def __init__(self, what, todo="", log=True):
        super().__init__(what, todo, log)


@dataclass(frozen=True)
class ArchiveInfo:
    path: str
    updated: str
    size: int | None = None


def base_url():
    return os.environ.get("SP_LITARCH_BASE", DEFAULT_BASE)


def archive_url(info):
    return base_url() + info.path


def find_archive(file_list_csv, accession=ACCESSION):
    rows = {(r["File"], r["Last Updated (YYYY-MM-DD HH:MM:SS)"])
            for r in csv.DictReader(io.StringIO(file_list_csv)) if r.get("Accession ID") == accession}
    if not rows:
        raise ArchiveError("StatPearls is not in NLM's file list right now. Check your internet connection and try again later; "
                           "if it keeps happening NLM may have moved the archive.")
    path, updated = sorted(rows, key=lambda r: r[1])[-1]
    return ArchiveInfo(path=path, updated=updated, size=None)


def _open(url, method="GET", headers=None, timeout=60):
    req = urllib.request.Request(url, method=method, headers={**UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_info():
    try:
        with _open(base_url() + "file_list.csv", timeout=120) as r:
            text = r.read().decode("utf-8", errors="replace")
        info = find_archive(text)
        with _open(archive_url(info), method="HEAD") as r:
            size = int(r.headers["Content-Length"])
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        raise ArchiveError(f"Could not reach NLM to check the StatPearls archive ({e}). Check your internet connection and try again.") from e
    return ArchiveInfo(info.path, info.updated, size)


def download(url, dest, size, progress):
    """Resumable download of `url` to `dest` (exact `size` bytes). Interrupted runs continue from dest.with_suffix('.part')."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size == size:
        progress(size, size)
        return
    part = dest.with_suffix(".part")
    for attempt in range(1, 6):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have < size:
            try:
                with _open(url, headers={"Range": f"bytes={have}-"} if have else None) as r:
                    if have and r.status != 206:  # server ignored Range: start over
                        have = 0
                    with open(part, "ab" if have else "wb") as fo:
                        done = have
                        while True:
                            chunk = r.read(CHUNK)
                            if not chunk:
                                break
                            fo.write(chunk)
                            done += len(chunk)
                            progress(done, size)
            except urllib.error.HTTPError as e:
                raise ArchiveError(f"NLM refused the download (HTTP {e.code}). Try again later.") from e
            except (urllib.error.URLError, OSError, ConnectionError) as e:
                if attempt == 5:
                    raise ArchiveError("The download was interrupted. Run the same command again to resume where it stopped.") from e
                time.sleep(2 * attempt)
                continue
        break
    got = part.stat().st_size if part.exists() else 0
    if got != size:
        if got > size or got == 0:
            part.unlink(missing_ok=True)
        raise ArchiveError(f"The download is the wrong size ({got} bytes, expected {size}). Run the same command again to retry.")
    part.replace(dest)


def extract_articles(tar_path, dest_dir):
    """One streaming pass over the gzip; writes only *.nxml members, flattened into dest_dir. -> count."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    seen = set()
    with tarfile.open(tar_path, "r|gz") as tf:
        for m in tf:
            if not (m.isfile() and m.name.lower().endswith(".nxml")):
                continue
            n += 1
            progress.tick("unpack", n, 0, "article files")
            seen.add(Path(m.name).name)
            out = dest / Path(m.name).name
            with tf.extractfile(m) as fh:
                data = fh.read()
            if out.exists() and out.stat().st_size == len(data) and out.read_bytes() == data:
                continue  # same bytes (an interrupted run resumes here); same size alone is not proof of the same text
            tmp = out.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(out)
    for old in dest.glob("*.nxml"):  # files from an earlier archive that NLM has since removed
        if old.name not in seen:
            old.unlink()
    progress.tick("unpack", n, n, "article files")
    return n
