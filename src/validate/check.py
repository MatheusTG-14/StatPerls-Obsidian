"""Vault validators (see docs/design.md). Exit code 0 only if every hard check passes."""
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

from src.common import no_ws, read_json
from src.extract.nxml import block_text
from src.render.markdown import unesc
from src.render.names import fold
from src.enrich.system import CATEGORIES, SUBCATEGORIES
from src.enrich.tagging import DRUG_CLASSES, FACETS
from src.render.tags import ARTICLE_TYPES, MODALITY_VALUES

WIKILINK = re.compile(r"(?<!\\)!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
INLINE_CODE = re.compile(r"(?<!\\)`([^`]*)`")
MDLINK = re.compile(r"(?<!\\)\[((?:\\.|[^\]\\])*)\]\((?:<[^>]*>|[^)\s]*)\)")
REQUIRED = ["title", "article_id", "nbk", "pmid", "authors", "last_update", "source", "license", "tags"]
TAG_OK = [
    lambda t: t.startswith("type/") and t[5:] in ARTICLE_TYPES + ["figure"],
    lambda t: re.fullmatch(r"region/[a-z0-9-]+", t),
    lambda t: t in ("status/nursing", "status/archived", "status/auto-classified"),
    lambda t: t.startswith("image/") and t[6:] in MODALITY_VALUES,
    lambda t: t.startswith("article-type/") and t[13:] in ARTICLE_TYPES,
    lambda t: t.startswith("system/") and t[7:] in {c["slug"] for c in CATEGORIES},
    lambda t: t.startswith("system/") and t[7:] in {f"{c}/{s['slug']}" for c, subs in SUBCATEGORIES.items() for s in subs},
    lambda t: t == "type/hub",
    lambda t: t.startswith("drug-class/") and t[11:] in DRUG_CLASSES,
    lambda t: "/" in t and t.split("/", 1)[0] in FACETS and t.split("/", 1)[1] in FACETS[t.split("/", 1)[0]],
]


def split_fm(text):
    if not text.startswith("---\n"):
        return None, text
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]), text[end + 5:]


def strip_markup(body):
    lines, code, spans = [], [], []
    in_code = False
    for line in body.splitlines():
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:  # code blocks are verbatim, never escaped
            code.append(line)
            continue
        if re.fullmatch(r"\|(---\|)+", line):
            continue
        # inline code is verbatim: park it behind a placeholder, restore after unescaping
        line = INLINE_CODE.sub(lambda m: (spans.append(m.group(1)), f"\x01{len(spans) - 1}\x01")[1], line)
        line = WIKILINK.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), line)
        line = MDLINK.sub(lambda m: m.group(1), line)
        line = re.sub(r"</?(sup|sub|u)>|<br>", "", line)
        if re.match(r"#{2,3} ", line):
            line = re.sub(r"^#{2,3} ", "", line)  # heading text may itself start with "1."
        else:
            line = re.sub(r"^\s*(?:(?:-|\d+\.)(?: |$))+", "", line)  # "- - x": item whose first child is a list
        line = re.sub(r"(?<!\\)[*`]", "", line)
        line = re.sub(r"(?<!\\)\|", "", line)
        lines.append(line)
    text = re.sub("\x01(\\d+)\x01", lambda m: spans[int(m.group(1))], unesc("".join(lines)))
    return no_ws(text) + "\0" + no_ws("".join(code))


def mine_path_links(text):
    """Wikilink targets written as a path into StatPearls/: they break when notes move folders."""
    return [m.group(1).strip() for m in WIKILINK.finditer(text) if m.group(1).strip().startswith("StatPearls/")]


def hub_collisions(hub_stems, article_keys):
    """Hub stems whose folded form equals an article stem or alias (folded keys)."""
    return {h for h in hub_stems if fold(h) in article_keys}


def check(vault):
    sys.stdout.reconfigure(encoding="utf-8")
    root = Path(vault) / "StatPearls"
    errors, warns = Counter(), Counter()
    examples = {}

    def err(kind, where):
        errors[kind] += 1
        examples.setdefault(kind, where)

    notes = {p.stem: p for p in root.rglob("*.md")}
    targets = {fold(s) for s in notes} | {fold(p.name) for p in root.rglob("*.base")}
    if (root / "_attachments").exists():
        targets |= {fold(p.name) for p in (root / "_attachments").iterdir()}
    aliases = set()
    l1 = Path("data/l1")
    for stem, p in sorted(notes.items()):
        text = p.read_text(encoding="utf-8")
        if "\r" in text:
            err("crlf", stem)
        fm, body = split_fm(text)
        folder = p.relative_to(root).parts[0]
        if folder in ("Articles", "Nursing", "Archived"):
            if fm is None:
                err("no_frontmatter", stem)
                continue
            for k in REQUIRED:
                if not fm.get(k):
                    err(f"missing_{k}", stem)
            aliases |= {fold(a) for a in fm.get("aliases") or []}
            for t in fm.get("tags") or []:
                if not any(ok(t) for ok in TAG_OK):
                    err("tag_not_in_vocab", f"{stem}: {t}")
            if not any(t.startswith("type/") for t in fm.get("tags") or []):
                err("no_type_tag", stem)
            # every citation link lands on a reference block ID in the same note
            blocks = set(re.findall(r" \^(ref-\d+)$", body, re.M))
            for m in re.finditer(r"\]\(#\^(ref-\d+)\)", body):
                if m.group(1) not in blocks:
                    err("dangling_citation", f"{stem} -> {m.group(1)}")
            # fidelity: every L1 block's text appears, in order-independent substring form
            rec = read_json(l1 / f"{fm['article_id']}.json")
            flat = strip_markup(body)
            for s in rec["sections"]:
                for b in s["blocks"]:
                    t = no_ws(block_text(b))
                    if t and t not in flat:
                        err("fidelity", f"{stem}: {t[:60]}")
        elif folder == "Figures":
            for t in (fm or {}).get("tags") or []:
                if not any(ok(t) for ok in TAG_OK):
                    err("tag_not_in_vocab", f"{stem}: {t}")
        for m in WIKILINK.finditer(text):
            target = m.group(1).strip()
            if fold(target) not in targets:
                err("dangling_link", f"{stem} -> {target}")
            if target == stem:
                err("self_link", stem)
    article_keys = {fold(s) for s, p in notes.items() if p.relative_to(root).parts[0] in ("Articles", "Nursing", "Archived")} | aliases
    hub_names = set()
    for s, p in notes.items():
        if p.relative_to(root).parts[0] == "Hubs":
            hub_names.add(s)
            hub_names |= set((split_fm(p.read_text(encoding="utf-8"))[0] or {}).get("aliases") or [])
    for h in sorted(hub_collisions(hub_names, article_keys)):
        err("hub_collision", h)
    mine = Path(vault) / "Mine"
    if mine.exists():
        for p in mine.rglob("*.md"):
            for target in mine_path_links(p.read_text(encoding="utf-8")):
                warns["mine_path_link"] += 1
                examples.setdefault("mine_path_link", f"{p.stem} -> {target}")
            if fold(p.stem) in {fold(s) for s in notes} | aliases:
                warns["mine_name_collision"] += 1
                examples.setdefault("mine_name_collision", p.stem)
    try:
        remotes = subprocess.run(["git", "remote"], capture_output=True, text=True).stdout.strip()
    except OSError:  # no git on this computer (an installed vault): nothing can have a remote
        remotes = ""
    if remotes:
        err("git_remote_present", remotes)
    print(f"notes checked: {len(notes)}")
    print("errors:", dict(errors) or "none")
    print("warnings:", dict(warns) or "none")
    for k, v in examples.items():
        print(f"  e.g. {k}: {v}")
    return 1 if errors else 0
