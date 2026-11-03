"""L1 (+ registry) -> vault/StatPearls. Deterministic (rule 5); vault/Mine untouched (rule 7).

mode: "pilot" (PILOT_SIZE varied articles, links limited to the pilot set)
      "all"   (live + nursing; archived only with "all+archived")
"""
import json
import os
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from src import progress
from src.common import read_json, read_schema, sha256_text, write_json, write_text
from src.extract.nxml import block_text, inline_text, nbk_links
from src.render import hubs, markdown as md
from src.render.links import TitleIndex
from src.render.search_index import build_index
from src.render.names import Registry, fold, sanitize
from src.render.tags import anatomy_region, anatomy_structure, article_type, credit_class, modality

PILOT_SIZE = 50
FOLDER = {"live": "Articles", "nursing": "Nursing", "archived": "Archived"}
EDITION = "StatPearls [Internet]. Treasure Island (FL): StatPearls Publishing"
LICENSE_NAME = {"https://creativecommons.org/licenses/by-nc-nd/4.0/": "CC BY-NC-ND 4.0", "http://creativecommons.org/licenses/by/4.0/": "CC BY 4.0"}


def y(v):
    """YAML scalar: JSON strings are valid YAML double-quoted scalars."""
    return json.dumps(v, ensure_ascii=False)


def frontmatter(fields):
    lines = ["---"]
    for k, v in fields:
        if v is None:
            continue
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                lines += [f"  - {y(x)}" for x in v]
        else:
            lines.append(f"{k}: {y(v)}")
    lines.append("---")
    return "\n".join(lines)


# ---------- selection ----------

def load_index(l1_dir):
    path = Path(l1_dir).parent / "l1_index.json"
    if path.exists():
        return read_json(path)
    idx = {}
    for p in sorted(Path(l1_dir).glob("*.json")):
        r = read_json(p)
        idx[r["id"]] = {
            "kind": r["kind"], "title": r["title"], "nbk": r["nbk"],
            "h2": [x["title"] for x in r["sections"]],
            "fig_kinds": [f["kind"] for f in r["figures"]],
            "fig_where": [f["where"] for f in r["figures"]],
            "has_table": any(b["t"] == "table" for x in r["sections"] for b in x["blocks"]),
            "has_code": any(b["t"] == "code" for x in r["sections"] for b in x["blocks"]),
            "nbk_links": nbk_links(r),
        }
    write_json(path, idx)
    return idx


def num(i):
    """Numeric part of 'article-123' / 'nurse-article-123', for stable ordering."""
    return int(i.rsplit("-", 1)[1])


def pick_pilot(idx):
    """Deterministic, varied: per type, plus coverage of tables, videos, code, NBK links, nursing."""
    live = sorted((i for i, e in idx.items() if e["kind"] == "live"), key=num)
    chosen = []

    def add(i):
        if i not in chosen:
            chosen.append(i)

    feats = [
        lambda e: e["has_table"],
        lambda e: "video" in e["fig_kinds"],
        lambda e: e["has_code"],
        lambda e: bool(e["nbk_links"]),
        lambda e: sum(1 for w in e["fig_where"] if w != "back") >= 2,
        lambda e: len(e["fig_kinds"]) >= 6,
    ]
    for f in feats:
        for i in [i for i in live if f(idx[i])][:2]:
            add(i)
    by_type = defaultdict(list)
    for i in live:
        by_type[article_type(idx[i])].append(i)
    for t in sorted(by_type):
        pool = by_type[t]
        step = max(1, len(pool) // 4)
        for i in pool[::step][:4]:
            add(i)
    for i in sorted((i for i, e in idx.items() if e["kind"] == "nursing"), key=num)[:2]:
        add(i)
    nbk_to_id = {e["nbk"]: i for i, e in idx.items()}
    for i in list(chosen):  # pull in NBK-link targets so the pilot shows real cross-links
        for n in idx[i]["nbk_links"]:
            t = nbk_to_id.get(n)
            if t and idx[t]["kind"] == "live" and len(chosen) < PILOT_SIZE:
                add(t)
    return set(chosen[:PILOT_SIZE])


# ---------- figures ----------

class Media:
    """Distinct image/video files used by the selection -> vault filenames + figure notes."""

    def __init__(self, recs, registry, members):
        self.uses = defaultdict(list)  # src -> [(rec, fig)]
        for i in sorted(recs, key=lambda x: (KIND_ORDER[recs[x]["kind"]], num(x))):
            for f in recs[i]["figures"]:
                if f["kind"] != "none":
                    self.uses[f["src"]].append((recs[i], f))
        self.file = {src: m["file"] for src, m in members.items()}
        self.note = {}
        for src in sorted(self.uses):
            rec, f = self.uses[src][0]
            want = sanitize(f"{rec['title']} - {f['label'] or 'Figure'}")
            self.note[src] = registry.assign("figures", src, want, src.rsplit(".", 1)[0][:40])

    def vault_name(self, src):
        return self.file[src]


KIND_ORDER = {"live": 0, "nursing": 1, "archived": 2}


def caption_md(f, ctx):
    ctx.no_auto += 1
    s = md.inl(f["caption"], ctx)
    ctx.no_auto -= 1
    return s


def figure_block(f, media, ctx, heading):
    name = media.vault_name(f["src"])
    note = media.note[f["src"]]
    label = md.esc(f["label"]) if f["label"] else "Figure"
    lines = [f"{heading} {label}" if heading else f"**{label}**", "", f"![[{name}]]", ""]
    cap = caption_md(f, ctx)
    lines.append(f"{cap} ([[{note}|figure note]])" if cap else f"[[{note}|figure note]]")
    return "\n".join(lines)


# ---------- article note ----------

def drug_class_sections(classes_of):
    """{stem: [drug-class slugs]} -> Pharmacology hub sections by vocabulary area (DEC-23); classless drugs last."""
    from src.enrich.tagging import DRUG_VOCAB
    sections = {}
    for d in DRUG_VOCAB:
        stems = [s for s, cs in classes_of.items() if d["slug"] in cs]
        sections.setdefault(d["area"], []).append((d["label"], stems))
    sections["Unclassified"] = [("No class", [s for s, cs in classes_of.items() if not cs])]
    return list(sections.items())


def facet_tags(facets):
    return [f"{k}/{v}" for k in ("population", "setting", "discipline", "pathogen", "drug-class") for v in sorted(facets.get(k, []))]


def auto_tags(auto):
    """Placed by deterministic heuristics, not by an agent answer or a user correction (installer spec 3.4)."""
    return ["status/auto-classified"] if auto else []


def render_article(rec, stem, ctx, media, atype, system):
    nbk = rec.get("nbk")
    src_url = f"https://www.ncbi.nlm.nih.gov/books/{nbk}/" if nbk else None
    lic = LICENSE_NAME.get(rec["license_url"], rec["license_url"])
    primary, secondary, rule, sub, facets, *rest = system
    tags = [f"type/{atype}"] + [f"system/{primary}" + (f"/{sub}" if sub else "")] + [f"system/{c}" for c in secondary]
    tags += facet_tags(facets)
    region = anatomy_region(rec["title"])
    if region:
        tags.append(f"region/{region}")
    if rec["kind"] != "live":
        tags.append(f"status/{rec['kind']}")
    tags += auto_tags(bool(rest and rest[0]))
    aliases = []
    if rec["title"] != stem:
        aliases.append(rec["title"])
    structure = anatomy_structure(rec["title"])
    if structure:
        aliases.append(structure)
    fm = frontmatter([
        ("title", rec["title"]),
        ("aliases", aliases),
        ("article_id", rec["id"]),
        ("nbk", nbk),
        ("pmid", rec.get("pmid")),
        ("authors", [a["name"] for a in rec["authors"]]),
        ("last_update", rec["updated"]),
        ("edition", "StatPearls [Internet]"),
        ("article_type", atype),
        ("system", primary),
        ("systems", secondary),
        ("system_rule", rule),
        ("subsystem", sub),
        ("status", rec["kind"]),
        ("source", src_url),
        ("pubmed", f"https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/" if rec.get("pmid") else None),
        ("license", lic),
        ("n_figures", len([f for f in rec["figures"] if f["kind"] != "none"])),
        ("tags", tags),
    ])
    ctx.refs = {r["id"]: k for k, r in enumerate(rec["references"], 1)}
    figs_inline = {}
    for f in rec["figures"]:
        if f["where"] != "back" and f["kind"] != "none":
            figs_inline[f["id"]] = figure_block(f, media, ctx, heading=None)
    ctx.figs = figs_inline
    out = [fm, "", hubs.menu_line(primary, secondary, atype, sub, rec.get("nbk"), rec.get("pmid")), ""]
    for s in rec["sections"]:
        out.append(f"## {md.esc(s['title'])}")
        out.append("")
        for b in s["blocks"]:
            text = md.block(b, ctx, 0)
            if text:
                out.append(text)
                out.append("")
    back = [f for f in rec["figures"] if f["where"] == "back" and f["kind"] != "none"]
    if back:
        out.append("## Figures")
        out.append("")
        for f in back:
            out.append(figure_block(f, media, ctx, heading="###"))
            out.append("")
    if rec["references"]:
        out.append("## References")
        out.append("")
        for k, r in enumerate(rec["references"], 1):
            line = f"{k}. {md.esc(r['text'])}"
            if r["ids"].get("pmid"):
                line += f" [PubMed](https://pubmed.ncbi.nlm.nih.gov/{r['ids']['pmid']}/)"
            out.append(f"{line} ^ref-{k}")  # block ID: target of the in-text citation links
        out.append("")
    out.append(f"> [!info] StatPearls snapshot, last updated {rec['updated']}")
    out.append(f"> {md.esc(', '.join(a['name'] for a in rec['authors']))}.")
    src_line = f"[NCBI Bookshelf {nbk}]({src_url})" if src_url else "NCBI Bookshelf"
    out.append(f"> Source: {src_line} · {lic} · Educational use only, not for point-of-care decisions.")
    out.append("")
    out.append("---")
    out.append("")
    authors = ", ".join(a["name"] for a in rec["authors"])
    out.append(
        f"*{md.esc(authors)}. {md.esc(rec['title'])}. In: {EDITION}; 2026 Jan-. Last update {rec['updated']}. "
        f"{rec.get('copyright') or ''} {lic}. Converted for private study; not to be shared.*".replace("  ", " ")
    )
    return "\n".join(out) + "\n"


def render_figure_note(src, media, stems, kind, primaries):
    uses = media.uses[src]
    rec0, f0 = uses[0]
    cap0 = inline_text(f0["caption"])
    mod = modality(cap0, kind)
    name = media.vault_name(src)
    arts = []
    for rec, _ in uses:
        if rec["id"] in stems and f"[[{stems[rec['id']]}]]" not in arts:
            arts.append(f"[[{stems[rec['id']]}]]")
    article_types = sorted({article_type(r) for r, _ in uses})
    fm = frontmatter([
        ("title", media.note[src]),
        ("image", f"[[{name}]]"),
        ("media_kind", kind),
        ("figure_ids", [f["id"] for _, f in uses]),
        ("articles", arts),
        ("credit_class", credit_class(cap0)),
        ("modality", mod),
        ("modality_source", "caption-rule" if mod != "unclassified" else None),
        ("tags", ["type/figure", f"image/{mod}"] + [f"article-type/{t}" for t in article_types]
         + [f"system/{c}" for c in sorted({primaries[r["id"]] for r, _ in uses if r["id"] in primaries}, key=lambda x: (hubs.ORDER[x.split("/")[0]], x))]),
    ])
    out = [fm, "", f"![[{name}]]", ""]
    ctx = md.Ctx(None)
    for rec, f in uses:
        where = f"[[{stems[rec['id']]}]]" if rec["id"] in stems else md.esc(rec["title"])
        out.append(f"**{md.esc(f['label'] or 'Figure')}** in {where}: {caption_md(f, ctx)}")
        out.append("")
    return "\n".join(out)


# ---------- hubs ----------

AUTO_BASE = "Auto-classified.base"

BASES = {
    "All articles.base": """filters:
  and:
    - file.inFolder("StatPearls/Articles")
views:
  - type: table
    name: All articles
    order:
      - file.name
      - article_type
      - last_update
      - n_figures
    sort:
      - property: file.name
        direction: ASC
  - type: table
    name: Recently updated
    order:
      - file.name
      - article_type
      - last_update
    sort:
      - property: last_update
        direction: DESC
""",
    "Figures gallery.base": """filters:
  and:
    - file.inFolder("StatPearls/Figures")
views:
  - type: cards
    name: All figures
    image: note.image
    order:
      - file.name
      - modality
      - credit_class
  - type: cards
    name: Histology
    image: note.image
    filters:
      and:
        - modality == "histology"
  - type: cards
    name: Radiology
    image: note.image
    filters:
      or:
        - modality == "radiograph"
        - modality == "ct"
        - modality == "mri"
        - modality == "ultrasound"
  - type: cards
    name: Clinical photos
    image: note.image
    filters:
      and:
        - modality == "clinical-photo"
""",
}
TYPE_BASE = """filters:
  and:
    - file.inFolder("StatPearls/Articles")
    - article_type == "{t}"
views:
  - type: table
    name: {t}
    order:
      - file.name
      - last_update
      - n_figures
"""


# ---------- categories and hub pages (DEC-18) ----------

def load_systems(ids, reg, path="data/l2/system.json"):
    """article -> (primary, secondary, rule); primary is sticky in the registry (rule 11 spirit)."""
    l2 = read_json(path) if Path(path).exists() else {}
    if not l2:
        print("warning: no data/l2/system.json; every article goes to General and Professional (run sp.py classify)")
    out = {}
    for i in sorted(ids):
        e = l2.get(i)
        if e is None:  # not classified yet: render as general, but pin nothing
            out[i] = ("general", [], "fallback", None, {}, False)
            continue
        primary = reg.sticky("system", i, e["primary"], force=e["rule"] in ("override", "agent", "agent-recheck"))
        secondary = ([e["primary"]] if e["primary"] != primary else []) + [c for c in e["secondary"] if c != primary]
        # subcategory only while it belongs to the pinned category (else the category's "Other")
        from src.enrich.system import SUBCATEGORIES
        subs = [s["slug"] for s in SUBCATEGORIES.get(primary, [])]
        sub = e.get("sub") if e.get("sub") in subs else (subs[-1] if subs else None)
        out[i] = (primary, secondary[:3], e["rule"], sub, e.get("facets", {}), bool(e.get("auto")))
    return out


def recorded_overrides():
    """Corrections already harvested into the user override files -> ({id: category slug}, {id: 'cat/sub'})."""
    import yaml
    out = []
    for f in ("system.yaml", "subsystem.yaml"):
        p = Path("schema/overrides") / f
        out.append((yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {})
    return tuple(out)


def article_path(root, kind, primary, stem, sub=None):
    if kind == "live":
        return root / "Articles" / hubs.FOLDER[primary] / f"{stem}.md"  # subcategory is a tag, not a folder (DEC-21)
    return root / FOLDER[kind] / f"{stem}.md"


DISCIPLINES = ("Physiology", "Biochemistry", "Histology", "Embryology", "Genetics", "Neuroanatomy", "Microbiology")


def hub_pages(ids, idx, stems, types, systems, bases):
    """-> sorted [(stem, text)] for Home, category hubs and theme hubs."""
    from src.enrich.system import CATEGORIES
    pages = {}
    by_cat = defaultdict(lambda: defaultdict(list))
    by_sub = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    also = defaultdict(list)
    for i in ids:
        primary, secondary, _, sub, *_ = systems[i]
        by_cat[primary][types[i]].append(stems[i])
        if sub:
            by_sub[primary][sub][types[i]].append(stems[i])
        for c in secondary:
            also[c].append(stems[i])
    rel = hubs.related({i: v[:2] for i, v in systems.items()})  # (primary, secondary)
    for c in CATEGORIES:
        render = hubs.render_subcategory_hub if c["slug"] in hubs.SUBCATEGORIES else hubs.render_category_hub
        members = by_sub[c["slug"]] if c["slug"] in hubs.SUBCATEGORIES else by_cat[c["slug"]]
        pages[hubs.hub_stem(c["folder"])] = render(c, members, also[c["slug"]], rel.get(c["slug"], []))

    def by_folder(sel):
        g = defaultdict(list)
        for i in ids:
            if sel(i):
                g[systems[i][0]].append(stems[i])
        return [(hubs.FOLDER[c["slug"]], g[c["slug"]]) for c in CATEGORIES]

    regions = defaultdict(list)
    for i in ids:
        if types[i] == "anatomy":
            m = re.match(r"(?:Anatomy|Neuroanatomy), ([^:,]+)[:,]", idx[i]["title"])
            regions[m.group(1).strip() if m else "Other"].append(stems[i])
    disc = defaultdict(list)
    for i in ids:
        t = idx[i]["title"]
        d = next((x for x in DISCIPLINES if t.startswith(x + ",")), None)
        if d or types[i] == "basic-science":
            disc[d or "Other"].append(stems[i])
    themes = {
        "Anatomy": sorted(regions.items(), key=lambda kv: (kv[0] == "Other", kv[0])),
        "Basic Science Disciplines": [(d, disc[d]) for d in DISCIPLINES + ("Other",)],
        "Pharmacology": None,  # sectioned by drug class below
        "Procedures": by_folder(lambda i: types[i] == "procedure"),
        "Lab Tests": by_folder(lambda i: types[i] == "lab-test"),
        "Nursing": by_folder(lambda i: types[i] == "nursing"),
        "EMS": [("EMS", [stems[i] for i in ids if idx[i]["title"].startswith("EMS ")])],
        "Osteopathic": [("Osteopathic", [stems[i] for i in ids if idx[i]["title"].startswith("Osteopathic")])],
    }
    for name, groups in themes.items():
        if groups is not None:
            pages[hubs.hub_stem(name)] = hubs.render_list_hub(name, groups)
    drugs = {stems[i]: systems[i][4].get("drug-class", []) for i in ids if types[i] == "drug"}
    pages[hubs.hub_stem("Pharmacology")] = hubs.render_sectioned_hub("Pharmacology", drug_class_sections(drugs))
    pages[hubs.hub_stem(hubs.HOME)] = hubs.render_home(list(themes), bases, Counter(systems[i][0] for i in ids))
    return sorted(pages.items())


# ---------- build ----------

def build(l1_dir, vault, mode="pilot", media_dir="data/media", members_json="data/meta/media_members.json"):
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.perf_counter()

    def lap(msg):
        print(f"[{time.perf_counter() - t0:6.1f}s] {msg}", flush=True)

    vault = Path(vault)
    root = vault / "StatPearls"
    idx = load_index(l1_dir)
    if mode == "pilot":
        ids = pick_pilot(idx)
    elif mode == "all+archived":
        ids = set(idx)
    else:
        ids = {i for i, e in idx.items() if e["kind"] in ("live", "nursing")}
    recs = {i: read_json(Path(l1_dir) / f"{i}.json") for i in sorted(ids)}
    lap(f"loaded {len(recs)} records ({mode})")
    reg = Registry("data/registry.json")
    stems_all = {}
    for i in sorted(idx, key=lambda x: (KIND_ORDER[idx[x]["kind"]], num(x))):  # stable across modes
        stems_all[i] = reg.assign("articles", i, sanitize(idx[i]["title"]), idx[i].get("nbk") or i)
    stems = {i: stems_all[i] for i in ids}
    live_stems = {i: s for i, s in stems.items() if idx[i]["kind"] == "live"}
    types = {i: article_type(recs[i]) for i in ids}
    from src.enrich.harvest import pending_changes
    built_manifest = root / "_meta" / "build-manifest.json"
    if (root / "Articles").exists():  # before load_systems: compare with what the last build rendered
        recorded = recorded_overrides()
        pending = pending_changes(root, live_stems, dict(reg.maps.get("system", {})),
                                  read_json(built_manifest).get("subs", {}) if built_manifest.exists() else {},
                                  built_manifest.stat().st_mtime if built_manifest.exists() else None,
                                  recorded=recorded[0], recorded_subs=recorded[1])
        if pending:
            raise SystemExit(f"{len(pending)} category changes made in Obsidian are not harvested yet: run `python -I sp.py harvest` first")
    systems = load_systems(ids, reg)
    entries = []
    for i in live_stems:
        entries.append((idx[i]["title"], i))
        st = anatomy_structure(idx[i]["title"])
        if st and len(st.split()) >= 2:
            entries.append((st, i))
    index = TitleIndex(entries)
    nbk_to_id = {e["nbk"]: i for i, e in idx.items() if e.get("nbk")}
    media = Media(recs, reg, read_json(members_json))
    lap(f"index {len(index.keys)} link keys, {len(media.uses)} media files")
    old_manifest = root / "_meta" / "build-manifest.json"
    old_paths = sorted(read_json(old_manifest)["files"]) if old_manifest.exists() else []
    for sub in ("Articles", "Nursing", "Archived", "Figures", "Hubs", "_meta"):
        shutil.rmtree(root / sub, ignore_errors=True)
    stats = Counter()
    link_counts = {}
    manifest = {}
    search_sections = []

    def emit(path, text):
        write_text(path, text)
        manifest[path.relative_to(root).as_posix()] = sha256_text(text)

    for k, i in enumerate(sorted(ids), 1):
        progress.tick("notes", k, len(ids), "notes")
        rec = recs[i]
        ctx = md.Ctx(i, index, live_stems, nbk_to_id)
        emit(article_path(root, rec["kind"], systems[i][0], stems[i], systems[i][3]), render_article(rec, stems[i], ctx, media, types[i], systems[i]))
        link_counts[i] = len(ctx.links_out)
        stats["articles"] += 1
        stats["links"] += len(ctx.links_out)
        if rec["kind"] in ("live", "nursing"):
            search_sections += [(stems[i], s["title"], " ".join(block_text(b) for b in s["blocks"])) for s in rec["sections"]]
    lap("articles written")
    with progress.stage("search"):
        for rel, text in build_index(search_sections).items():
            emit(root / "_meta" / "search" / rel, text)
    lap(f"search index written ({len(search_sections)} sections)")
    for k, src in enumerate(sorted(media.uses), 1):
        progress.tick("figure-notes", k, len(media.uses), "figure notes")
        kind = media.uses[src][0][1]["kind"]
        emit(root / "Figures" / f"{media.note[src]}.md", render_figure_note(src, media, stems, kind, {i: v[0] + (f"/{v[3]}" if v[3] else "") for i, v in systems.items()}))
        stats["figure_notes"] += 1
    lap("figure notes written")
    att = root / "_attachments"
    att.mkdir(parents=True, exist_ok=True)
    needed = {media.vault_name(s) for s in media.uses}
    for old in att.iterdir():
        if old.name not in needed:
            old.unlink()
    for name in sorted(needed):
        dest = att / name
        if not dest.exists():
            try:
                os.link(Path(media_dir) / name, dest)  # same volume: instant, no extra disk
            except OSError:
                shutil.copyfile(Path(media_dir) / name, dest)
    stats["attachments"] = len(needed)
    lap("attachments linked")
    for name, body in BASES.items():
        emit(root / "Hubs" / name, body)
    for t in sorted(set(types.values())):
        emit(root / "Hubs" / f"Type - {t}.base", TYPE_BASE.format(t=t))
    bases = list(BASES) + [f"Type - {t}.base" for t in sorted(set(types.values()))]
    if any(v[5] for v in systems.values()):  # only when something was placed automatically
        emit(root / "Hubs" / AUTO_BASE, read_schema("schema/bases/" + AUTO_BASE))
        bases.append(AUTO_BASE)
    for stem, text in hub_pages(ids, idx, stems, types, systems, bases):
        emit(root / "Hubs" / f"{stem}.md", text)
        stats["hubs"] += 1
    new_paths = {Path(k).name: k for k in manifest if k.endswith(".md")}
    moves = {k: new_paths[Path(k).name] for k in old_paths if k.endswith(".md") and Path(k).name in new_paths and new_paths[Path(k).name] != k}
    write_json(Path("data/reports") / "moves.json", moves)
    emit(root / "_meta" / "About this vault.md", ABOUT)
    reg.save()
    manifest = dict(sorted(manifest.items()))
    report = {
        "mode": mode,
        "stats": dict(stats),
        "vault_hash": sha256_text(json.dumps(manifest, sort_keys=True)),
        "link_density": {
            "max": max(link_counts.values(), default=0),
            "mean": round(sum(link_counts.values()) / max(1, len(link_counts)), 1),
            "zero_link_notes": sum(1 for v in link_counts.values() if v == 0),
        },
        "ambiguous_link_keys": len(index.ambiguous),
    }
    rendered_subs = {stems[i]: f"{v[0]}/{v[3]}" for i, v in sorted(systems.items()) if v[3] and idx[i]["kind"] == "live"}
    write_json(root / "_meta" / "build-manifest.json", {"report": report, "files": manifest, "subs": rendered_subs})
    write_json(Path("data/reports") / f"build-{mode}.json", report)
    lap("done")
    print(json.dumps(report, indent=1))


ABOUT = """# About this vault

Generated from the StatPearls archive (NLM LitArch, NBK430685) for private study.
Everything under `StatPearls/` is rebuilt by the pipeline; put your own notes in `Mine/`.

- Content: StatPearls Publishing, CC BY-NC-ND 4.0. Not to be shared or published.
- Educational snapshot: check each note's last update date. Not for point-of-care decisions.
- Excluded on purpose: Review Questions sections and question-bank promotion lines.
"""
