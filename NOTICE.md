# Notice: content, licensing and acceptable use

## This repository holds no StatPearls content

No article text, figure, article title or archive file is stored here. The program downloads the archive
itself, from NLM, onto your computer. The only per-article data shipped are article IDs (`article-<n>`) with
category, tag and drug-class labels produced by this project, content hashes, and NLM reference MeSH data.

## StatPearls license

StatPearls is published on the NCBI Bookshelf and licensed
[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/). Figures may carry their own terms; each
generated figure note records its credit verbatim.

Practical consequences of that license for anyone who runs this program:

- **Do not share the generated vault, the downloaded archive, or any part of the converted text**: not in a
  public or private repository, not on a shared drive, not in a cloud-synced folder, not as a release asset.
  The license allows making adapted material for non-commercial use but not sharing it.
- Non-commercial use only. Attribution is already written into every note; do not remove it.
- This is an interpretation, not legal advice. When in doubt, do not share.

## Download policy

The program downloads only from the NLM Literature Archive file service (`ftp.ncbi.nlm.nih.gov/pub/litarch/`)
and the NCBI E-utilities (`eutils.ncbi.nlm.nih.gov`, at most 2 requests per second, tool name
`statpearls-vault`). NCBI documents the file service as the permitted route for bulk retrieval of Bookshelf
content. Do not point this program at the Bookshelf website or statpearls.com, and do not remove the rate limit.
See <https://www.ncbi.nlm.nih.gov/books/about/ftp/>.

## Medical disclaimer

The vault is an educational snapshot. Each note shows its last-update date. It is not a source for
point-of-care decisions, and automatic categories, tags and links can be wrong.

## Third-party components

The code in this repository is MIT-licensed (see LICENSE); that license does not cover StatPearls content.

- [Rich](https://github.com/Textualize/rich), MIT license, vendored in `_vendor/rich/` (license file included).
- `lxml`, `PyYAML`, `jsonschema` are installed from PyPI at run time (pinned in `src/installer/requirements.txt`)
  and compiled into the `.exe` when you build it.
- The Obsidian plugin is built with esbuild/TypeScript against the Obsidian API (dev dependencies only).
- MeSH data in `state/mesh_cache.json.gz` comes from NLM (public data).

"StatPearls", "PubMed", "NCBI" and "Obsidian" are trademarks of their respective owners.
