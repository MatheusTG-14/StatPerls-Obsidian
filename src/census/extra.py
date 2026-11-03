"""Phase 0 census, pass 3: subheading encoding, figure files, captions, images.

Usage: python -I src/census/extra.py <extracted_dir> <tar.gz> <out_json>
"""
import json
import re
import sys
import tarfile
from collections import Counter
from pathlib import Path

from lxml import etree
from PIL import Image

XL = "{http://www.w3.org/1999/xlink}href"
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
CREDIT = [
    ("public-domain", r"public domain"),
    ("cc-by-sa", r"CC[ -]BY[ -]SA|by-sa"),
    ("cc-by", r"CC[ -]BY|creativecommons"),
    ("wikimedia", r"wikimedia|wikipedia"),
    ("contributed", r"contributed by|courtesy of"),
    ("dermnet", r"dermnet"),
    ("openi", r"open-?i\b"),
]


def main(root, tgz, out):
    sys.stdout.reconfigure(encoding="utf-8")
    root = Path(root)
    bold_only_p = 0
    bold_only_examples = Counter()
    pubmed_excerpt = []
    graphic_refs = Counter()
    graphic_by_article = {}
    credit = Counter()
    no_credit_examples = []
    for p in sorted(root.glob("*.nxml")):
        if p.name in ("TOC.nxml", "contributors.nxml"):
            continue
        r = etree.parse(str(p), PARSER).getroot()
        for para in r.iter("p"):
            kids = list(para)
            if len(kids) == 1 and kids[0].tag == "bold" and not (para.text or "").strip() and not (kids[0].tail or "").strip():
                bold_only_p += 1
                bold_only_examples[" ".join("".join(kids[0].itertext()).split())[:60]] += 1
            if para.get("content-type") == "pubmed-excerpt" and len(pubmed_excerpt) < 3:
                pubmed_excerpt.append(etree.tostring(para, encoding="unicode")[:400])
        for f in r.iter("fig"):
            g = f.find("graphic")
            if g is not None:
                graphic_refs[g.get(XL)] += 1
                graphic_by_article.setdefault(g.get(XL), set()).add(p.name)
            cap = " ".join("".join(f.find("caption").itertext()).split()) if f.find("caption") is not None else ""
            hit = [k for k, rx in CREDIT if re.search(rx, cap, re.I)]
            credit[hit[0] if hit else "unclassified"] += 1
            if not hit and len(no_credit_examples) < 25:
                no_credit_examples.append(cap[:160])
    # images straight from the tarball (case-safe)
    dims, fmt, sizes = Counter(), Counter(), []
    bad = []
    with tarfile.open(tgz, "r:gz") as tf:
        for m in tf:
            if not m.isfile() or not m.name.lower().endswith(".jpg"):
                continue
            sizes.append(m.size)
            try:
                with Image.open(tf.extractfile(m)) as im:
                    fmt[im.format] += 1
                    w, h = im.size
                    long = max(w, h)
                    dims["<800" if long < 800 else "800-1999" if long < 2000 else "2000-3999" if long < 4000 else ">=4000"] += 1
            except Exception as e:  # noqa: BLE001 - census records, never raises
                bad.append([m.name, str(e)[:100]])
    sizes.sort()
    shared = Counter(len(v) for v in graphic_by_article.values())
    res = {
        "bold_only_p": bold_only_p,
        "bold_only_top": bold_only_examples.most_common(30),
        "pubmed_excerpt_examples": pubmed_excerpt,
        "distinct_graphic_refs": len(graphic_refs),
        "graphic_files_shared_by_n_articles": sorted(shared.items()),
        "credit_classes": credit.most_common(),
        "unclassified_caption_examples": no_credit_examples,
        "jpg_count": len(sizes),
        "jpg_bytes_median": sizes[len(sizes) // 2],
        "jpg_bytes_p95": sizes[int(len(sizes) * 0.95)],
        "jpg_bytes_max": sizes[-1],
        "image_formats_actual": fmt.most_common(),
        "long_edge_buckets": dims.most_common(),
        "unreadable": bad,
    }
    Path(out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(*sys.argv[1:4])
