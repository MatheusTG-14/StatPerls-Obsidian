"""L1 inline/block trees -> Obsidian Markdown. Text is never altered, only escaped.

All escaping goes through `esc` so the fidelity check can undo it (`unesc`).
"""
import re

# Always: \ ` * _ [ ] < | $ ; '#' before non-space (tags); doubled = ~ % (highlight, strike, comment).
_ESC = re.compile(r"[\\`*_\[\]<|$]|#(?=\S)|([=~%])(?=\1)")
_LINE_START = re.compile(r"^(\s*)(?:([-+>#])|(\d+)([.)]))(\s)")


def esc(s):
    return _ESC.sub(lambda m: "\\" + m.group(0), s)


def unesc(s):
    return re.sub(r"\\(.)", r"\1", s)


def esc_line_start(line):
    def fix(m):
        lead, sym, num, dot, sp = m.groups()
        return f"{lead}\\{sym}{sp}" if sym else f"{lead}{num}\\{dot}{sp}"
    return _LINE_START.sub(fix, line, count=1)


def _url(href):
    href = href.strip()
    return f"<{href}>" if re.search(r"[\s()<>]", href) else href


class Ctx:
    """Per-note render state: link matcher, first-mention memory, figure lookups."""

    def __init__(self, self_id, index=None, stems=None, nbk_to_id=None, figs=None):
        self.self_id = self_id
        self.index = index
        self.stems = stems or {}
        self.nbk_to_id = nbk_to_id or {}
        self.figs = figs or {}
        self.refs = {}  # reference rid -> its number in the References list
        self.linked = set()
        self.links_out = []
        self.no_auto = 0  # >0 while inside headings, links, captions

    def wikilink(self, target_id, surface):
        stem = self.stems[target_id]
        self.links_out.append(target_id)
        return f"[[{stem}]]" if surface == stem else f"[[{stem}|{surface}]]"


def text_with_links(v, ctx):
    if ctx.no_auto or ctx.index is None:
        return esc(v)
    out, pos = [], 0
    for start, end, target in ctx.index.find(v):
        if target == ctx.self_id or target in ctx.linked or target not in ctx.stems:
            continue
        ctx.linked.add(target)
        out.append(esc(v[pos:start]))
        out.append(ctx.wikilink(target, v[start:end]))
        pos = end
    out.append(esc(v[pos:]))
    return "".join(out)


def _wrap(marker, inner):
    """Emphasis markers must hug non-space text."""
    stripped = inner.strip(" ")
    if not stripped:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip(" "))]
    trail = inner[len(inner.rstrip(" ")):]
    return f"{lead}{marker}{stripped}{marker}{trail}"


def inl(nodes, ctx):
    out = []
    i = 0
    while i < len(nodes):
        n = nodes[i]
        t = n["t"]
        if t == "text":
            out.append(text_with_links(n["v"], ctx))
        elif t == "b":
            out.append(_wrap("**", inl(n["c"], ctx)))
        elif t == "i":
            out.append(_wrap("*", inl(n["c"], ctx)))
        elif t in ("sup", "sub", "u"):
            out.append(f"<{t}>{inl(n['c'], ctx)}</{t}>")
        elif t == "cite":
            out.append(cite(n, ctx))
        elif t == "code":
            v = n["v"].replace("`", "'")
            out.append(f"`{v}`")
        elif t == "br":
            out.append("<br>")
        elif t == "link":
            out.append(link(n, ctx))
        elif t == "block":  # a list inside a paragraph: break out onto its own lines
            out.append("\n" + block(n["b"], ctx, 0) + "\n")
        i += 1
    return "".join(out)


def cite(n, ctx):
    """Citation marker -> same-note link to its reference's block ID; printed text kept as is."""
    k = ctx.refs.get(n.get("rid"))
    if k is None or not n["v"]:
        return esc(n["v"])
    return f"[{esc(n['v'])}](#^ref-{k})"


def link(n, ctx):
    m = re.search(r"ncbi\.nlm\.nih\.gov/books/(NBK\d+)", n["href"])
    ctx.no_auto += 1
    label = inl(n["c"], ctx)
    ctx.no_auto -= 1
    if m:
        from src.extract.nxml import inline_text
        target = ctx.nbk_to_id.get(m.group(1))
        surface = inline_text(n["c"])
        # wikilink aliases cannot hold [ ] |; keep such links as web links so the text stays verbatim
        if target and target in ctx.stems and target != ctx.self_id and not re.search(r"[\[\]|]", surface):
            ctx.linked.add(target)
            return ctx.wikilink(target, surface)
    return f"[{label}]({_url(n['href'])})"


def is_subheading(b):
    """DEC-09 pilot rule: short bold-only paragraph without sentence punctuation."""
    if not b.get("bold_only"):
        return False
    from src.extract.nxml import inline_text
    s = inline_text(b["c"]).strip()
    return 0 < len(s) <= 80 and not s.endswith((".", "?", "!", ";", ","))


def block(b, ctx, depth):
    t = b["t"]
    if t == "p":
        if is_subheading(b):
            from src.extract.nxml import inline_text
            ctx.no_auto += 1
            h = esc(inline_text(b["c"]).strip())
            ctx.no_auto -= 1
            return f"### {h}"
        return esc_line_start(inl(b["c"], ctx))
    if t == "list":
        lines = []
        for k, item in enumerate(b["items"], 1):
            marker = f"{k}." if b["ordered"] else "-"
            pad = " " * (len(marker) + 1)
            first = True
            for sub in item:
                # item text that itself starts with "1. " or "- " must not become a nested list
                text = block(sub, ctx, depth + 1) if sub["t"] != "p" else esc_line_start(inl(sub["c"], ctx))
                for j, line in enumerate(text.splitlines()):
                    if first and j == 0:
                        lines.append(f"{marker} {line}")
                    elif line:
                        lines.append(pad + line)
                first = False
            if first:
                lines.append(marker)
        return "\n".join(lines)
    if t == "table":
        return table(b, ctx)
    if t == "code":
        return "```text\n" + b["v"].replace("```", "'''") + "\n```"
    if t == "figref":
        return ctx.figs.get(b["id"], "")
    raise ValueError(t)


def table(b, ctx):
    rows = [[inl(c, ctx).replace("\n", "<br>") for c in r] for r in b["rows"] if r]
    out = []
    if b["caption"]:
        ctx.no_auto += 1
        out.append(inl(b["caption"], ctx))
        ctx.no_auto -= 1
        out.append("")
    if not rows:
        return "\n".join(out)
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out.append("| " + " | ".join(rows[0]) + " |")
    out.append("|" + "---|" * width)
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)
