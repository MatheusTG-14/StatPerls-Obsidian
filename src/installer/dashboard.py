"""Live dashboard for install and update: step list, current-step detail, elapsed and estimated time left.

Rich mode: one Live display (refreshed at most 4 times a second). Plain mode: a line when a step starts or ends and a
detail line at most every 10 seconds. The dashboard listens to `src.progress` while it is open.
"""
import time

from src import progress
from src.installer.ui import fmt_bytes, fmt_duration

# Measured on the full archive (DEC-26): unpack 162 s, read 1050 s, build 1128 s; the rest are small or estimated.
TYPICAL_SECONDS = {1: 2, 2: 30, 3: 10, 4: 200, 5: 162, 6: 1050, 7: 1128, 8: 30}

# How a step with several phases is weighted (shares of the step); other steps are a single phase.
PHASES = {
    5: [("unpack", 0.5), ("figures", 0.5)],
    6: [("read", 0.85), ("reference", 0.15)],
    7: [("classify", 0.10), ("notes", 0.75), ("figure-notes", 0.10), ("search", 0.05)],
}
PHASE_LABEL = {"unpack": "Unpacking", "figures": "Figures", "read": "Reading", "reference": "Fetching reference data", "classify": "Sorting into categories",
               "notes": "Writing notes", "figure-notes": "Writing figure notes", "search": "Building the search index"}
DETAIL_EVERY = 10.0  # plain mode: seconds between detail lines


def spinner_name(console):
    return "dots" if console.unicode else "line"


def typical_for(download_bytes=None):
    """TYPICAL_SECONDS with the download step estimated from its size (about 10 MB/s)."""
    t = dict(TYPICAL_SECONDS)
    if download_bytes:
        t[4] = download_bytes / 10e6
    return t


def phase_fraction(step, phase, frac):
    """Fraction of the whole step once `phase` of it is `frac` done."""
    base = 0.0
    for key, weight in PHASES.get(step, []):
        if key == phase:
            return base + weight * max(0.0, min(1.0, frac))
        base += weight
    return max(0.0, min(1.0, frac))


def estimate_left(typical, current, frac, elapsed_step, skipped=()):
    """Seconds left: the rest of the current step (at its own rate once it is measurable, else its typical time)
    plus the typical time of every later step that is not skipped."""
    frac = max(0.0, min(1.0, frac or 0.0))
    if frac >= 0.02 and elapsed_step >= 3:
        here = elapsed_step * (1 - frac) / frac
    else:
        here = typical.get(current, 0) * (1 - frac)
    later = sum(v for k, v in typical.items() if k > current and k not in skipped)
    return here + later


def fmt_eta(s):
    if s < 60:
        return "less than a minute"
    if s < 3600:
        return f"{round(s / 60)} min"
    return f"{int(s // 3600)} h {round(s % 3600 / 60)} min"


class Dashboard:
    def __init__(self, console, title, folder, archive_date, steps, typical=None, clock=time.monotonic, done_before=None, show_done_before=True):
        self.c = console
        self.title, self.folder, self.archive_date = title, folder, archive_date
        self.steps = list(steps)
        self.typical = typical or dict(TYPICAL_SECONDS)
        self.clock = clock
        self.rows = [{"status": "wait", "dur": None, "note": "", "t0": None} for _ in self.steps]
        self.cur = None
        self.warnings = []
        self._detail = None      # (phase, done, total, unit)
        self._phase = None       # (phase, t0, done0) for the rate
        self._rate = None
        self._last_plain = None
        self._live = None
        self._open = False
        before = done_before or {}
        for n, secs in before.items():
            if 1 <= n <= len(self.rows):
                self.rows[n - 1].update(status="done", dur=float(secs))
        self.show_done_before = show_done_before
        self._offset = sum(float(v) for v in before.values())
        self._t0 = None

    # ----- lifecycle -----
    def __enter__(self):
        self._t0 = self.clock()
        progress.set_listener(self.on_progress)
        self._open = True
        if self.c.rich:
            from rich.live import Live
            self._live = Live(get_renderable=self._render, console=self.c._rc, refresh_per_second=4, transient=False,
                              redirect_stdout=False, redirect_stderr=True)
            self._live.start(refresh=True)
        else:
            self.c.say(f"{self.title}: {self.folder} (archive of {self.archive_date})")
            for n, row in enumerate(self.rows, 1):
                if row["status"] == "done" and self.show_done_before:
                    self.c.say(f"{self.c.sym['ok']} Step {n} of {len(self.steps)}: {self.steps[n - 1]} ({fmt_duration(row['dur'])})")
        return self

    def __exit__(self, et, ev, tb):
        self.close()
        return False

    def close(self, clear=False):
        """Stop listening and put the terminal back (cursor shown, display left on screen unless clear)."""
        progress.set_listener(None)
        if self._live is not None:
            self._live.transient = clear
            try:
                self._live.stop()
            finally:
                self._live = None
        self._open = False

    def handoff(self):
        """The next process draws its own dashboard: remove this one."""
        self.close(clear=True)

    # ----- steps -----
    def elapsed(self):
        return self._offset + (self.clock() - self._t0 if self._t0 is not None else 0.0)

    def start(self, n):
        row = self.rows[n - 1]
        row.update(status="run", t0=self.clock(), note="")
        self.cur = n
        self._detail = self._phase = self._rate = None
        if self._live is None:
            self.c.step(n, len(self.steps), self.steps[n - 1])
        self._refresh()

    def finish(self, n, note=""):
        row = self.rows[n - 1]
        row.update(status="done", dur=self.clock() - (row["t0"] if row["t0"] is not None else self.clock()), note=note)
        self._detail = None
        if self._live is None:
            self.c.done(note or self.steps[n - 1])
        self._refresh()

    def skip(self, n, note=""):
        self.rows[n - 1].update(status="skip", note=note)
        if self._live is None:
            self.c.say(f"Step {n} of {len(self.steps)}: {self.steps[n - 1]} - skipped" + (f" ({note})" if note else ""))
        self._refresh()

    def warn(self, text):
        self.warnings.append(text)
        if self._live is None:
            self.c.warn(text)
        self._refresh()

    def detail(self, done, total, unit, rate=None, phase=None):
        phase = phase or unit
        now = self.clock()
        if self._phase is None or self._phase[0] != phase or done < self._phase[2]:
            self._phase = (phase, now, done)
        _, t0, d0 = self._phase
        if rate is None and now > t0:
            rate = (done - d0) / (now - t0)
        self._rate = rate
        self._detail = (phase, done, total, unit)
        if self._live is None:
            if self._last_plain is None or now - self._last_plain >= DETAIL_EVERY:
                self._last_plain = now
                self.c.say("  " + self._detail_text(wide=True))

    def on_progress(self, step, done, total, unit):
        self.detail(done, total, unit, phase=step)

    def _refresh(self):
        if self._live is not None:
            self._live.refresh()

    # ----- numbers -----
    def _frac(self):
        if not self._detail or self.cur is None:
            return None
        phase, done, total, unit = self._detail
        if not total:
            return None
        return phase_fraction(self.cur, phase, done / total)

    def left(self):
        if self.cur is None or self.rows[self.cur - 1]["status"] != "run":
            return None
        skipped = {n for n, r in enumerate(self.rows, 1) if r["status"] == "skip"}
        elapsed_step = self.clock() - (self.rows[self.cur - 1]["t0"] or self.clock())
        return estimate_left(self.typical, self.cur, self._frac() or 0.0, elapsed_step, skipped)

    def _detail_text(self, wide):
        if not self._detail:
            return ""
        phase, done, total, unit = self._detail
        if unit == "bytes":
            text = f"{fmt_bytes(done)} of {fmt_bytes(total)}"
            if wide and self._rate and self._rate > 0:
                text += f"  {self._rate / 1e6:.1f} MB/s  {fmt_duration((total - done) / self._rate)} left"
            return text
        label = PHASE_LABEL.get(phase, "")
        counter = f"{done:,} of {total:,} {unit}" if total else f"{done:,} {unit}"
        return f"{label}: {counter}" if label else counter

    # ----- rich rendering -----
    def _render(self):
        from src.installer import screens
        from rich.console import Group
        from rich.panel import Panel
        from rich.progress_bar import ProgressBar
        from rich.spinner import Spinner
        from rich.table import Table
        from rich.text import Text

        width = self.c._rc.width
        narrow = width < 80
        head = Text.assemble((str(self.folder), "path"), ("   archive of ", "label"), (str(self.archive_date), "path"), overflow="fold")
        grid = Table.grid(padding=(0, 1), expand=True)
        grid.add_column(width=2, no_wrap=True)
        grid.add_column(ratio=1, overflow="fold")
        grid.add_column(justify="right", overflow="fold")
        ok = self.c.sym["ok"]
        for n, (name, row) in enumerate(zip(self.steps, self.rows), 1):
            label = f"{n}. {name}"
            if row["status"] == "done":
                note = fmt_duration(row["dur"]) if row["dur"] is not None else ""
                grid.add_row(Text(ok, style="ok"), Text(label), Text(note, style="label"))
            elif row["status"] == "run":
                grid.add_row(Spinner(spinner_name(self.c), style="brand.blue"), Text(label, style="bold"), Text(""))
            elif row["status"] == "skip":
                grid.add_row(Text("-", style="dim"), Text(label, style="dim"), Text("skipped" + (f": {row['note']}" if row["note"] else ""), style="dim"))
            else:
                grid.add_row(Text("·", style="dim"), Text(label, style="dim"), Text(""))
        parts = [head, Text(""), grid]
        for w in self.warnings:
            parts.append(Text.assemble(("! ", "warn"), (w, "")))
        if self._detail:
            phase, done, total, unit = self._detail
            line = Table.grid(padding=(0, 2))
            line.add_column()
            line.add_column(overflow="fold")
            bar_w = 16 if narrow else 28
            if self.c.unicode:
                bar = ProgressBar(total=total or None, completed=done, width=bar_w, complete_style="brand.blue",
                                  finished_style="green", pulse_style="brand.blue")
            else:  # Rich's bar glyph (━) is missing from old console fonts
                k = round(bar_w * done / total) if total else 0
                bar = Text.assemble((self.c.sym["full"] * k, "brand.blue"), (self.c.sym["empty"] * (bar_w - k), "dim"))
            line.add_row(bar, Text(self._detail_text(wide=not narrow)))
            parts += [Text(""), line]
        left = self.left()
        foot = f"Elapsed {fmt_duration(self.elapsed())}" + (f"   About {fmt_eta(left)} left" if left is not None else "")
        hint = ("Ctrl+C stops safely;" + chr(10) + "run the same command again to resume." if narrow
                else "Ctrl+C stops safely; run the same command again to resume.")
        parts += [Text(""), Text(foot), Text(hint, style="label")]
        return Panel(Group(*parts), title=Text(self.title, style="brand.blue"), title_align="left", box=screens.panel_box(),
                     border_style="brand.blue", padding=(0, 1))
