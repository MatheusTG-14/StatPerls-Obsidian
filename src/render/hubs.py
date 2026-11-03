"""Hub notes and the per-article hub menu line (spec 4.4-4.5). Pure functions, deterministic."""
import json
from collections import Counter, defaultdict

from src.enrich.system import CATEGORIES, ORDER, SUBCATEGORIES
from src.render.names import fold
from src.render.tags import ARTICLE_TYPES

FOLDER = {c["slug"]: c["folder"] for c in CATEGORIES}
TYPE_HUB = {"drug": "Pharmacology", "procedure": "Procedures", "lab-test": "Lab Tests", "anatomy": "Anatomy",
            "basic-science": "Basic Science Disciplines", "nursing": "Nursing", "toxicology": "Toxicology"}
TYPE_LABEL = {"disease": "Diseases", "procedure": "Procedures", "concept": "Concepts", "drug": "Drugs", "anatomy": "Anatomy",
              "basic-science": "Basic Science", "toxicology": "Toxicology", "lab-test": "Lab Tests", "nursing": "Nursing", "other": "Other"}
HOME = "Home"


def hub_stem(name):
    return f"{name} (hub)"


def hub_link(name):
    return f"[[{hub_stem(name)}|{name}]]"


SUBFOLDER = {s["slug"]: s["folder"] for subs in SUBCATEGORIES.values() for s in subs}


def menu_line(primary, secondary, atype, sub=None, nbk=None, pmid=None):
    names = [FOLDER[primary]] + [FOLDER[s] for s in secondary]
    th = TYPE_HUB.get(atype)
    if th and th not in names:
        names.append(th)
    head = hub_link(names[0])
    if sub:
        head += f" › [[{hub_stem(names[0])}#{SUBFOLDER[sub]}|{SUBFOLDER[sub]}]]"
    web = ([f"[Bookshelf](https://www.ncbi.nlm.nih.gov/books/{nbk}/)"] if nbk else []) + (
        [f"[PubMed](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)"] if pmid else [])
    return f"> [!hubs] {hub_link(HOME)} › " + " · ".join([head] + [hub_link(n) for n in names[1:]] + web)


def _fm(aliases):
    lines = ["---"]
    if aliases:
        lines.append("aliases:")
        lines += [f"  - {json.dumps(a, ensure_ascii=False)}" for a in aliases]
    lines += ["tags:", '  - "type/hub"', "---"]
    return "\n".join(lines)


def _groups(groups):
    groups = [(label, sorted(stems, key=fold)) for label, stems in groups if stems]
    fold_mark = "-" if len(groups) > 1 else "+"
    out = []
    for label, stems in groups:
        out.append(f"> [!hub-list]{fold_mark} {label} ({len(stems)})")
        out += [f"> - [[{s}]]" for s in stems]
        out.append("")
    return out


def _page(name, aliases, related, groups):
    out = [_fm(aliases), f"{hub_link(HOME)} › {name}", ""]
    if related:
        out += ["Related: " + " · ".join(hub_link(FOLDER[r]) for r in related), ""]
    out += _groups(groups)
    return "\n".join(out).rstrip("\n") + "\n"


def render_category_hub(cat, primary_members, also, related):
    groups = [(TYPE_LABEL[t], primary_members.get(t, [])) for t in ARTICLE_TYPES] + [("Also relevant", also)]
    return _page(cat["folder"], cat["aliases"], related, groups)


def render_subcategory_hub(cat, members_by_sub, also, related):
    """Category with subcategories: one `## Subcategory` heading each (menu lines link to it), type groups inside."""
    out = [_fm(cat["aliases"]), f"{hub_link(HOME)} › {cat['folder']}", ""]
    if related:
        out += ["Related: " + " · ".join(hub_link(FOLDER[r]) for r in related), ""]
    for s in SUBCATEGORIES[cat["slug"]]:
        groups = [(TYPE_LABEL[t], members_by_sub.get(s["slug"], {}).get(t, [])) for t in ARTICLE_TYPES]
        if any(g for _, g in groups):
            out += [f"## {s['folder']}", ""] + _groups(groups)
    if also:
        out += ["## Also relevant", ""] + _groups([("Also relevant", also)])
    return "\n".join(out).rstrip("\n") + "\n"


def render_list_hub(name, groups):
    return _page(name, [], [], groups)


def render_sectioned_hub(name, sections):
    """sections: [(heading, [(label, stems)])]; one `## heading` per section that has members."""
    out = [_fm([]), f"{hub_link(HOME)} › {name}", ""]
    for heading, groups in sections:
        if any(stems for _, stems in groups):
            out += [f"## {heading}", ""] + _groups(groups)
    return "\n".join(out).rstrip("\n") + "\n"


def related(assign, n=4):
    """assign: article -> (primary, secondary). Per category, the n categories it most often co-occurs with."""
    co = defaultdict(Counter)
    for primary, secondary in assign.values():
        for s in secondary:
            co[primary][s] += 1
            co[s][primary] += 1
    return {c: [k for k, _ in sorted(cnt.items(), key=lambda kv: (-kv[1], ORDER[kv[0]]))[:n]] for c, cnt in co.items()}


def render_home(theme_hubs, bases, counts):
    """The statpearls-home block feeds the local plugin's search page; the lists below are the plugin-off fallback."""
    data = {"categories": [{"name": c["folder"], "hub": hub_stem(c["folder"]), "count": counts.get(c["slug"], 0)} for c in CATEGORIES],
            "themes": [{"name": t, "hub": hub_stem(t)} for t in theme_hubs], "tables": list(bases)}
    out = [_fm([]), "```statpearls-home", json.dumps(data, ensure_ascii=False, sort_keys=True), "```", "", "Browse StatPearls by category, by theme, or in table views. Every article's top bar links back here.", "",
           "## Categories", ""]
    out += [f"- {hub_link(c['folder'])}" for c in CATEGORIES]
    out += ["", "## Themes", ""]
    out += [f"- {hub_link(t)}" for t in theme_hubs]
    out += ["", "## Tables", ""]
    out += [f"- [[{b}|{b.removesuffix('.base')}]]" for b in bases]
    return "\n".join(out) + "\n"
