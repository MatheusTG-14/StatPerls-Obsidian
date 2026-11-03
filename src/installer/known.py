"""Vault folders this computer has used, so the menu finds a vault wherever the .pyz file sits.

A short list of paths in the user profile (%APPDATA%\\StatPearls Vault\\installs.json on Windows); nothing else is
stored there. Standard library only: the menu reads it before the private Python environment exists.
"""
import json
import os
import tempfile
from pathlib import Path

MAX_REMEMBERED = 6  # the picker numbers its entries 1-9, with room for "Another folder..." and "Back"
MARKER = ("data", "meta", "installed.json")


def config_dir():
    if os.environ.get("SP_CONFIG_DIR"):
        return Path(os.environ["SP_CONFIG_DIR"])
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "StatPearls Vault"
    return Path.home() / ".config" / "statpearls-vault"


def _file():
    return config_dir() / "installs.json"


def is_install(folder):
    return Path(folder).joinpath(*MARKER).is_file()


def normalize(path):
    """The install folder for a path the user gave (the install folder itself or its vault folder), else None."""
    p = Path(path).expanduser().resolve()
    if is_install(p):
        return p
    if p.name.lower() == "vault" and is_install(p.parent):
        return p.parent
    return None


def load():
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(x) for x in data.get("folders", []) if isinstance(x, str)][:MAX_REMEMBERED]


def _save(folders):
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".installs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"folders": folders}, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, f)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _same(a, b):
    return os.path.normcase(a) == os.path.normcase(b)


def remember(folder):
    """Put folder first in the list (no duplicates, case-insensitive on Windows). A failure here never matters."""
    s = str(Path(folder).resolve())
    try:
        _save([s] + [x for x in load() if not _same(x, s)][: MAX_REMEMBERED - 1])
    except OSError:
        pass


def forget(folder):
    s = str(Path(folder).resolve())
    try:
        _save([x for x in load() if not _same(x, s)])
    except OSError:
        pass


def first_install():
    """The most recently used remembered folder that is still an installation, else None."""
    return next((Path(x) for x in load() if is_install(x)), None)
