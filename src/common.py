"""Shared helpers: safe XML parsing, whitespace normalization, LF-only writes."""
import hashlib
import json
import os
import re
from pathlib import Path

from lxml import etree

XLINK = "{http://www.w3.org/1999/xlink}href"
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)
_WS = re.compile(r"[ \t\r\n]+")


def parse_xml(path):
    return etree.parse(str(path), PARSER).getroot()


def read_schema(rel):
    """Text of a bundled schema file (e.g. "schema/vocab/facets.yaml"); also works inside the installer's .pyz."""
    p = Path(__file__).resolve().parents[1] / rel
    if p.is_file():
        return p.read_text(encoding="utf-8")
    import zipfile
    for parent in p.parents:
        if parent.is_file() and zipfile.is_zipfile(parent):
            with zipfile.ZipFile(parent) as z:
                return z.read(p.relative_to(parent).as_posix()).decode("utf-8")
    raise FileNotFoundError(rel)


def squash(s):
    """Collapse XML layout whitespace (not NBSP) to single spaces."""
    return _WS.sub(" ", s)


def no_ws(s):
    """Text with all whitespace removed, for fidelity comparison."""
    return re.sub(r"\s+", "", s)


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")  # write beside the target, then swap: an interrupted write keeps the old file
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def sha256_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
