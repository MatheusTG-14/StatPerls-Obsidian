# StatPearls Vault Builder

Downloads the StatPearls archive from the U.S. National Library of Medicine and builds a **private, local [Obsidian](https://obsidian.md) vault** from it: one note per article, with links between related articles, categories, tags, figures and a search-first Home page.

If you are not technical you may simply use the bundled exe or look for it in the releases. It will open a command line with the instructions to download. The download and vault buill is automatic, so don't worry! You only need to install obsidian later and then activate the bundled plugin for more functionality. 

This repository contains **only the program and its own metadata** (categories, tags, vocabularies, Obsidian settings, a small plugin). It contains **no StatPearls text, figures or article titles**. You download the content yourself though the app, from NLM, and it stays on your computer. Read [NOTICE.md](NOTICE.md) before using it.

> Not affiliated with, or endorsed by, StatPearls Publishing or the National Library of Medicine. The vault is
> an educational snapshot, not for point-of-care decisions: every note shows its last-update date.

## What you need

- Windows 10/11 for the `.exe`; or Python 3.12+ on any system for running from source.
- [Obsidian](https://obsidian.md) and an internet connection.
- About 5 GB of free disk. Because the PubMed map is fetched from NCBI, a first install takes roughly an hour (download of about 2 GB, then the build).
- Obsidian **closed** on the vault while installing or updating.

## Run it

### From source

```
git clone <this repository>
cd statperls_vaultbuilder
python entry.py                              # opens a menu (Install, Update, Status, Export)
python entry.py install "D:\StatPearls"      # or directly
```

The first run creates a private Python environment inside the install folder and installs the pinned
libraries from [src/installer/requirements.txt](src/installer/requirements.txt) (`lxml`, `PyYAML`, `jsonschema`);
nothing is installed system-wide.

### Windows .exe

Python and the libraries are built in. Build it yourself (the `.exe` is not distributed in this repository):

```
build.cmd
```

It sets up the pinned build tools in `.build-venv` and writes `dist\statpearls-vault.exe`. The program is not
code-signed, so Windows SmartScreen may say "Windows protected your PC": choose *More info*, then *Run anyway*.
Use it exactly like `python entry.py` (double-click for the menu).

### Portable `.pyz`

```
python -I sp.py bundle statpearls-vault.pyz
python statpearls-vault.pyz install "D:\StatPearls"
```

## Commands

| Command                             | What it does                                                                                                                                                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `install FOLDER`                    | Downloads the archive (or uses `--archive TARBALL`) and builds everything in `FOLDER`; the vault is `FOLDER\vault`.                                                                                          |
| `update [--force]`                  | Checks NLM for a newer archive and rebuilds in place. Never touches `Mine/`, your bookmarks or your Obsidian settings. New or changed articles are placed automatically and tagged `status/auto-classified`. |
| `status`                            | Shows what is installed and whether NLM has a newer archive.                                                                                                                                                 |
| `export OUT.pyz`                    | Writes a new `.pyz` carrying the corrections you made since install, for another computer. `export OUT.zip` writes only the corrections; put it next to the program as `statpearls-vault-corrections.zip`.   |
| `--yes`, `--plain`, `--folder PATH` | Accept the plan without asking; plain-text output (no dashboard); pick the install folder.                                                                                                                   |

Ctrl+C stops safely; run the same command again to resume. After installing, copy your own `Mine/` folder and `.obsidian/bookmarks.json` from a backup into `FOLDER\vault` if you have them, open the vault in Obsidian, turn off Restricted mode and enable the StatPearls plugin.

Your own notes go in `vault/Mine/`. The builder only ever writes inside `vault/StatPearls/`, `data/` and `backups/` of the install folder.

## What the install does

Eight steps, shown on a dashboard with counters and time left: checking the computer, preparing the Python libraries, setting up the folder, getting the archive from NLM, unpacking articles and figures, reading the articles (including the PubMed identifier map and reference MeSH data from NCBI), building the notes (the longest step), and finishing. Article text is rendered verbatim; the builder adds links, tags, aliases and metadata, and a source/attribution line on every note. See [docs/design.md](docs/design.md).

## What is in this repository

| Path                                                           | Contents                                                                                                                          |
| -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `src/`                                                         | The program: archive download, extraction, classification, rendering, validation, installer UI.                                   |
| `schema/`                                                      | Vocabularies, and the category/tag/drug-class assignments per article ID (`schema/overrides/`). IDs and slugs only, no titles.    |
| `state/`                                                       | NLM reference MeSH cache and per-article content hashes (for update detection).                                                   |
| `obsidian-config/`, `plugin/`                                  | Obsidian settings and CSS, and the built StatPearls Home plugin.                                                                  |
| `obsidian-plugin/`                                             | TypeScript source of that plugin.                                                                                                 |
| `src/census/`                                                  | Optional analysis scripts used to survey the archive format before the extractor was written. **Not needed to install or build.** |
| `tests/`                                                       | Test suite; uses one fully synthetic article.                                                                                     |
| `entry.py`, `sp.py`                                            | Installer entry point; developer command line for individual pipeline stages.                                                     |
| `build.cmd`, `statpearls-vault.spec`, `build-requirements.txt` | Windows `.exe` build.                                                                                                             |
| `_vendor/rich/`                                                | Vendored [Rich](https://github.com/Textualize/rich) (MIT) for the terminal dashboard.                                             |

## Development

```
pip install lxml PyYAML jsonschema pytest
python -m pytest -q                      # synthetic data only, about 30 s

cd obsidian-plugin
npm install
npm test && npm run build                # writes obsidian-plugin/main.js
copy main.js ..\plugin\main.js           # the copy the installer ships
```

Run individual stages from the repository root with `python -I sp.py <stage>` (`extract`, `media`, `build`, `validate`, `linkreport`, `mesh`, `classify`, and others; run it without arguments for the list). The classification refresh uses a *prepare / collect* flow: the program writes minimized batches (title, headings and introduction only), you have a language model classify them, and `collect` validates the answers against the frozen vocabularies before merging them into `schema/overrides/`. No API keys are used or stored by this code.

### Archive census scripts (optional)

`src/census/` holds three read-only scripts (`tags.py`, `articles.py`, `extra.py`) that inventory an extracted archive: file types, XML element frequencies, per-article facts, figure files. They were used once to design the extractor and are only useful to re-check the format when NLM changes it. **Nothing imports them and the installer, the build and the tests do not need them**; the `.pyz` and `.exe` leave them out. Usage is in each file's docstring, for example `python -I -m src.census.tags  extracted_root> <out_json>`.

## License

Code: [MIT](LICENSE). StatPearls content is **not** part of this repository and is
licensed by its owners under CC BY-NC-ND 4.0; see [NOTICE.md](NOTICE.md).
