"""Phase 0 census, pass 1: layout-agnostic inventory of the extracted archive.

Counts files by extension and size, and element/attribute frequencies across
all XML files, so the extractor can be designed against measured structure.

Usage: python -I -m src.census.tags <extracted_root> <out_json>
(run from the repo root; archive data is read, never executed)
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree

XML_EXT = {".nxml", ".xml"}


def local(tag):
    return etree.QName(tag).localname if isinstance(tag, str) else None


def main(root, out):
    root = Path(root)
    ext_count, ext_bytes = Counter(), Counter()
    tags, attrs = Counter(), Counter()
    tag_files = Counter()
    parse_errors = []
    dirs = Counter()
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        ext_count[ext] += 1
        ext_bytes[ext] += p.stat().st_size
        dirs[str(p.parent.relative_to(root)).split("\\")[0].split("/")[0]] += 1
        if ext not in XML_EXT:
            continue
        try:
            tree = etree.parse(str(p), parser)
        except etree.XMLSyntaxError as e:
            parse_errors.append([str(p.relative_to(root)), str(e)[:200]])
            continue
        seen = set()
        for el in tree.iter():
            name = local(el.tag)
            if name is None:
                continue
            tags[name] += 1
            seen.add(name)
            for a in el.attrib:
                attrs[f"{name}@{local(a)}"] += 1
        tag_files.update(seen)
    result = {
        "files_by_ext": dict(ext_count.most_common()),
        "bytes_by_ext": dict(ext_bytes.most_common()),
        "top_level_entries": len(dirs),
        "parse_errors": parse_errors,
        "tags": dict(tags.most_common()),
        "tag_in_n_files": dict(tag_files.most_common()),
        "attrs": dict(attrs.most_common()),
    }
    Path(out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("files_by_ext", "bytes_by_ext", "top_level_entries")}, indent=1))
    print("parse_errors:", len(parse_errors))


if __name__ == "__main__":
    main(*sys.argv[1:3])
