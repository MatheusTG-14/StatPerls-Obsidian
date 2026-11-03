"""Environment checks and bootstrap: Python version, cloud-synced folders, free disk, Obsidian running, private venv."""
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import venv
from importlib import resources
from pathlib import Path

from src.installer.ui import UserError

# Measured 2026-11-03 (DEC-26): clean install 5.3 GB + 2.05 GB archive = 7.4 GB, plus margin.
NEEDED_BYTES = 10 * (1 << 30)

_CLOUD_PARTS = (
    ("onedrive", "OneDrive"), ("dropbox", "Dropbox"), ("google drive", "Google Drive"), ("my drive", "Google Drive"),
    ("googledrive", "Google Drive"), ("icloud drive", "iCloud"), ("iclouddrive", "iCloud"),
    ("mobile documents", "iCloud"), ("com~apple~clouddocs", "iCloud"),  # macOS iCloud Drive
)


def check_python():
    if tuple(sys.version_info[:2]) < (3, 12):
        v = ".".join(str(x) for x in sys.version_info[:3])
        raise UserError(f"This tool needs Python 3.12 or newer, but this is Python {v}.",
                        "Install Python 3.12 or newer from python.org and run the same command with it.")


def cloud_synced(path):
    """Provider name when `path` sits in a cloud-synced folder (rule 2), else None."""
    p = Path(path)
    for part in p.parts:
        low = part.lower()
        for key, name in _CLOUD_PARTS:
            if low.startswith(key):
                return name
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(var)
        if base:
            try:
                p.resolve().relative_to(Path(base).resolve())
                return "OneDrive"
            except ValueError:
                pass
    return None


def free_bytes(path):
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def title_matches(title, vault_name):
    return re.search(rf"(?:^|\s-\s){re.escape(vault_name)} - Obsidian(?: [\w.\-]+)?$", title) is not None


def obsidian_has_vault_open(vault_name):
    """True/False on Windows (window titles); None where it cannot be told."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            titles.append(buf.value)
        return True
    user32.EnumWindows(each, 0)
    return any(title_matches(t, vault_name) for t in titles)


def venv_python(root):
    return Path(root) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _requirements_text():
    return resources.files("src.installer").joinpath("requirements.txt").read_text(encoding="utf-8")


def ensure_venv(root, console, child_args=None, before_exec=None, quiet=False):
    """Make sure we run inside root/.venv with the pinned libraries; otherwise build it and re-run there.

    Returns when already inside; otherwise runs the same command in the venv and exits with its status.
    `before_exec()` (optional) is called once the venv is ready and returns extra environment variables for the child;
    `quiet` leaves all messages to the caller's own display."""
    root = Path(root)
    target = (root / ".venv").resolve()
    if Path(sys.prefix).resolve() == target:
        return
    reqs = _requirements_text()
    marker = target / ".requirements-hash"
    want = hashlib.sha256(reqs.encode("utf-8")).hexdigest()
    py = venv_python(root)
    if not py.exists() or not marker.exists() or marker.read_text(encoding="utf-8") != want:
        if not quiet:
            console.say("Preparing the private Python libraries (needs internet, about a minute)...")
        if not py.exists():
            venv.EnvBuilder(with_pip=True).create(str(target))
        req_file = root / ".venv" / "requirements.txt"
        req_file.write_text(reqs, encoding="utf-8", newline="\n")
        r = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req_file)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            tail = (r.stdout + r.stderr)[-1500:]
            raise UserError("The Python libraries could not be installed.",
                            "Check your internet connection and run the same command again." + "\n" + tail.strip()[-300:])
        marker.write_text(want, encoding="utf-8", newline="\n")
        if not quiet:
            console.done("Libraries are ready")
    extra = before_exec() if before_exec else {}
    held = getattr(console, "hold_open", False)
    if held:  # the copy in the private environment shows the last screen and waits, not this one
        extra["SP_HOLD_OPEN"] = "1"
        console.hold_open = False
    script = str(Path(sys.argv[0]).resolve())
    args = list(sys.argv[1:] if child_args is None else child_args)
    old = signal.signal(signal.SIGINT, signal.SIG_IGN)  # Ctrl+C is handled by the child, which resumes cleanly
    try:
        rc = subprocess.call([str(py), script, *args], env={**os.environ, "SP_IN_VENV": "1", **extra})
    except OSError:
        console.hold_open = held  # this window shows the error and still waits
        raise UserError("The private Python environment could not be started.",
                        f"Delete the folder {target} and run the same command again.") from None
    finally:
        signal.signal(signal.SIGINT, old)
    raise SystemExit(rc)
