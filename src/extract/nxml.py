"""BITS book-part NXML -> L1 record (schema/l1.md).

Block and inline trees keep source order and verbatim text; only XML layout
whitespace is collapsed. Excluded material (Review Questions, question-bank
promo paragraphs) is counted, never silently dropped.
"""
import re

from src.common import XLINK, parse_xml, sha256_text, squash

EXCLUDED_SECTIONS = {"Review Questions"}
PROMO_HOSTS = ("statpearls.com",)
INLINE_TAGS = {"bold": "b", "italic": "i", "sup": "sup", "sub": "sub", "underline": "u"}


class UnknownElement(Exception):
    pass


def _text(el):
    return squash("".join(el.itertext())).strip() if el is not None else ""


def _date(el):
    if el is None:
        return None
    parts = [el.findtext(t) for t in ("year", "month", "day")]
    return "-".join(p.zfill(2) for p in parts if p) or None


# ---------- inlines ----------

def inlines(el):
    """Children + text of a mixed-content element as a list of inline nodes."""
    out = []
    if el.text:
        out.append({"t": "text", "v": el.text})
    for ch in el:
        if not isinstance(ch.tag, str):  # comments / PIs
            pass
        elif ch.tag in INLINE_TAGS:
            out.append({"t": INLINE_TAGS[ch.tag], "c": inlines(ch)})
        elif ch.tag == "ext-link":
            out.append({"t": "link", "href": ch.get(XLINK) or "", "c": inlines(ch)})
        elif ch.tag == "xref":
            out.append({"t": "cite", "rid": ch.get("rid"), "v": "".join(ch.itertext())})
        elif ch.tag == "code":
            out.append({"t": "code", "v": "".join(ch.itertext())})
        elif ch.tag == "p" and el.tag in ("td", "th"):  # paragraphs inside a table cell
            if out:
                out.append({"t": "br"})
            out.extend(inlines(ch))
        elif ch.tag == "list":  # one occurrence of a list inside <p>
            out.append({"t": "block", "b": block(ch)})
        else:
            raise UnknownElement(f"inline <{ch.tag}> in <{el.tag}>")
        if ch.tail:
            out.append({"t": "text", "v": ch.tail})
    return _norm_inlines(out)


def _norm_inlines(nodes):
    """Collapse layout whitespace across text runs; trim the edges."""
    merged = []
    for n in nodes:
        if n["t"] == "text":
            v = squash(n["v"])
            if merged and merged[-1]["t"] == "text":
                merged[-1]["v"] = squash(merged[-1]["v"] + v)
            elif v:
                merged.append({"t": "text", "v": v})
        else:
            merged.append(n)
    if merged and merged[0]["t"] == "text":
        merged[0]["v"] = merged[0]["v"].lstrip(" ")
    if merged and merged[-1]["t"] == "text":
        merged[-1]["v"] = merged[-1]["v"].rstrip(" ")
    return [n for n in merged if not (n["t"] == "text" and not n["v"])]


def inline_text(nodes):
    out = []
    for n in nodes:
        if n["t"] in ("text", "cite", "code"):
            out.append(n["v"])
        elif n["t"] == "br":
            continue
        elif n["t"] == "block":
            out.append(block_text(n["b"]))
        else:
            out.append(inline_text(n["c"]))
    return "".join(out)


# ---------- blocks ----------

def _is_promo(p):
    links = p.findall("ext-link")
    return (
        len(links) == 1
        and not squash(p.text or "").strip()
        and not squash(links[0].tail or "").strip()
        and any(h in (links[0].get(XLINK) or "") for h in PROMO_HOSTS)
    )


def _bold_only(nodes):
    return len(nodes) == 1 and nodes[0]["t"] == "b"


def block(el):
    tag = el.tag
    if tag == "p":
        c = inlines(el)
        b = {"t": "p", "c": c}
        if _bold_only(c):
            b["bold_only"] = True
        if el.get("content-type"):
            b["content_type"] = el.get("content-type")
        return b
    if tag == "list":
        items = []
        for li in el.findall("list-item"):
            items.append([block(ch) for ch in li if isinstance(ch.tag, str)])
        return {"t": "list", "ordered": el.get("list-type") == "order", "items": items}
    if tag == "table-wrap":
        cap = el.find("caption/title")
        rows = [[inlines(td) for td in tr if td.tag in ("td", "th")] for tr in el.iter("tr")]
        return {"t": "table", "id": el.get("id"), "caption": inlines(cap) if cap is not None else [], "rows": rows}
    if tag == "fig":
        return {"t": "figref", "id": el.get("id")}
    if tag == "code":
        return {"t": "code", "v": "".join(el.itertext())}
    raise UnknownElement(f"block <{tag}>")


def block_text(b):
    t = b["t"]
    if t == "p":
        return inline_text(b["c"])
    if t == "list":
        return "".join(block_text(x) for item in b["items"] for x in item)
    if t == "table":
        return inline_text(b["caption"]) + "".join(inline_text(c) for row in b["rows"] for c in row)
    if t == "code":
        return b["v"]
    return ""


# ---------- figures and references ----------

def figure(fig, where):
    g, m = fig.find("graphic"), fig.find("media")
    cap = fig.find("caption")
    cap_nodes = []
    if cap is not None:
        for p in cap.findall("p"):
            if cap_nodes:
                cap_nodes.append({"t": "text", "v": " "})
            cap_nodes.extend(inlines(p))
        if cap.find("title") is not None:
            cap_nodes = inlines(cap.find("title")) + ([{"t": "text", "v": " "}] if cap_nodes else []) + cap_nodes
    rec = {"id": fig.get("id"), "label": _text(fig.find("label")), "caption": cap_nodes, "where": where}
    if g is not None:
        rec["kind"], rec["src"] = "image", (g.get(XLINK) or "") + ".jpg"
    elif m is not None:
        rec["kind"], rec["src"] = "video", m.get(XLINK) or ""
    else:
        rec["kind"], rec["src"] = "none", ""
    return rec


def _names(pg):
    out = []
    for ch in pg:
        if ch.tag == "name":
            out.append(" ".join(x for x in (ch.findtext("surname"), ch.findtext("given-names")) if x))
        elif ch.tag == "collab":
            out.append(_text(ch))
    return out


def reference(ref):
    c = ref.find("element-citation")
    ids = {p.get("pub-id-type"): (p.text or "").strip() for p in c.findall("pub-id")} if c is not None else {}
    if c is None:
        return {"id": ref.get("id"), "label": _text(ref.find("label")), "text": _text(ref), "ids": ids}
    authors = []
    for pg in c.findall("person-group"):
        authors += _names(pg)
    authors += [_text(x) for x in c.findall("collab")]
    year = c.findtext("year") or _text(c.find("string-date"))
    vol, iss = c.findtext("volume"), c.findtext("issue")
    pages = c.findtext("page-range") or "-".join(x for x in (c.findtext("fpage"), c.findtext("lpage")) if x)
    parts = []
    if authors:
        parts.append(", ".join(authors) + ".")
    for t in ("article-title", "chapter-title"):
        if c.find(t) is not None:
            s = _text(c.find(t))
            parts.append(s if s.endswith((".", "?", "!")) else s + ".")
    if c.find("source") is not None:
        parts.append(_text(c.find("source")) + ".")
    pub = ": ".join(x for x in (c.findtext("publisher-loc"), c.findtext("publisher-name")) if x)
    if pub:
        parts.append(pub + ";")
    tail = year or ""
    if vol:
        tail += f";{vol}"
        if iss:
            tail += f"({iss})"
    if pages:
        tail += f":{pages}"
    if tail:
        parts.append(tail + ".")
    return {"id": ref.get("id"), "label": _text(ref.find("label")), "text": squash(" ".join(parts)).strip(), "ids": ids}


# ---------- article ----------

def extract(path):
    root = parse_xml(path)
    bp = root.find("book-part")
    if bp is None:
        return None
    meta = bp.find("book-part-meta")
    title = _text(meta.find("title-group/title"))
    authors = []
    for contrib in meta.iter("contrib"):
        n = contrib.find("name")
        name = " ".join(x for x in (n.findtext("given-names"), n.findtext("surname")) if x) if n is not None else _text(contrib.find("collab"))
        authors.append({"name": name, "aff": _text(contrib.find("aff")) or None})
    fname = path.name
    if fname.startswith("nurse-"):
        kind = "nursing"
    elif bp.get("indexed") == "no":
        kind = "archived"
    else:
        kind = "live"
    excluded = {"sections": [], "promo_paragraphs": 0}
    sections, figures = [], []
    body = bp.find("body")
    for sec in body.findall("sec") if body is not None else []:
        st = _text(sec.find("title"))
        if st in EXCLUDED_SECTIONS:
            excluded["sections"].append(st)
            continue
        blocks = []
        for ch in sec:
            if not isinstance(ch.tag, str) or ch.tag == "title":
                continue
            if ch.tag == "p" and _is_promo(ch):
                excluded["promo_paragraphs"] += 1
                continue
            if ch.tag == "fig":
                figures.append(figure(ch, sec.get("id")))
            if ch.tag == "sec":
                raise UnknownElement("nested sec")
            blocks.append(block(ch))
        sections.append({"id": sec.get("id"), "title": st, "title_c": inlines(sec.find("title")), "blocks": blocks})
    back = bp.find("back")
    refs = []
    if back is not None:
        for fg in back.findall("floats-group"):
            for fig in fg.findall("fig"):
                figures.append(figure(fig, "back"))
        for rl in back.findall("ref-list"):
            refs += [reference(r) for r in rl.findall("ref")]
    lic = root.find(".//license")
    rec = {
        "id": root.get("id"),
        "file": fname,
        "kind": kind,
        "title": title,
        "authors": authors,
        "updated": _date(meta.find("pub-history/date[@date-type='updated']")),
        "license_url": lic.get(XLINK) if lic is not None else None,
        "copyright": _text(root.find(".//copyright-statement")) or None,
        "sections": sections,
        "figures": figures,
        "references": refs,
        "excluded": excluded,
    }
    rec["content_hash"] = sha256_text(repr(rec))
    return rec


def body_text(rec):
    """All L1 body text (sections incl. headings), for fidelity checks."""
    out = []
    for s in rec["sections"]:
        out.append(s["title"])
        out += [block_text(b) for b in s["blocks"]]
    return "".join(out)


def source_body_text(path):
    """The same text taken straight from the XML, minus documented exclusions."""
    root = parse_xml(path)
    body = root.find("book-part/body")
    out = []
    for sec in body.findall("sec") if body is not None else []:
        if _text(sec.find("title")) in EXCLUDED_SECTIONS:
            continue
        for ch in sec:
            if not isinstance(ch.tag, str) or ch.tag == "fig" or (ch.tag == "p" and _is_promo(ch)):
                continue
            out.append("".join(ch.itertext()))
    return "".join(out)


def nbk_links(rec):
    """NBK accessions referenced by Bookshelf ext-links in the body."""
    found = []

    def walk(nodes):
        for n in nodes:
            if n["t"] == "link":
                m = re.search(r"ncbi\.nlm\.nih\.gov/books/(NBK\d+)", n["href"])
                if m:
                    found.append(m.group(1))
                walk(n["c"])
            elif n["t"] == "block":
                walk_b(n["b"])
            elif "c" in n:
                walk(n["c"])

    def walk_b(b):
        if b["t"] == "p":
            walk(b["c"])
        elif b["t"] == "list":
            for item in b["items"]:
                for x in item:
                    walk_b(x)
        elif b["t"] == "table":
            for row in b["rows"]:
                for c in row:
                    walk(c)

    for s in rec["sections"]:
        for b in s["blocks"]:
            walk_b(b)
    return found
