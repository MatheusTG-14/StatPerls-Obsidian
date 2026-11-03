# PyInstaller recipe for statpearls-vault.exe. Written by `python -I sp.py bundle-exe`; compile with build.cmd.
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
    datas=[(os.path.join(here, d), d) for d in ('schema', 'state', 'obsidian-config', 'plugin')],
    hiddenimports=modules(here, "src") + modules(os.path.join(here, "_vendor"), "rich"),
    excludes=["tkinter", "pytest", "pygments", "markdown_it", "IPython", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="statpearls-vault", console=True, upx=False,
          debug=False, strip=False, runtime_tmpdir=None)
