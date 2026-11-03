"""Screen builders for the installer: data in, Rich renderables out. No I/O, no state.

Rich is imported here only; `ui.Console` imports this module when it runs in rich mode.
Text conventions: a piece of a line wrapped in backticks is a path or command and gets its own colour.
"""
import re

from rich import box
from rich.console import Group
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

BLUE, TEAL, MINT, NAVY = "#016EB8", "#0B7B73", "#71CFC1", "#18214D"

THEME = Theme({
    "brand.blue": f"bold {BLUE}", "brand.teal": TEAL, "brand.mint": MINT, "brand.navy": f"bold white on {NAVY}",
    "path": f"bold {MINT}", "label": "dim", "ok": "bold green", "warn": "bold yellow", "bad": "bold red", "dim": "dim",
})

_TICKS = re.compile(r"`([^`]*)`")
_BOX = [box.ROUNDED]


def use_safe_glyphs(flag):
    """Old console fonts lack rounded corners: square box-drawing characters exist in every console code page."""
    _BOX[0] = box.SQUARE if flag else box.ROUNDED


def panel_box():
    return _BOX[0]


def styled(line, style=""):
    """A Text from a plain line; `backticked` pieces use the path colour."""
    t = Text(style=style, overflow="fold")
    pos = 0
    for m in _TICKS.finditer(line):
        t.append(line[pos:m.start()])
        t.append(m.group(1), style="path")
        pos = m.end()
    t.append(line[pos:])
    return t


def strip_ticks(line):
    return _TICKS.sub(lambda m: m.group(1), line)


def _grid(rows, value_style=""):
    g = Table.grid(padding=(0, 2))
    g.add_column(style="label", no_wrap=False)
    g.add_column(overflow="fold")
    for k, v in rows:
        g.add_row(Text(str(k)), styled(str(v), value_style))
    return g


def header(title, subtitle=""):
    body = [Text(title, style="brand.navy")]
    if subtitle:
        body.append(Text(subtitle, style="label"))
    return Panel(Group(*body), box=panel_box(), border_style="brand.blue", padding=(0, 2))


def state_panel(rows, title="This computer"):
    return Panel(_grid(rows, "path"), title=title, title_align="left", box=panel_box(), border_style="brand.teal", padding=(0, 2))


def plan_panel(lines, table):
    parts = [styled(x) for x in lines]
    if table:
        parts += [Text(""), _grid(table, "path")]
    return Panel(Group(*parts), title="What will happen", title_align="left", box=panel_box(), border_style="brand.blue", padding=(1, 2))


def done_panel(table, lines, ok=True):
    parts = []
    if table:
        g = Table.grid(padding=(0, 2))
        g.add_column(style="label")
        g.add_column(justify="right", style="bold")
        for k, n in table:
            g.add_row(str(k), f"{n:,}" if isinstance(n, int) else str(n))
        parts += [g, Text("")]
    parts += [styled(x) for x in lines]
    title = "Done" if ok else "Done with warnings"
    return Panel(Group(*parts), title=Text(title, style="ok" if ok else "warn"), title_align="left", box=panel_box(),
                 border_style="green" if ok else "yellow", padding=(1, 2))


def status_table(rows):
    return Panel(_grid(rows, "path"), title="Status", title_align="left", box=panel_box(), border_style="brand.blue", padding=(0, 2))


def stopped_panel():
    return Panel(Group(Text("Your work so far is saved."), Text("Run the same command again to resume.")),
                 title=Text("Stopped safely", style="warn"), title_align="left", box=panel_box(), border_style="yellow", padding=(0, 2))


def error_panel(what, todo, log_path=None):
    parts = [styled(what, "bold")]
    if todo:
        parts += [Text(""), styled(todo)]
    if log_path:
        parts += [Text(""), Text.assemble("Details are saved in ", (str(log_path), "path"), overflow="fold")]
    return Panel(Group(*parts), title=Text("Problem", style="bad"), title_align="left", box=panel_box(), border_style="red", padding=(0, 2))


def help_panel(prog, description, commands, examples):
    g = Table.grid(padding=(0, 2))
    g.add_column(style="path", no_wrap=True)
    g.add_column(overflow="fold")
    for name, summary in commands:
        g.add_row(name, summary)
    parts = [Text(description, overflow="fold"), Text(""), g, Text(""), Text("Examples", style="brand.blue")]
    parts += [Text("  " + e, style="path", overflow="fold") for e in examples]
    return Panel(Group(*parts), title=f"{prog}", title_align="left", box=panel_box(), border_style="brand.blue", padding=(1, 2))


def menu_body(options, selected, message="", hint=""):
    """options: [(label, reason or None)]; the selected row is marked."""
    t = Text()
    for k, (label, reason) in enumerate(options):
        mark = "❯ " if k == selected else "  "
        if reason is not None:
            t.append(f"{mark}{k + 1}) {label}", style="dim")
            t.append(f"   {reason}\n", style="dim italic")
        else:
            t.append(f"{mark}{k + 1}) {label}\n", style="brand.blue" if k == selected else "")
    if message:
        t.append("\n" + message + "\n", style="warn")
    if hint:
        t.append("\n" + hint, style="label")
    return Padding(t, (0, 2))
