"""The Windows .exe (DEC-28): write a folder that compiles on its own, then compile it with PyInstaller.

The folder holds exactly what the .pyz carries (bundle.collect: code, Rich, vocabularies, corrections, state, Obsidian
settings, plugin) plus the recipe: entry.py, statpearls-vault.spec, build-requirements.txt and build.cmd. Python is
needed only on the computer that compiles; the .exe carries its own. The folder names article titles: keep it private.
"""
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from src.installer import bundle

MARKER = ".statpearls-exe-source"  # only a folder carrying this file is ever emptied
PYINSTALLER = "6.22.2"
DATA_DIRS = ("schema", "state", "obsidian-config", "plugin")

SPEC = '''# PyInstaller recipe for statpearls-vault.exe. Written by `python -I sp.py bundle-exe`; compile with build.cmd.
import os

here = os.path.abspath(SPECPATH)


def modules(base, package):
    """Every module of a package folder, so imports made inside functions are never missed."""
    out = []
    for dirpath, _dirs, files in os.walk(os.path.join(base, package)):
        rel = os.path.relpath(dirpath, base).replace(os.sep, ".")
        out += [rel + "." + f[:-3] if f != "__init__.py" else rel for f in sorted(files) if f.endswith(".py")]
    return sorted(out)


a = Analysis(
    [os.path.join(here, "entry.py")],
    pathex=[here, os.path.join(here, "_vendor")],
    datas=[(os.path.join(here, d), d) for d in %(data_dirs)r],
    hiddenimports=modules(here, "src") + modules(os.path.join(here, "_vendor"), "rich"),
    excludes=["tkinter", "pytest", "pygments", "markdown_it", "IPython", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="statpearls-vault", console=True, upx=False,
          debug=False, strip=False, runtime_tmpdir=None)
'''

BUILD_CMD = r'''@echo off
rem Compiles dist\statpearls-vault.exe from this folder. Python 3.12+ is needed on this computer only for compiling.
setlocal
cd /d "%~dp0"
if not exist .build-venv\Scripts\python.exe (
  python -m venv .build-venv || goto :fail
)
.build-venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r build-requirements.txt || goto :fail
.build-venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath .build statpearls-vault.spec || goto :fail
echo.
echo Built %~dp0dist\statpearls-vault.exe
exit /b 0
:fail
echo.
echo The build failed; the messages above say why.
exit /b 1
'''

README = '''# StatPearls vault: compilable source of the Windows .exe

Everything statpearls-vault.exe is made from, written by `python -I sp.py bundle-exe` in the development repository.
It holds the same code and data as statpearls-vault.pyz (no StatPearls text, but article titles in state/registry.json):
keep this folder private, like the .exe.

- `build.cmd` compiles `dist\\statpearls-vault.exe` (needs Python 3.12+ and internet for the pinned build tools in
  `build-requirements.txt`; they go into `.build-venv` here, nothing is installed system-wide).
- `python entry.py` runs the same program from source, for testing.
- `statpearls-vault.spec` is the PyInstaller recipe; `src/`, `schema/`, `state/`, `obsidian-config/`, `plugin/` and
  `_vendor/rich` are the program and its data.

Do not edit files here: change the repository and run `bundle-exe` again (it replaces this folder).
'''


def requirements():
    return (Path(__file__).with_name("requirements.txt").read_text(encoding="utf-8").strip().splitlines()
            + [f"pyinstaller=={PYINSTALLER}", "certifi==2026.10.23"])  # certifi: CA bundle for the frozen build on macOS


def stage(root, dest):
    """Write the compilable folder `dest` (replacing an earlier one). -> {relative path: size}."""
    dest = Path(dest)
    if dest.exists():
        if not (dest / MARKER).is_file():
            raise SystemExit(f"{dest} exists and was not written by bundle-exe; choose an empty or new folder")
        for p in dest.iterdir():  # keep the build caches; everything else is written afresh
            if p.name in (".build-venv", ".build"):
                continue
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    files = bundle.collect(root)
    files["entry.py"] = files.pop("__main__.py")
    files["statpearls-vault.spec"] = (SPEC % {"data_dirs": DATA_DIRS}).encode("utf-8")
    files["build.cmd"] = BUILD_CMD.replace("\n", "\r\n").encode("ascii")  # cmd.exe wants CRLF
    files["build-requirements.txt"] = ("\n".join(requirements()) + "\n").encode("utf-8")
    files["README.md"] = README.encode("utf-8")
    files[MARKER] = b"written by sp.py bundle-exe\n"
    for name, data in files.items():
        p = dest / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return {n: len(files[n]) for n in sorted(files)}


def check_build_python():
    """This Python must hold the pinned libraries and PyInstaller: they go into the .exe as they are."""
    wrong = []
    for line in requirements():
        name, want = line.split("==")
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            have = None
        if have != want:
            wrong.append(f"{name} {have or 'missing'} (needs {want})")
    if wrong:
        raise SystemExit("cannot compile with this Python: " + ", ".join(wrong)
                         + "; run build.cmd in the source folder instead, which sets up its own tools")


def build(root, out, source):
    """Write the source folder, compile it with this Python, put the .exe at `out`. -> (exe size, files staged)."""
    manifest = stage(root, source)
    check_build_python()
    source, out = Path(source).resolve(), Path(out).resolve()
    dist = source / "dist"
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
                        "--distpath", str(dist), "--workpath", str(source / ".build"), str(source / "statpearls-vault.spec")],
                       cwd=source)
    if r.returncode:
        raise SystemExit(f"PyInstaller failed ({r.returncode})")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    shutil.copyfile(dist / "statpearls-vault.exe", tmp)
    tmp.replace(out)
    return out.stat().st_size, len(manifest)
