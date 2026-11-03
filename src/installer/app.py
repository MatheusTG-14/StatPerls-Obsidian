"""Commands of the portable installer: install, update, status, export, agent-prepare, agent-collect, menu.

The install folder mirrors the repository layout (schema/overrides, data/, vault/, backups/, logs/, .venv/) so every
existing pipeline stage runs unchanged with the folder as working directory.
"""
import argparse
import contextlib
import datetime
import json
import os
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

from src import stages
from src.installer import archive, env, known, ui
from src.installer.dashboard import Dashboard, typical_for
from src.installer.ui import Console, Pending, UserError, fmt_bytes, fmt_duration, run_safely

VERSION = "1"
FROZEN = bool(getattr(sys, "frozen", False))  # the Windows .exe (DEC-28): Python and the libraries are built in
CORRECTIONS_NAME = "statpearls-vault-corrections.zip"
_latest = {"lock": threading.Lock(), "info": None}


def forget_latest():
    """A new run starts with no remembered archive info (a stale thread keeps its own lock)."""
    global _latest
    _latest = {"lock": threading.Lock(), "info": None}


def latest_info():
    """The archive info from NLM, downloaded once per run and shared by the welcome check, status and the plan."""
    if _latest.get("fn") is not archive.fetch_info:  # a different source (tests) never sees an older answer
        forget_latest()
        _latest["fn"] = archive.fetch_info
    state = _latest
    with state["lock"]:
        if state["info"] is None:
            state["info"] = archive.fetch_info()
        return state["info"]


def program_path():
    """The file the user ran: the .exe, or the .pyz."""
    return Path(sys.executable if FROZEN else sys.argv[0]).resolve()


def prog():
    """How the user runs this program, for messages."""
    return program_path().name if FROZEN else "python statpearls-vault.pyz"


def default_export_path():
    if FROZEN:  # the .exe reads corrections from this name, next to it
        return program_path().parent / CORRECTIONS_NAME
    return Path.cwd() / f"statpearls-vault-{datetime.date.today().isoformat()}.pyz"


UPDATE_CHECK_SECONDS = 4.0  # the menu never waits longer than this for the online check
TOTAL_STEPS = 8
ARCHIVE_NAME = "statpearls_NBK430685.tar.gz"
VAULT_NAME = "vault"
OBSIDIAN_OWN = ("plugins/statpearls/main.js", "plugins/statpearls/manifest.json", "snippets/statpearls.css")
# bundled state name -> install-folder path
STATE_FILES = {
    "state/registry.json": "data/registry.json",
    "state/pubmed_map.json": "data/meta/pubmed_map.json",
    "state/mesh_cache.json.gz": "data/meta/mesh_cache.json.gz",
    "state/content_hashes.json": "data/meta/content_hashes.json",
}


# ---------- what the .pyz carries ----------

class DirBundle:
    """Bundled state read from a directory (tests, development)."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self, name):
        p = self.path / name
        return p.read_bytes() if p.is_file() else None

    def names(self, prefix):
        return sorted(p.relative_to(self.path).as_posix() for p in self.path.rglob("*") if p.is_file()
                      and p.relative_to(self.path).as_posix().startswith(prefix))


class ZipBundle:
    """Bundled state read from the .pyz itself."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self, name):
        with zipfile.ZipFile(self.path) as z:
            try:
                return z.read(name)
            except KeyError:
                return None

    def names(self, prefix):
        with zipfile.ZipFile(self.path) as z:
            return sorted(n for n in z.namelist() if n.startswith(prefix) and not n.endswith("/"))


class LayeredBundle:
    """A corrections file over the built-in data: the first layer that has a file wins."""

    def __init__(self, layers):
        self.layers = layers

    def read(self, name):
        return next((d for d in (b.read(name) for b in self.layers) if d is not None), None)

    def names(self, prefix):
        return sorted({n for b in self.layers for n in b.names(prefix)})


def default_bundle():
    if FROZEN:
        base = DirBundle(sys._MEIPASS)
    else:
        p = Path(sys.argv[0])
        base = ZipBundle(p) if p.is_file() and zipfile.is_zipfile(p) else None
    if base is None:
        return None
    extra = program_path().parent / CORRECTIONS_NAME
    if extra.is_file() and zipfile.is_zipfile(extra):
        return LayeredBundle([ZipBundle(extra), base])
    return base


# ---------- small helpers ----------

class Ctx:
    def __init__(self, console, bundle, root, args, use_venv):
        self.console, self.bundle, self.root, self.args, self.use_venv = console, bundle, Path(root) if root else None, args, use_venv
        self.child = os.environ.get("SP_IN_VENV") == "1"
        self.plan_confirmed = self.child and os.environ.get("SP_PLAN_CONFIRMED") == "1"  # the parent already asked
        self.done_before = parse_done_steps(os.environ.get("SP_DONE_STEPS"))
        self.warned = self.child and os.environ.get("SP_WARNED") == "1"  # the parent already showed the warnings

    def warn_once(self, text):
        if not self.warned:
            self.console.warn(text)

    def p(self, *parts):
        return self.root.joinpath(*parts)

    @property
    def log_path(self):
        return self.p("logs", "installer.log")


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def read_json_file(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_bytes(path, data):
    """Atomic: a Ctrl+C mid-write keeps the old file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json_file(path, obj):
    write_bytes(path, (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))


def human_date(updated):
    try:
        return datetime.datetime.strptime(updated[:10], "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return updated


@contextlib.contextmanager
def pipeline(ctx, label):
    """Run pipeline code with the install folder as working directory; its printed output goes to the log."""
    ctx.log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ctx.log_path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"--- {label} {now_utc().isoformat(timespec='seconds')}\n")
        with stages.working_dir(ctx.root), contextlib.redirect_stdout(fh):
            try:
                yield
            except SystemExit as e:
                if e.code in (0, None):
                    return
                raise UserError(f"A step failed: {e.code}", f"See {ctx.log_path} for details, fix the cause and run the same command again.") from e


def run_stage(ctx, argv):
    with pipeline(ctx, "stage " + " ".join(argv)):
        rc = stages.run(argv)
    return rc


# ---------- preflight ----------

def installed_info(root):
    return read_json_file(Path(root) / "data" / "meta" / "installed.json")


def preflight(ctx, mode):
    env.check_python()
    root = ctx.root
    prov = env.cloud_synced(root)
    if prov:
        raise UserError(f"The folder {root} is inside {prov}, which uploads files to the cloud.",
                        "StatPearls is licensed for private study only and must not be shared or synced. "
                        f"Choose a folder outside it, for example {example_folder()}.", log=False)
    free = env.free_bytes(root)
    if free < env.NEEDED_BYTES:
        raise UserError(f"Not enough free disk space: {fmt_bytes(free)} free, about {fmt_bytes(env.NEEDED_BYTES)} needed.",
                        "Free some space or choose a folder on a bigger drive, then run the same command again.", log=False)
    if mode == "update" or (root / "vault").exists():
        open_ = env.obsidian_has_vault_open(VAULT_NAME)
        if open_:
            raise UserError("Obsidian has this vault open.", "Close Obsidian and run the command again.", log=False)
        if open_ is None:
            ctx.warn_once("Could not check whether Obsidian is running. Make sure it is closed before continuing.")


# ---------- stage bookkeeping (resumable) ----------

def last_build_incomplete(root):
    """True when the previous run started building and did not finish (or no finished build exists)."""
    manifest = Path(root) / "vault" / "StatPearls" / "_meta" / "build-manifest.json"
    if not manifest.exists():
        return True
    data = read_json_file(Path(root) / "data" / "meta" / "stages.json", {})
    done = set(data.get("done", []))
    return "build_started" in done and "build" not in done


class Progress:
    def __init__(self, root, key, fresh):
        self.path = Path(root) / "data" / "meta" / "stages.json"
        data = read_json_file(self.path, {})
        self.key = key
        self.forced = fresh  # a forced run redoes every step once; an interrupted forced run still resumes
        same = data.get("key") == key
        self.done = set(data.get("done", [])) if same and (not fresh or data.get("forced")) else set()

    def is_done(self, name):
        return name in self.done

    def mark(self, name):
        self.done.add(name)
        write_json_file(self.path, {"key": self.key, "done": sorted(self.done), "forced": self.forced})

    def clear(self):
        self.path.unlink(missing_ok=True)


# ---------- archive choice ----------

def choose_archive(ctx, info_hint=None):
    """-> (ArchiveInfo, local tarball Path or None)."""
    local = Path(ctx.args.archive).resolve() if getattr(ctx.args, "archive", None) else None
    if local is not None:
        if not local.is_file():
            raise UserError(f"The archive file {local} was not found.", "Check the path given to --archive.", log=False)
        size = local.stat().st_size
        try:
            info = latest_info()
            if info.size == size:
                return info, local
        except UserError:
            pass
        ctx.warn_once("Could not confirm this file against NLM's list; treating it as a local copy.")
        return archive.ArchiveInfo(path="local", updated=f"local-{size}", size=size), local
    return latest_info(), None


def archive_key(info):
    return f"{info.updated}|{info.size}"


# ---------- shared pipeline ----------

def confirm_plan(ctx, mode, info, local, need_download):
    """The plan panel and "Continue?" -- before any work starts."""
    c = ctx.console
    free = env.free_bytes(ctx.root)
    if local is not None:
        what = f"Use the archive file `{local}` ({fmt_bytes(info.size)}), no download."
        download = "none (your own file)"
    elif need_download:
        what = f"Download the StatPearls archive from NLM ({fmt_bytes(info.size)}, published {human_date(info.updated)})."
        download = fmt_bytes(info.size)
    else:
        what = "The archive is already downloaded."
        download = "none (already downloaded)"
    lines = ["Set up a private Python environment for this tool (a one-time step).", what,
             "Read all articles and build your Obsidian notes (the longest step).",
             "Nothing is uploaded or shared; everything stays in the folder below."]
    if mode == "update":
        lines.insert(0, "Save a backup of your settings and category changes first.")
    table = [("Download", download), ("Disk space", f"about {fmt_bytes(env.NEEDED_BYTES)} needed, {fmt_bytes(free)} free"),
             ("Time", "roughly 20 to 40 minutes"), ("Folder", f"`{ctx.root}`")]
    if not c.plan_panel(lines, table):
        raise UserError("Cancelled. Nothing was changed.", "", log=False)


def step_names(first):
    return ["Checking this computer", "Preparing the Python libraries", "Setting up your folder" if first else "Saving a backup and your changes",
            "Getting the StatPearls archive", "Unpacking articles and figures", "Reading the articles and reference data",
            "Building your notes (the longest step)", "Finishing"]


def parse_done_steps(text):
    """"1:3.0,2:61.5" -> {1: 3.0, 2: 61.5}; anything unreadable is ignored."""
    out = {}
    for part in (text or "").split(","):
        n, _, secs = part.partition(":")
        try:
            out[int(n)] = float(secs)
        except ValueError:
            continue
    return out


def backup_state(ctx):
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    dest = ctx.p("backups", stamp)
    for rel in ("schema/overrides", "data/registry.json", "data/meta"):
        src = ctx.p(*rel.split("/"))
        if src.is_dir():
            shutil.copytree(src, dest / rel, dirs_exist_ok=True)
        elif src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    return dest


def unpack_bundled_state(ctx):
    b = ctx.bundle
    for name, rel in STATE_FILES.items():
        dest = ctx.p(*rel.split("/"))
        data = b.read(name)
        if data is not None and not dest.exists():
            write_bytes(dest, data)
    for name in b.names("schema/overrides/"):
        dest = ctx.p(*name.split("/"))
        if not dest.exists():
            write_bytes(dest, b.read(name))
    ctx.p("vault", "Mine").mkdir(parents=True, exist_ok=True)


def needs_pubmed_refresh(ctx):
    pm = read_json_file(ctx.p("data", "meta", "pubmed_map.json"), {})
    raw = ctx.p(*stages.RAW.split("/"))
    ids = {p.stem.removeprefix("nurse-") for p in raw.glob("*.nxml") if p.name not in ("TOC.nxml", "contributors.nxml")}
    return bool(ids - set(pm))


def refresh_pubmed_map(ctx):
    from src.acquire import eutils
    raw = ctx.p("data", "raw", "eutils")
    raw.mkdir(parents=True, exist_ok=True)
    for old in raw.glob("efetch_*.xml"):
        old.unlink()
    with pipeline(ctx, "pubmed map"):
        eutils.fetch(str(raw))
        eutils.build_map(str(raw), str(ctx.p("data", "meta", "pubmed_map.json")))


def reading_stage(ctx, progress):
    """PubMed map if needed, canonical records, reference data for categories."""
    if progress.is_done("refs"):
        return
    if needs_pubmed_refresh(ctx):
        refresh_pubmed_map(ctx)
    l1 = ctx.p("data", "l1")
    if l1.is_dir():
        for old in l1.glob("*.json"):  # derived data; removed articles must not linger
            old.unlink()
    rc = run_stage(ctx, ["extract"])
    if rc:
        raise UserError("Reading the articles failed.", f"See {ctx.log_path} and run the same command again.")
    from src.enrich import mesh
    with pipeline(ctx, "reference data"):
        mesh.fetch(stages.L1, "data/raw/mesh", cache=stages.MESH_CACHE)
    progress.mark("refs")


def run_pipeline(ctx, mode):
    c, args = ctx.console, ctx.args
    first = mode == "install"
    root = ctx.root
    preflight(ctx, mode)  # refusals come before any question; nothing has been written yet
    info, local = choose_archive(ctx)
    old = installed_info(root)
    if not first:
        if old is None:
            raise UserError("There is no StatPearls vault in this folder yet.", "Run install first.", log=False)
        if not args.force and local is None and old.get("archive_updated") == info.updated and old.get("archive_size") == info.size:
            c.say(f"Already up to date (archive of {human_date(info.updated)}).")
            return 0
    elif old is not None:
        raise UserError("This folder already holds a StatPearls vault.", "Run update instead.", log=False)
    tar = local or ctx.p("data", "raw", "archive", ARCHIVE_NAME)
    need_download = local is None and not (tar.exists() and tar.stat().st_size == info.size)
    if not ctx.plan_confirmed:
        confirm_plan(ctx, mode, info, local, need_download)
    root.mkdir(parents=True, exist_ok=True)
    build_was_interrupted = not first and last_build_incomplete(root)
    progress = Progress(root, archive_key(info), fresh=bool(getattr(args, "force", False)))
    typical = typical_for(info.size if need_download else 0)
    d = Dashboard(c, "Installing" if first else "Updating", root, human_date(info.updated), step_names(first), typical,
                  done_before=ctx.done_before if ctx.child else None, show_done_before=c.rich)
    final = {}

    def hand_over():
        """Called just before the command is re-run inside the private environment: its dashboard continues ours."""
        d.finish(2, "Libraries are ready")
        secs = {n: d.rows[n - 1]["dur"] or 0.0 for n in (1, 2)}
        d.handoff()
        return {"SP_PLAN_CONFIRMED": "1", "SP_WARNED": "1", "SP_DONE_STEPS": ",".join(f"{n}:{s:.1f}" for n, s in secs.items())}

    with d:
        if not ctx.child:
            d.start(1)
            d.finish(1, "This computer is ready")
            d.start(2)
            if ctx.use_venv:
                env.ensure_venv(root, c, ctx.child_args, before_exec=hand_over, quiet=True)  # re-runs this command in the private environment, or returns when already there
            d.finish(2, "Libraries are ready")

        d.start(3)
        if first:
            unpack_bundled_state(ctx)
            d.finish(3, "Folder prepared")
        else:
            backup = backup_state(ctx)
            final["backup"] = backup
            if build_was_interrupted:
                # the half-finished build already wrote notes into new folders that the registry has not pinned yet:
                # harvesting now would record the pipeline's own placements as the user's moves
                d.finish(3, f"Backup saved in {backup}; your category changes were recorded by the earlier run or will be on the next full run")
            else:
                run_stage(ctx, ["harvest"])  # moves made in Obsidian become corrections before anything is rebuilt
                d.finish(3, f"Backup saved in {backup} and your category changes recorded")
        old_hashes = read_json_file(ctx.p("data", "meta", "content_hashes.json"), {})

        d.start(4)
        if local is not None:
            d.finish(4, "Using your local archive file")
        elif progress.is_done("download") and tar.exists():
            d.skip(4, "already downloaded")
        else:
            last = [0.0]

            def prog(done, total):
                if time.time() - last[0] > 0.25 or done == total:
                    last[0] = time.time()
                    d.detail(done, total, "bytes")
            archive.download(archive.archive_url(info), tar, info.size, prog)
            progress.mark("download")
            d.finish(4, "Archive downloaded")

        d.start(5)
        if progress.is_done("unpack"):
            d.skip(5, "already unpacked")
        else:
            raw = ctx.p(*stages.RAW.split("/"))
            n = archive.extract_articles(tar, raw)
            from src.acquire.media import unpack
            with pipeline(ctx, "figures"):
                unpack(str(tar), "data/media", "data/meta/media_members.json", "data/registry.json")
            progress.mark("unpack")
            d.finish(5, f"{n} article files and the figures unpacked")

        d.start(6)
        reading_stage(ctx, progress)
        d.finish(6, "Articles read")

        d.start(7)
        if run_stage(ctx, ["classify"]):
            raise UserError("Sorting the articles into categories failed.", f"See {ctx.log_path} and run the same command again.")
        progress.mark("build_started")
        if run_stage(ctx, ["build", "--all"]):
            raise UserError("Building the notes failed.", f"See {ctx.log_path} and run the same command again.")
        progress.mark("build")
        problems = run_stage(ctx, ["validate"])
        if problems:
            d.warn(f"The final check found problems (details in {ctx.log_path}).")
        d.finish(7, "Notes built")

        d.start(8)
        install_obsidian_files(ctx, first)
        if not first and read_json_file(ctx.p("data", "reports", "moves.json"), {}) and ctx.p("vault", ".obsidian", "bookmarks.json").exists():
            run_stage(ctx, ["migrate-bookmarks"])
        from src.installer import report  # needs yaml/lxml: only after the private environment exists
        l1_index = read_json_file(ctx.p("data", "l1_index.json"), {})
        new_hashes = report.content_hashes(l1_index)
        diff = report.diff(old_hashes, new_hashes)
        sysrep = read_json_file(ctx.p("data", "reports", "system.json"), {})
        titles = {i: e.get("title", "") for i, e in l1_index.items()}
        for i in diff["deleted"]:
            titles.setdefault(i, "")
        rep = report.write_report(ctx.p("data", "reports", "update.json"), diff, sysrep.get("auto_classified", []),
                                  report.dangling_mine_links(ctx.p("vault")), titles)
        write_json_file(ctx.p("data", "meta", "content_hashes.json"), new_hashes)
        write_json_file(ctx.p("data", "meta", "installed.json"), {
            "installer": VERSION, "archive_updated": info.updated, "archive_size": info.size,
            "installed_at": now_utc().isoformat(timespec="seconds"), "articles": len(new_hashes) or len(l1_index),
        })
        progress.clear()
        d.finish(8, "Report written")
        total_time = d.elapsed()

    lines = report.summary_lines(rep)[1:]  # the counts are in the table
    lines += [f"Full report: `{ctx.p('data', 'reports', 'update.json')}`"]
    if final.get("backup"):
        lines.append(f"Backup of your settings: `{final['backup']}`")
    lines.append(f"Total time: {fmt_duration(total_time)}")
    lines += next_steps(ctx, first)
    clean = not problems and not rep["dangling_mine_links"]
    c.done_panel([("New", len(rep["new"])), ("Updated", len(rep["changed"])), ("Removed", len(rep["deleted"])),
                  ("Placed automatically", len(rep["auto_classified"]))], lines, ok=clean)
    return 0


def install_obsidian_files(ctx, first):
    """Install: bundled settings only where absent. Both: the plugin and the style file."""
    dot = ctx.p("vault", ".obsidian")
    b = ctx.bundle
    if first:
        for name in b.names("obsidian-config/"):
            rel = name[len("obsidian-config/"):]
            if rel in OBSIDIAN_OWN:
                continue
            dest = dot / rel
            if not dest.exists():
                write_bytes(dest, b.read(name))
    css = b.read("obsidian-config/snippets/statpearls.css")
    if css is not None:
        write_bytes(dot / "snippets" / "statpearls.css", css)
    for f in ("main.js", "manifest.json"):
        data = b.read("plugin/" + f)
        if data is not None:
            write_bytes(dot / "plugins" / "statpearls" / f, data)


def next_steps(ctx, first):
    vault = ctx.p("vault")
    cmd = f'{prog()} update --folder "{ctx.root}"'
    if first:
        return ["", "Next steps:",
                f"  1. If you have a backup of your own notes, copy it into `{vault / 'Mine'}` (and bookmarks into `.obsidian`).",
                f"  2. Open Obsidian, choose 'Open folder as vault' and pick `{vault}`.",
                "  3. In Settings, Community plugins: turn off Restricted mode and enable StatPearls.",
                "", f"Later, to check for a newer archive: `{cmd}`"]
    return ["", "Next step: open the vault in Obsidian."]


# ---------- commands ----------

def cmd_install(ctx):
    return run_pipeline(ctx, "install")


def cmd_update(ctx):
    return run_pipeline(ctx, "update")


def dir_size(path):
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def cmd_status(ctx):
    c = ctx.console
    info = installed_info(ctx.root) if ctx.root else None
    if info is None:
        c.say("No StatPearls vault found here. Run install first.")
        return 1
    sysrep = read_json_file(ctx.p("data", "reports", "system.json"), {})
    check = Pending(lambda: latest_vs_installed(info), UPDATE_CHECK_SECONDS, unknown="unknown (could not reach NLM)")
    _, newer = check.value(wait=True)
    newer = newer or check.unknown
    articles = info.get("articles")
    rows = [("Folder", f"`{ctx.root}`"), ("Archive", human_date(info["archive_updated"])),
            ("Articles", f"{articles:,}" if isinstance(articles, int) else "unknown"),
            ("Placed automatically", str(len(sysrep.get("auto_classified", [])))),
            ("Last update", human_date(info.get("installed_at", "unknown"))),
            ("Vault size", fmt_bytes(dir_size(ctx.p("vault")))), ("Update available", newer)]
    c.status_table(rows)
    return 0


def cmd_export(ctx):
    """OUT.pyz: a new installer file (from the .pyz only). OUT.zip: a corrections file for the .exe."""
    from src.installer.bundle import bundle, corrections
    c = ctx.console
    out = Path(ctx.args.out).resolve()
    data_only = out.suffix.lower() == ".zip"
    if FROZEN and not data_only:
        raise UserError("The .exe can only write a corrections file (.zip).",
                        f"Choose a name ending in .zip, for example {CORRECTIONS_NAME}.", log=False)
    running = program_path()
    if out == running or (out.exists() and running.exists() and os.path.samefile(out, running)):
        raise UserError("That is the installer file that is running now; writing there would replace it.",
                        f"Choose another file name, for example {default_export_path().name}.", log=False)
    what = ("Write a corrections file (your corrections, category changes, settings and plugin) for the .exe."
            if data_only else "Write a new installer file that carries your corrections and category changes.")
    if not c.plan_panel([what, "It contains article titles, so keep it private."],
                        [("File", f"`{out}`"), ("From", f"`{ctx.root}`")]):
        raise UserError("Cancelled. Nothing was written.", "", log=False)
    c.say("Writing the file...")
    manifest = (corrections if data_only else bundle)(ctx.root, out, None)
    if data_only:
        nxt = [f"On another computer: put it next to statpearls-vault.exe, named {CORRECTIONS_NAME},",
               "then run statpearls-vault.exe install"]
    else:
        nxt = ["On another computer: python statpearls-vault.pyz install"]
    c.done_panel([("Files", len(manifest)), ("Size", fmt_bytes(out.stat().st_size))],
                 [f"Wrote `{out}`", "", "Keep it private: a USB stick or the backups folder, never a cloud folder."] + nxt)
    return 0


def flagged_ids(ctx):
    rep = read_json_file(ctx.p("data", "reports", "system.json"), {})
    ids = set(rep.get("auto_classified", []))
    if not ids:
        raise UserError("No articles are waiting for a closer look.", "Nothing to prepare.", log=False)
    return ids


def agent_prepare_lines(n, folder):
    return [f"Batches for {n} automatically placed articles are in `{folder}`.", "", "Next steps:",
            "  1. Run Claude Code sub-agents on each batch file (they write <batch>.answers.jsonl next to it).",
            f"  2. Run: {prog()} agent-collect MODEL",
            f"  3. Run: {prog()} update --force  to rebuild with the answers."]


def agent_collect_lines():
    return ["The answers are saved in your corrections.", "", "Next steps:",
            f"  1. Run: {prog()} update --force  to rebuild the vault with them."]


def cmd_agent_prepare(ctx):
    ids = flagged_ids(ctx)
    from src.enrich.tagging import prepare_drugs, prepare_tags
    with pipeline(ctx, "agent-prepare"):
        prepare_tags("data/l2/system.json", stages.L1, "data/l2/agent-flagged", only=ids)
        prepare_drugs(stages.L1, "data/l2/agent-flagged-drugs", only=ids)
    ctx.console.done_panel([("Articles", len(ids))], agent_prepare_lines(len(ids), ctx.p("data", "l2")))
    return 0


def cmd_agent_collect(ctx):
    from src.enrich.tagging import collect_drugs, collect_tags
    with pipeline(ctx, "agent-collect"):
        collect_tags("data/l2/agent-flagged", "schema/overrides/tags-agent.yaml", ctx.args.model)
        collect_drugs("data/l2/agent-flagged-drugs", "schema/overrides/drug-class-agent.yaml", ctx.args.model)
    ctx.console.done_panel([], agent_collect_lines())
    return 0


# ---------- entry ----------

def build_parser():
    p = argparse.ArgumentParser(prog=program_path().name if FROZEN else "statpearls-vault.pyz",
                                description="Install, update and report on your private StatPearls vault for Obsidian. "
                                            "With no command, a short menu opens.")
    sub = p.add_subparsers(dest="cmd", metavar="command")
    i = sub.add_parser("install", help="build a new vault in a folder")
    i.add_argument("folder", nargs="?")
    i.add_argument("--archive", help="use a StatPearls archive file you already have instead of downloading it")
    i.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    u = sub.add_parser("update", help="check for a newer archive and rebuild the vault")
    u.add_argument("--folder")
    u.add_argument("--force", action="store_true", help="rebuild even when the archive has not changed")
    u.add_argument("--archive")
    u.add_argument("--yes", action="store_true")
    s = sub.add_parser("status", help="show the installed archive date, counts and whether an update exists")
    s.add_argument("--folder")
    e = sub.add_parser("export", help="write a new .pyz, or a corrections file (.zip), that carries your corrections")
    e.add_argument("out")
    e.add_argument("--folder")
    e.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = sub.add_parser("agent-prepare", help="prepare batches for automatically placed articles")
    a.add_argument("--folder")
    ac = sub.add_parser("agent-collect", help="collect agent answers for those batches")
    ac.add_argument("model")
    ac.add_argument("--folder")
    return p


def find_folder(explicit):
    """--folder (the install folder or its vault folder), else the current folder or the .pyz's folder,
    else the most recently used remembered installation."""
    if explicit:
        return known.normalize(explicit) or Path(explicit).resolve()
    for cand in (Path.cwd(), program_path().parent):
        if known.is_install(cand):
            return cand.resolve()
    return known.first_install()


NOT_AN_INSTALL_TODO = ("Choose the folder that contains the vault and data folders (the vault folder itself also works), "
                       "or run install to create one.")


HELP_COMMANDS = [
    ("install [FOLDER]", "build a new vault in a folder (--archive FILE uses an archive you already have)"),
    ("update", "check for a newer archive and rebuild the vault (--force rebuilds anyway)"),
    ("status", "show the installed archive date, counts and whether an update exists"),
    ("export OUT", "OUT.pyz: a new installer file with your corrections; OUT.zip: a corrections file for the .exe"),
    ("agent-prepare", "prepare batches for articles that were placed automatically"),
    ("agent-collect MODEL", "collect the answers for those batches"),
]
def example_folder():
    return r"C:\StatPearls Vault" if os.name == "nt" else str(Path.home() / "StatPearls Vault")


def help_examples():
    return [f'{prog()} install "{example_folder()}"', f'{prog()} update --folder "{example_folder()}"']


def show_help(console):
    console.help(program_path().name if FROZEN else "statpearls-vault.pyz", "Install, update and report on your private StatPearls vault for Obsidian. "
                 "With no command, a short menu opens. Options: --folder PATH (all commands except install), --yes (no questions), "
                 "--plain (no colours or live display).", HELP_COMMANDS, help_examples())


def main(argv=None, bundle=None, console=None, use_venv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    forget_latest()
    unicode_ok = ui.detect_unicode(sys.stdout)  # before stdout is switched to UTF-8: this is what the console really shows
    plain = "--plain" in argv
    argv = [a for a in argv if a != "--plain"]
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if argv[:1] in (["-h"], ["--help"]):
        show_help(console or Console(plain=True if plain else None, unicode=unicode_ok))
        raise SystemExit(0)
    args = build_parser().parse_args(argv)
    console = console or Console(yes=getattr(args, "yes", False), plain=True if plain else None, unicode=unicode_ok)
    bundle = bundle or default_bundle()
    if use_venv is None:
        use_venv = not FROZEN and default_bundle() is not None and bundle is not None  # the .exe has its libraries built in
    # a window that would vanish (double-click opens the menu) stays until Enter; typed commands and --yes never wait
    handed_down = os.environ.get("SP_HOLD_OPEN") == "1"
    console.hold_open = bool(console.interactive and (args.cmd is None or handed_down))
    if args.cmd is None:
        return menu(console, bundle, use_venv)
    return dispatch(args, console, bundle, use_venv)


def child_argv(args, folder):
    """The command line for the copy that runs inside the private environment: everything already decided
    (command, folder, flags) so the menu and the folder question are not asked twice."""
    cmd, folder = args.cmd, str(folder)
    extra = []
    if cmd == "install":
        out = ["install", folder]
    elif cmd == "update":
        out = ["update", "--folder", folder] + (["--force"] if getattr(args, "force", False) else [])
    elif cmd == "export":
        return ["export", str(Path(args.out).resolve()), "--folder", folder] + (["--yes"] if getattr(args, "yes", False) else [])
    elif cmd == "agent-collect":
        return ["agent-collect", args.model, "--folder", folder]
    else:
        return [cmd, "--folder", folder]
    if getattr(args, "archive", None):
        extra += ["--archive", args.archive]
    if getattr(args, "yes", False):
        extra.append("--yes")
    return out + extra


def dispatch(args, console, bundle, use_venv):
    cmd = args.cmd
    try:
        if cmd == "install":
            folder = Path(args.folder).resolve() if args.folder else console.ask_path(
                "Where should the vault go?", Path.home() / "StatPearls Vault").resolve()
        else:
            folder = find_folder(getattr(args, "folder", None))
    except KeyboardInterrupt:
        console.say("")
        console.say("Stopped. Run the same command again to resume.")
        return 130
    ctx = Ctx(console, bundle, folder, args, use_venv)
    ctx.child_args = child_argv(args, folder) if folder is not None else None
    log = ctx.log_path if folder is not None and folder.exists() else None
    handlers = {"install": cmd_install, "update": cmd_update, "status": cmd_status, "export": cmd_export,
                "agent-prepare": cmd_agent_prepare, "agent-collect": cmd_agent_collect}

    def go():
        if folder is None:
            raise UserError("Could not find a StatPearls vault.", "Add --folder PATH, or open the menu and choose the vault folder.", log=False)
        if cmd != "install" and installed_info(folder) is None:
            raise UserError(f"{folder} is not a StatPearls vault installed by this program.", NOT_AN_INSTALL_TODO, log=False)
        if bundle is None and cmd in ("install", "update"):
            raise UserError("This tool must be run from the statpearls-vault.pyz or .exe file.", "Run: python statpearls-vault.pyz " + cmd, log=False)
        if use_venv and cmd not in ("install", "update"):  # those two check the folder first, then enter the venv themselves
            env.ensure_venv(folder, console, ctx.child_args)
        rc = handlers[cmd](ctx)
        if not rc and installed_info(folder) is not None:
            known.remember(folder)  # the menu finds it next time, wherever the .pyz file is
        return rc
    return run_safely(go, console, log)


def latest_vs_installed(info):
    latest = latest_info()
    newer = (latest.updated, latest.size) != (info["archive_updated"], info["archive_size"])
    return f"yes (archive of {human_date(latest.updated)})" if newer else "no"


def welcome_state(folder, info):
    """-> (rows for the state panel, the online-check Pending or None). The check runs while the menu is shown."""
    if not info:
        return [("Vault folder", "none found yet")], None
    sysrep = read_json_file(Path(folder) / "data" / "reports" / "system.json", {})
    articles = info.get("articles")
    check = Pending(lambda: latest_vs_installed(info), UPDATE_CHECK_SECONDS, unknown="unknown (could not reach NLM)")
    rows = [("Vault folder", f"`{folder}`"), ("Archive", human_date(info["archive_updated"])),
            ("Articles", f"{articles:,}" if isinstance(articles, int) else "unknown"),
            ("Placed automatically", str(len(sysrep.get("auto_classified", [])))), ("Update available", check)]
    return rows, check


CHOOSE, FIND, OTHER, BACK = "Choose vault folder...", "Find an existing vault...", "Another folder...", "Back"


def menu_options(info):
    why = None if info else "no vault chosen yet"
    return [("Install", None), ("Update", why), ("Status", why), ("Export", why), (CHOOSE if info else FIND, None), ("Quit", None)]


def picker_options():
    """Remembered folders (missing ones shown but disabled) -> (options, label -> folder)."""
    opts, where = [], {}
    for f in known.load():
        info = installed_info(f) if known.is_install(f) else None
        if info:
            arts = info.get("articles")
            label = f"{f}   archive of {human_date(info['archive_updated'])}" + (f", {arts:,} articles" if isinstance(arts, int) else "")
            opts.append((label, None))
            where[label] = Path(f)
        else:
            opts.append((f, "not found (deleted, or a drive that is not connected)"))
    return opts + [(OTHER, None), (BACK, None)], where


def pick_folder(console, current):
    """The vault-folder picker. -> the chosen install folder, or current when the user goes back."""
    while True:
        opts, where = picker_options()
        rows = [("Vault folder now", f"`{current}`" if current else "none")]
        choice = console.menu(rows, opts)
        if choice in (BACK, "Quit"):
            return current
        if choice in where:
            return where[choice]
        if choice == OTHER:
            raw = console.ask_path("Folder that holds your vault (it contains the vault and data folders)",
                                   current or Path.home() / "StatPearls Vault")
            found = known.normalize(raw)
            if found:
                known.remember(found)
                return found
            console.error(f"{raw} is not a StatPearls vault installed by this program.", NOT_AN_INSTALL_TODO)


def menu(console, bundle, use_venv):
    folder = find_folder(None)
    try:
        while True:
            info = installed_info(folder) if folder else None
            console.header("StatPearls vault", f"Installer {VERSION} - a private study copy for Obsidian")
            rows, _ = welcome_state(folder, info)
            choice = console.menu(rows, menu_options(info))
            if choice not in (CHOOSE, FIND):
                break
            folder = pick_folder(console, folder)
    except (KeyboardInterrupt, EOFError):
        return 130
    except UserError as e:
        console.error(e.what, e.todo)
        return 1
    if choice == "Quit":
        return 0
    ns = argparse.Namespace(cmd=choice.lower(), yes=False, force=False, archive=None, folder=str(folder) if folder else None, folder_arg=None, out=None)
    if choice == "Install":
        ns.folder = None
    if choice == "Export":
        ns.out = str(default_export_path())
    return dispatch(ns, console, bundle, use_venv)
