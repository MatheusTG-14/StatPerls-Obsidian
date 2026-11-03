"""Fetch PubMed book records for StatPearls via NCBI E-utilities (DEC-11).

Saves raw efetch XML batches, then writes the article-ID -> NBK/PMID map.
Polite: no API key, at most 2 requests per second, tool name sent.

Usage: python -I src/acquire/eutils.py fetch <raw_dir>
       python -I src/acquire/eutils.py map <raw_dir> <out_json>
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from lxml import etree

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL = "statpearls-vault"
BATCH = 500
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True)


def get(endpoint, **params):
    params["tool"] = TOOL
    url = BASE + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read()
            time.sleep(0.5)
            return data
        except Exception as e:  # noqa: BLE001 - retried, then re-raised
            print(f"retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed: {endpoint}")


def fetch(raw_dir):
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    s = etree.fromstring(get("esearch.fcgi", db="pubmed", term='"StatPearls"[book]', usehistory="y", retmax=0), PARSER)
    count, webenv, qk = int(s.findtext("Count")), s.findtext("WebEnv"), s.findtext("QueryKey")
    print("count", count)
    for start in range(0, count, BATCH):
        out = raw / f"efetch_{start:05d}.xml"
        if out.exists():
            continue
        data = get("efetch.fcgi", db="pubmed", query_key=qk, WebEnv=webenv, retstart=start, retmax=BATCH, retmode="xml")
        out.write_bytes(data)
        print("saved", out.name, len(data))


def build_map(raw_dir, out_json):
    sys.stdout.reconfigure(encoding="utf-8")
    rows, mesh, kw = {}, 0, 0
    for f in sorted(Path(raw_dir).glob("efetch_*.xml")):
        for b in etree.parse(str(f), PARSER).getroot().iter("PubmedBookArticle"):
            d = b.find("BookDocument")
            t = d.find("ArticleTitle")
            part = t.get("part") if t is not None else None
            has_mesh = b.find(".//MeshHeadingList") is not None
            has_kw = d.find("KeywordList") is not None
            mesh += has_mesh
            kw += has_kw
            rows[part] = {
                "pmid": d.findtext("PMID"),
                "nbk": d.findtext("ArticleIdList/ArticleId[@IdType='bookaccession']"),
                "title": "".join(t.itertext()) if t is not None else None,
                "contribution_date": "-".join(x.zfill(2) for x in (d.findtext(f"ContributionDate/{k}") for k in ("Year", "Month", "Day")) if x) or None,
                "mesh": [m.findtext("DescriptorName") for m in b.iter("MeshHeading")],
                "keywords": [k.text for k in d.iter("Keyword")],
                "pub_types": [p.text for p in d.iter("PublicationType")],
            }
    Path(out_json).write_text(json.dumps(dict(sorted(rows.items(), key=lambda kv: kv[0] or "")), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"records {len(rows)}  with MeSH {mesh}  with keywords {kw}  missing part {sum(1 for k in rows if not k)}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fetch":
        fetch(sys.argv[2])
    elif cmd == "map":
        build_map(sys.argv[2], sys.argv[3])
