"""Console output for the installer: steps, screens, menu, prompts, plain-English errors. No tracebacks on screen.

Two renderers behind one interface: rich (an interactive terminal, Rich vendored in the .pyz) and plain (redirected
output, NO_COLOR, --plain, or a console that cannot show box-drawing characters; ASCII-only symbols there).
"""
import os
import sys
import textwrap
import threading
import time
import traceback
from pathlib import Path


class UserError(Exception):
    """A problem the user can fix: what went wrong, and what to do next."""

    def __init__(self, what, todo="", log=True):
        super().__init__(what)
        self.what = what
        self.todo = todo
        self.log = log  # False for self-explanatory refusals: nothing is written, no log is mentioned


def fmt_bytes(n):
    """Decimal units, one decimal: 2.0 GB, 1.5 KB."""
    n = float(n)
    for unit in ("B", "KB", "MB"):
        if n < 1000:
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} GB"


def fmt_duration(s):
    s = int(round(s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s"
    return f"{s // 3600} h {s % 3600 // 60} min"


def _vt_enabled():
    if os.name != "nt":
        return True
    try:
        return os.system("") == 0  # switches the Windows console to VT mode as a side effect
    except OSError:
        return False


def can_encode(out, text="┃✓"):
    """True when the stream can show box-drawing characters and check marks."""
    enc = getattr(out, "encoding", None)
    if not enc:
        return True  # in-memory streams
    try:
        text.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def detect_unicode(stream):
    """Full Unicode glyphs (rounded corners, ✓, braille spinner) need a font that has them: Windows Terminal or a UTF-8
    console. Old consoles still get the rich interface, only with glyphs their fonts have (screens.use_safe_glyphs)."""
    if not can_encode(stream):
        return False
    if os.name == "nt" and bool(getattr(stream, "isatty", lambda: False)()):
        if os.environ.get("WT_SESSION"):
            return True
        try:
            import ctypes
            return ctypes.windll.kernel32.GetConsoleOutputCP() == 65001
        except Exception:  # noqa: BLE001
            return True
    return True


UNICODE = {"ok": "✓", "warn": "!", "arrow": "→", "full": "█", "empty": "░"}
ASCII = {"ok": "[done]", "warn": "!", "arrow": "->", "full": "#", "empty": "-"}


def _untick(text):
    return text.replace("`", "")


class Pending:
    """A value computed in a thread (the online update check). value() -> (ready, result-or-None)."""

    def __init__(self, fn, timeout, unknown="unknown"):
        self.unknown = unknown
        self._result = None
        self._done = threading.Event()
        self.timeout = timeout
        self.started = time.monotonic()

        def run():
            try:
                self._result = fn()
            except Exception:  # noqa: BLE001
                self._result = None
            self._done.set()
        threading.Thread(target=run, daemon=True).start()

    def value(self, wait=False):
        if wait:
            self._done.wait(max(0.0, self.timeout - (time.monotonic() - self.started)))
        done = self._done.is_set()
        return done or wait or time.monotonic() - self.started >= self.timeout, (self._result if done else None)


class Console:
    def __init__(self, out=None, inp=input, color=None, yes=False, plain=None, width=None, keys=None, interactive=None, unicode=None):
        self.out = out if out is not None else sys.stdout
        self.inp = inp
        self.yes = yes
        self.width = width
        self.keys = keys
        tty = bool(getattr(self.out, "isatty", lambda: False)())
        self.tty = tty
        self.unicode = detect_unicode(self.out) if unicode is None else unicode
        self.sym = UNICODE if self.unicode else ASCII
        if interactive is None:
            interactive = tty and bool(getattr(sys.stdin, "isatty", lambda: False)())
        self.interactive = interactive
        self.hold_open = False
        forced_plain = plain is True
        if plain is None:
            plain = not (tty and "NO_COLOR" not in os.environ)
        self.rich = False
        self._rc = None
        if not plain:
            try:
                self._rc = self._make_rich()
                self.rich = True
                from src.installer import screens
                screens.use_safe_glyphs(not self.unicode)
            except ImportError:
                self._rc = None
        if color is None:
            color = tty and not forced_plain and "NO_COLOR" not in os.environ and _vt_enabled()
        self.color = color
        self._step_started = time.time()
        self._bar_open = False

    def _make_rich(self):
        from rich.console import Console as RichConsole

        from src.installer import screens
        real = any(self.out is s for s in (sys.stdout, sys.stderr, getattr(sys, "__stdout__", None)))
        return RichConsole(file=self.out, force_terminal=True if not self.tty else None, width=self.width, theme=screens.THEME,
                           highlight=False, legacy_windows=None if real else False, soft_wrap=False)

    @property
    def screens(self):
        from src.installer import screens
        return screens

    # ----- output -----
    def _w(self, text):
        self.out.write(text)
        try:
            self.out.flush()
        except Exception:  # noqa: BLE001
            pass

    def _c(self, code, text):
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text

    def _end_bar(self):
        if self._bar_open:
            self._w("\n")
            self._bar_open = False

    def _line(self, text="", indent=""):
        """One plain line; wrapped only when a width was given (a redirected file is never re-wrapped)."""
        if not text or not self.width:
            self._w(indent + text + "\n")
            return
        for ln in textwrap.wrap(text, self.width, initial_indent=indent, subsequent_indent=indent + "  ",
                                break_long_words=True, break_on_hyphens=False) or [indent]:
            self._w(ln + "\n")

    def say(self, text=""):
        self._end_bar()
        if self.rich:
            self._rc.print(self.screens.styled(text))
        else:
            self._w(_untick(text) + "\n")

    def step(self, n, total, title):
        self._end_bar()
        self._step_started = time.time()
        if self.rich:
            self._rc.print()
            self._rc.print(f"Step {n} of {total}: {title}", style="brand.blue")
        else:
            self._w("\n" + self._c("1", f"Step {n} of {total}: {title}") + "\n")

    def done(self, text):
        self._end_bar()
        took = fmt_duration(time.time() - self._step_started)
        if self.rich:
            from rich.text import Text
            self._rc.print(Text.assemble((self.sym["ok"], "ok"), " ", self.screens.styled(text), f" ({took})"))
        else:
            self._w(self._c("32", self.sym["ok"]) + f" {_untick(text)} ({took})\n")

    def warn(self, text):
        self._end_bar()
        if self.rich:
            from rich.text import Text
            self._rc.print(Text.assemble(("! ", "warn"), self.screens.styled(text)))
        else:
            self._w(self._c("33", "! ") + _untick(text) + "\n")

    def bar(self, done, total, started):
        frac = min(1.0, done / total) if total else 1.0
        filled = int(frac * 10)
        elapsed = max(time.time() - started, 1e-6)
        speed = done / elapsed
        left = (total - done) / speed if speed > 0 else 0
        line = (f"[{self.sym['full'] * filled}{self.sym['empty'] * (10 - filled)}] {int(frac * 100):>3} %  "
                f"{fmt_bytes(done)} of {fmt_bytes(total)}  {speed / 1e6:.1f} MB/s  {fmt_duration(left)} left")
        self._w("\r" + line + "   ")
        self._bar_open = True

    # ----- screens -----
    def header(self, title, subtitle=""):
        self._end_bar()
        if self.rich:
            self._rc.print(self.screens.header(title, subtitle))
        else:
            self._w(f"{title}\n" + (f"{subtitle}\n" if subtitle else "") + "=" * min(len(title), 60) + "\n")

    def _rows_plain(self, rows):
        pad = max((len(str(k)) for k, _ in rows), default=0) + 1
        for k, v in rows:
            self._line(f"{str(k) + ':':<{pad}} {_untick(str(v))}", "  ")

    def state_panel(self, rows):
        self._end_bar()
        if self.rich:
            self._rc.print(self.screens.state_panel(rows))
        else:
            self._rows_plain(rows)

    def plan_panel(self, lines, table):
        """Shows what will happen, then asks "Continue?" -> bool."""
        self._end_bar()
        if self.rich:
            self._rc.print(self.screens.plan_panel(lines, table))
        else:
            self._w("\n")
            for ln in lines:
                self._line(_untick(ln))
            if table:
                self._w("\n")
                self._rows_plain(table)
            self._w("\n")
        return self.confirm("Continue?", default=True)

    def done_panel(self, table, lines, ok=True):
        self._end_bar()
        if self.rich:
            self._rc.print(self.screens.done_panel(table, lines, ok))
            return
        self._w("\n" + ("Done" if ok else "Done with warnings") + "\n")
        self._rows_plain([(k, f"{n:,}" if isinstance(n, int) else n) for k, n in table])
        if table and lines:
            self._w("\n")
        for ln in lines:
            self._line(_untick(ln))

    def status_table(self, rows):
        self._end_bar()
        if self.rich:
            self._rc.print(self.screens.status_table(rows))
        else:
            self._rows_plain(rows)

    def stopped(self):
        self._end_bar()
        if self.rich:
            self._rc.print()
            self._rc.print(self.screens.stopped_panel())
        else:
            self._w("\nStopped safely. Run the same command again to resume.\n")

    def help(self, prog, description, commands, examples):
        if self.rich:
            self._rc.print(self.screens.help_panel(prog, description, commands, examples))
            return
        self._line(f"{prog}: {description}")
        self._w("\nCommands:\n")
        pad = max(len(n) for n, _ in commands)
        for n, d in commands:
            self._line(f"{n:<{pad}}  {d}", "  ")
        self._w("\nExamples:\n")
        for e in examples:
            self._line(e, "  ")

    def error(self, what, todo, log_path=None):
        self._end_bar()
        if self.rich:
            self._rc.print(self.screens.error_panel(what, todo, log_path))
            return
        self._w(self._c("31;1", "Problem: ") + _untick(what) + "\n")
        if todo:
            self._w(_untick(todo) + "\n")
        if log_path:
            self._w(f"Details are saved in {log_path}\n")

    def summary(self, lines):
        self._end_bar()
        self._w("\n")
        for line in lines:
            if self.rich:
                self._rc.print(self.screens.styled(line))
            else:
                self._w(_untick(line) + "\n")

    def wait_to_close(self):
        """Keeps a window that was opened by double-click readable; only after a menu start in a terminal."""
        if not self.hold_open:
            return
        self._end_bar()
        try:
            self.inp("\nPress Enter to close this window. ")
        except (EOFError, KeyboardInterrupt):
            pass

    # ----- input -----
    def _ask(self, prompt):
        try:
            return self.inp(prompt)
        except EOFError:
            raise UserError("This needs an answer, but there is no one to ask here.",
                            "Add --yes to accept the plan without asking.", log=False) from None

    def confirm(self, question, default=True):
        if self.yes:
            return default
        hint = "[Y/n]" if default else "[y/N]"
        while True:
            self._end_bar()
            ans = self._ask(f"{question} {hint} ").strip().lower()
            if ans == "":
                return default
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no"):
                return False

    def ask_path(self, question, default):
        if self.yes:
            return Path(default)
        ans = self._ask(f"{question} [{default}] ").strip().strip('"')
        return Path(ans) if ans else Path(default)

    def menu(self, state_rows, options):
        """options: labels or (label, reason-when-disabled or None). -> the chosen label ("Quit" for Esc / q)."""
        self._end_bar()
        opts = [(o, None) if isinstance(o, str) else (o[0], o[1]) for o in options]
        if self.rich and (self.keys is not None or self.interactive):
            return self._menu_keys(state_rows, opts)
        return self._menu_typed(state_rows, opts)

    @staticmethod
    def _resolved_rows(rows, wait=False):
        out, pending = [], False
        for r in rows:
            if isinstance(r, str):
                out.append(("", r))
                continue
            k, v = r
            if isinstance(v, Pending):
                ready, val = v.value(wait)
                v = val if ready and val is not None else (v.unknown if ready else "checking...")
                pending = pending or not ready
            out.append((k, v))
        return out, pending

    def _menu_typed(self, state_rows, opts):
        rows, _ = self._resolved_rows(state_rows, wait=True)
        for k, v in rows:
            self._w(_untick(f"{k}: {v}" if k else v) + "\n")
        self._w("\n")
        for n, (label, reason) in enumerate(opts, 1):
            self._w(f"  {n}) {label}" + (f"   ({reason})" if reason else "") + "\n")
        while True:
            ans = self._ask("Choose a number: ").strip()
            if ans.isdigit() and 1 <= int(ans) <= len(opts):
                label, reason = opts[int(ans) - 1]
                if reason:
                    self._w(f"{label} is not available: {reason}\n")
                    continue
                return label
            if ans.lower() in ("q", "quit") and any(o[0] == "Quit" for o in opts):
                return "Quit"

    def _menu_keys(self, state_rows, opts):
        from rich.console import Group
        from rich.live import Live
        from src.installer import keys as keymod
        keys = self.keys
        if keys is None:
            keys = keymod.read_key
        scr = self.screens
        labels = [o[0] for o in opts]
        enabled = [k for k, o in enumerate(opts) if o[1] is None]
        sel = enabled[0] if enabled else 0
        msg = ""
        quit_label = "Quit" if "Quit" in labels else labels[-1]
        hint = f"Up/Down and Enter, or press 1-{len(opts)}.  Esc quits."

        def draw():
            rows, pending = self._resolved_rows(state_rows)
            return Group(scr.state_panel(rows), scr.menu_body(opts, sel, msg, hint)), pending
        renderable, pending = draw()
        import contextlib
        raw_mode = contextlib.nullcontext()
        if self.keys is None:
            raw_mode = keymod.session()
        with raw_mode, Live(renderable, console=self._rc, auto_refresh=False, transient=False) as live:
            while True:
                k = keys(0.25 if pending else None)
                if k is not None:
                    msg = ""
                    if k in ("up", "down") and enabled:
                        pos = enabled.index(sel) if sel in enabled else 0
                        sel = enabled[(pos + (1 if k == "down" else -1)) % len(enabled)]
                    elif k == "enter" and opts[sel][1] is None:
                        return labels[sel]
                    elif k in ("esc", "q"):
                        return quit_label
                    elif k.isdigit() and 1 <= int(k) <= len(opts):
                        label, reason = opts[int(k) - 1]
                        if reason is None:
                            return label
                        msg = f"{label} is not available: {reason}"
                renderable, pending = draw()
                live.update(renderable, refresh=True)


def run_safely(fn, console, log_path):
    """Run fn() and turn every failure into a short message plus a log file. -> process exit code."""
    try:
        try:
            rc = fn()
            return 0 if rc is None else rc
        except KeyboardInterrupt:
            console.stopped()
            return 130
        except UserError as e:
            logged = bool(e.log and log_path)
            if logged:
                _log(log_path, f"UserError: {e.what} | {e.todo}\n{traceback.format_exc()}")
            console.error(e.what, e.todo, log_path if logged else None)
            return 1
        except Exception:  # noqa: BLE001
            if log_path:
                _log(log_path, traceback.format_exc())
            console.error("Something unexpected went wrong.", "Run the same command again; finished steps are not repeated. "
                          "If it keeps failing, keep the log file.", log_path)
            return 1
    finally:
        console.wait_to_close()


def _log(log_path, text):
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}\n")
    except OSError:
        pass
