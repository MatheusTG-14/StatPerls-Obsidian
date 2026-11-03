"""Phase 0 census, pass 2: per-article facts for the StatPearls BITS archive.

Writes one JSON line per book-part file plus a summary. Images are checked
against the tarball member list (not the extracted folder), because NTFS
case-insensitivity drops case-colliding files on extraction.

Usage: python -I src/census/articles.py <extracted_dir> <tar_listing_files.txt> <out_dir>
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

XL = "{http://www.w3.org/1999/xlink}href"
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)


def text(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def date_of(el):
    if el is None:
        return None
    y, m, d = (el.findtext(t) for t in ("year", "month", "day"))
    return "-".join(x.zfill(2) for x in (y, m, d) if x) or None


def toc_index(path):
    tree = etree.parse(str(path), PARSER)
    out = {}
    for e in tree.iter("toc-entry"):
        ro = e.find(".//related-object")
        if ro is not None:
            out[ro.get("document-id")] = text(e.find("title"))
    return out


def article(path, members_ci):
    tree = etree.parse(str(path), PARSER)
    r = tree.getroot()
    bp = r.find("book-part")
    if bp is None:
        return {"file": path.name, "kind": "non-article"}
    meta = bp.find("book-part-meta")
    body = bp.find("body")
    h2 = [text(s.find("title")) for s in body.findall("sec")] if body is not None else []
    sec_types = [s.get("sec-type") for s in body.findall("sec")] if body is not None else []
    figs = r.findall(".//fig")
    graphics = [g.get(XL) for g in r.iter("graphic")]
    missing, ambiguous = [], []
    for g in graphics:
        hits = members_ci.get((g or "").lower() + ".jpg", [])
        exact = [h for h in hits if h == g + ".jpg"]
        if not exact:
            missing.append(g)
        if len(hits) > 1:
            ambiguous.append(g)
    fig_ids = [f.get("id") for f in figs]
    xref_types = Counter(x.get("ref-type") for x in r.iter("xref"))
    ext = [e.get(XL) or "" for e in r.iter("ext-link")]
    ext_kind = Counter()
    for h in ext:
        if "statpearls.com" in h:
            ext_kind["statpearls.com"] += 1
        elif re.search(r"ncbi\.nlm\.nih\.gov/books/NBK\d+", h):
            ext_kind["bookshelf-NBK"] += 1
        elif "pubmed" in h:
            ext_kind["pubmed"] += 1
        elif "ncbi.nlm.nih.gov/pmc" in h:
            ext_kind["pmc"] += 1
        elif "wikimedia" in h or "wikipedia" in h:
            ext_kind["wikimedia"] += 1
        else:
            ext_kind["other"] += 1
    span = sum(1 for td in r.iter("td", "th") if td.get("rowspan", "1") != "1" or td.get("colspan", "1") != "1")
    nested_tbl = sum(1 for t in r.iter("table") if t.find(".//table") is not None)
    block_in_cell = sum(1 for td in r.iter("td") if td.find(".//list") is not None or len(td.findall("p")) > 1)
    pub_ids = Counter(p.get("pub-id-type") for p in r.iter("pub-id"))
    captions = [text(f.find("caption")) for f in figs]
    return {
        "file": path.name,
        "kind": "nurse" if path.name.startswith("nurse-") else "article",
        "id": r.get("id"),
        "title": text(meta.find("title-group/title")),
        "indexed": bp.get("indexed", "yes"),
        "updated": date_of(meta.find("pub-history/date[@date-type='updated']")),
        "pub_date": date_of(r.find("book-meta/pub-date")),
        "n_authors": len(meta.findall(".//contrib")),
        "h2": h2,
        "sec_types": sec_types,
        "n_sec": len(r.findall(".//sec")),
        "max_sec_depth": max((sum(1 for _ in s.iterancestors("sec")) for s in r.iter("sec")), default=-1) + 1,
        "n_p": sum(1 for _ in r.iter("p")),
        "chars": len(text(body)),
        "n_fig": len(figs),
        "dup_fig_ids": len(fig_ids) - len(set(fig_ids)),
        "n_graphic": len(graphics),
        "graphic_missing": missing,
        "graphic_case_ambiguous": ambiguous,
        "graphic_mimetypes": sorted({g.get("mimetype") or "" for g in r.iter("graphic")}),
        "fig_in_body": sum(1 for f in figs if any(a.tag == "body" for a in f.iterancestors())),
        "captions": captions,
        "n_media": sum(1 for _ in r.iter("media")),
        "media": [m.get(XL) for m in r.iter("media")],
        "xref_types": dict(xref_types),
        "ext_kind": dict(ext_kind),
        "n_tables": sum(1 for _ in r.iter("table")),
        "span_cells": span,
        "nested_tables": nested_tbl,
        "block_cells": block_in_cell,
        "n_ref": sum(1 for _ in r.iter("ref")),
        "pub_id_types": dict(pub_ids),
        "n_sup": sum(1 for _ in r.iter("sup")),
        "n_sub": sum(1 for _ in r.iter("sub")),
        "n_code": sum(1 for _ in r.iter("code")),
        "p_content_types": sorted({p.get("content-type") for p in r.iter("p") if p.get("content-type")}),
        "license": (r.find(".//license") is not None and r.find(".//license").get(XL)) or None,
    }


def main(root, listing, out_dir):
    root, out_dir = Path(root), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    members_ci = {}
    for line in Path(listing).read_text(encoding="utf-8").splitlines():
        name = line.split("/", 1)[-1]
        members_ci.setdefault(name.lower(), []).append(name)
    toc = toc_index(root / "TOC.nxml")
    rows = []
    with open(out_dir / "articles.jsonl", "w", encoding="utf-8") as fh:
        for p in sorted(root.glob("*.nxml")):
            if p.name in ("TOC.nxml",):
                continue
            row = article(p, members_ci)
            row["in_toc"] = row.get("id") in toc
            rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(len(rows), "rows; toc entries", len(toc))


if __name__ == "__main__":
    main(*sys.argv[1:4])
