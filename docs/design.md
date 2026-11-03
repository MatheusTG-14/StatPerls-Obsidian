# Design notes

Source comments mention `DEC-nn` (design decisions), `rule n` and `PLAN section n`. The private notes behind them
are not published; this page summarizes what matters.

## Layers

L0 raw archive → L1 canonical JSON per article → L2 enrichment sidecars (categories, tags) → L3 the vault
(`vault/StatPearls/`) → L4 search index for the Home plugin (`vault/StatPearls/_meta/search/`).

## Ground rules the code enforces

1. **Source.** Only the NLM LitArch file service and NCBI E-utilities. No scraping.
2. **No distribution.** Archive, intermediate data and vault stay on the user's computer.
3. **Verbatim body text.** Enrichment adds links, tags, aliases and metadata; it never rewrites, summarizes or
   reorders source prose.
4. **Attribution on every note:** title, authors, NBK ID, source URL, license, last-update date.
5. **Deterministic rendering.** The same inputs give a byte-identical vault. No model calls in the renderer.
   Text files are written with `\n` line endings for this reason.
6. **Closed world.** Classification chooses among candidates produced by code, from frozen vocabularies
   (`schema/vocab/`). Answers are schema-validated and carry the model name and a fingerprint of the exact input;
   an answer whose input changed is ignored as stale.
7. **Generated and personal content are separate.** `vault/StatPearls/` is disposable and rebuilt;
   `vault/Mine/` is never touched. Names of `Mine/` notes must not collide with generated ones (the validator warns).
8. **Build with Obsidian closed.**
9. **Educational snapshot.** Every note shows its last-update date.
10. **Data minimization.** Classification input is the title, headings and introduction only; link
    disambiguation sees a short context window; nothing sends a full article.
11. **Stable identity.** The archive article ID is the permanent key. A note's file name is assigned at its first
    build, stored in `data/registry.json`, and never changed, so links from `Mine/` do not dangle when titles
    change. Back that file up.

## Classification

Article categories come from reference MeSH headings (NLM data, cached in `state/`) voted over the tree, plus
frozen rules (`src/enrich/system.py`), then per-category subcategories, facet tags and drug classes from the
assignments in `schema/overrides/`. Precedence: your edits (`system.yaml`, harvested from Obsidian) win over
agent assignments, which win over the heuristics. Moving a note between category folders in Obsidian is picked up
by `harvest` and kept across rebuilds.

## Installer

`src/installer/` is a resumable eight-step state machine with a Rich dashboard (plain lines when output is not a
terminal). It keeps a private virtual environment in the install folder, records progress so Ctrl+C is safe,
remembers install folders (paths only) in `%APPDATA%\StatPearls Vault\installs.json`, and refuses to run inside
cloud-synced folders (OneDrive, Dropbox, Google Drive). Bundled data (`state/`, `schema/overrides/`, Obsidian
settings, plugin) is unpacked into the install folder once and never overwrites what is already there.
