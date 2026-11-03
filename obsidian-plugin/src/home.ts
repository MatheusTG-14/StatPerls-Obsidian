// Renders the `statpearls-home` block written atop Home (hub).md (spec 3.2). Data comes from the block;
// ranking and search logic live in titles.ts and content.ts.
import { App, MarkdownRenderChild, Notice, TFile, sanitizeHTMLToDom } from "obsidian";
import { makeSearcher, snippet, tokenize } from "./content";
import { rankTitles, TitleEntry } from "./titles";

interface HomeData {
  categories: { name: string; hub: string; count: number }[];
  themes: { name: string; hub: string }[];
  tables: string[];
}

const INDEX = "StatPearls/_meta/search/";
const ROOTS = ["StatPearls/Articles/", "StatPearls/Nursing/", "StatPearls/Hubs/"];
const CHIPS = ["Treatment / Management", "Evaluation", "Etiology", "Pathophysiology", "Differential Diagnosis", "Complications",
  "Prognosis", "Epidemiology", "History and Physical", "Indications", "Contraindications", "Mechanism of Action"];
const PUBMED = "https://pubmed.ncbi.nlm.nih.gov/?term=";
const STATPEARLS = "https://www.ncbi.nlm.nih.gov/books/NBK430685/?term=";

let searcher: ReturnType<typeof makeSearcher> | null = null; // one index cache per Obsidian session

export class HomeView extends MarkdownRenderChild {
  private mode: "titles" | "contents" = "titles";
  private section: string | null = null;
  private selected = 0;
  private titleHits: TitleEntry[] = [];
  private timer: number | undefined;
  private gen = 0; // bumped on every refresh; an older contents search stops at its next await
  private input!: HTMLInputElement;
  private results!: HTMLElement;
  private browse!: HTMLElement;

  constructor(private app: App, el: HTMLElement, private data: HomeData) {
    super(el);
  }

  onload() {
    const root = this.containerEl.createDiv({ cls: "sp-home" });
    const row = root.createDiv({ cls: "sp-home-search" });
    this.input = row.createEl("input", { type: "search", placeholder: "Search StatPearls…", cls: "sp-home-input" });
    const modes = row.createDiv({ cls: "sp-home-modes" });
    for (const [m, label] of [["titles", "Titles"], ["contents", "Contents"]] as const) {
      const b = modes.createEl("button", { text: label, cls: "sp-home-mode" });
      b.toggleClass("is-active", m === this.mode);
      b.onclick = () => {
        this.mode = m;
        modes.querySelectorAll("button").forEach((x) => x.toggleClass("is-active", x === b));
        this.refresh(true);
      };
    }
    const web = row.createDiv({ cls: "sp-home-web" });
    web.createEl("button", { text: "Search PubMed" }).onclick = () => this.web(PUBMED);
    web.createEl("button", { text: "Search StatPearls" }).onclick = () => this.web(STATPEARLS);
    this.results = root.createDiv({ cls: "sp-home-results" });
    this.browse = root.createDiv({ cls: "sp-home-browse" });
    this.renderBrowse();
    this.registerDomEvent(this.input, "input", () => this.refresh(false));
    this.registerDomEvent(this.input, "keydown", (e) => this.key(e));
    window.setTimeout(() => this.input.focus(), 50);
  }

  onunload() {
    window.clearTimeout(this.timer);
  }

  private web(base: string) {
    const q = this.input.value.trim();
    window.open(base + encodeURIComponent(q)); // the browser makes the request; the plugin itself never does
  }

  /** A vault path, or a basename resolved under StatPearls (pipeline notes win over same-named Mine/ notes). */
  private resolve(link: string): TFile | null {
    if (link.includes("/")) {
      const f = this.app.vault.getAbstractFileByPath(link);
      return f instanceof TFile ? f : null;
    }
    const named = this.app.vault.getFiles().filter((f) => (f.extension === "md" ? f.basename : f.name) === link);
    return named.find((f) => ROOTS.some((r) => f.path.startsWith(r))) ?? named.find((f) => f.path.startsWith("StatPearls/")) ?? null;
  }

  /** Opens only existing files: openLinkText on an unresolved name would create a new empty note. */
  private open(target: string) {
    const cut = target.indexOf("#");
    const file = this.resolve(cut < 0 ? target : target.slice(0, cut));
    if (!file) return void new Notice(`StatPearls: "${target}" not found; rebuild the vault?`);
    this.app.workspace.openLinkText(file.path + (cut < 0 ? "" : target.slice(cut)), "", false);
  }

  private renderBrowse() {
    const tiles = this.browse.createDiv({ cls: "sp-home-tiles" });
    for (const c of this.data.categories) {
      const t = tiles.createDiv({ cls: "sp-home-tile" });
      t.createDiv({ text: c.name, cls: "sp-home-tile-name" });
      t.createDiv({ text: `${c.count} articles`, cls: "sp-home-tile-count" });
      t.onclick = () => this.open(c.hub);
    }
    const row = (label: string, items: { text: string; target: string }[]) => {
      const r = this.browse.createDiv({ cls: "sp-home-row" });
      r.createSpan({ text: label, cls: "sp-home-row-label" });
      for (const it of items) r.createEl("button", { text: it.text, cls: "sp-home-chip" }).onclick = () => this.open(it.target);
    };
    row("Themes", this.data.themes.map((t) => ({ text: t.name, target: t.hub })));
    row("Tables", this.data.tables.map((b) => ({ text: b.replace(/\.base$/, ""), target: b })));
  }

  private titleEntries(): TitleEntry[] {
    const out: TitleEntry[] = [];
    for (const f of this.app.vault.getMarkdownFiles()) {
      if (!ROOTS.some((r) => f.path.startsWith(r))) continue;
      out.push({ title: f.basename, path: f.path });
      const aliases = this.app.metadataCache.getFileCache(f)?.frontmatter?.aliases;
      for (const a of Array.isArray(aliases) ? aliases : []) if (typeof a === "string") out.push({ title: a, path: f.path });
    }
    return out;
  }

  private refresh(now: boolean) {
    window.clearTimeout(this.timer);
    this.gen += 1;
    const q = this.input.value;
    const active = q.trim().length > 0;
    this.browse.toggle(!active);
    this.results.empty();
    if (!active) return;
    if (this.mode === "titles") return this.showTitles(q);
    this.timer = window.setTimeout(() => this.showContents(q), now ? 0 : 250);
  }

  private showTitles(q: string) {
    this.titleHits = rankTitles(q, this.titleEntries());
    this.selected = 0;
    if (!this.titleHits.length) return void this.results.createDiv({ text: "No matching titles.", cls: "sp-home-empty" });
    const list = this.results.createDiv({ cls: "sp-home-list" });
    this.titleHits.forEach((h, k) => {
      const item = list.createDiv({ cls: "sp-home-hit" });
      item.toggleClass("is-selected", k === this.selected);
      item.createDiv({ text: h.title, cls: "sp-home-hit-title" });
      const base = h.path.split("/").pop()!.replace(/\.md$/, "");
      if (base !== h.title) item.createDiv({ text: base, cls: "sp-home-hit-sub" });
      item.onclick = () => this.open(h.path);
    });
  }

  private async showContents(q: string) {
    const gen = this.gen;
    const chips = this.results.createDiv({ cls: "sp-home-row" });
    for (const s of [null, ...CHIPS]) {
      const b = chips.createEl("button", { text: s ?? "All sections", cls: "sp-home-chip" });
      b.toggleClass("is-active", s === this.section);
      b.onclick = () => {
        this.section = s;
        this.refresh(true);
      };
    }
    const status = this.results.createDiv({ text: "Searching…", cls: "sp-home-status" });
    const t0 = performance.now();
    searcher ??= makeSearcher(async (rel) => {
      try {
        return await this.app.vault.adapter.read(INDEX + rel);
      } catch {
        return null;
      }
    });
    const hits = await searcher(q, { section: this.section ?? undefined });
    if (gen !== this.gen) return; // a newer refresh owns the results area
    status.setText(`${hits.length} articles · ${Math.round(performance.now() - t0)} ms`);
    const terms = tokenize(q);
    const list = this.results.createDiv({ cls: "sp-home-list" });
    for (const h of hits) {
      const item = list.createDiv({ cls: "sp-home-hit" });
      item.createDiv({ text: h.stem, cls: "sp-home-hit-title" });
      item.createDiv({ text: `${h.section}${h.sections > 1 ? ` · ${h.sections} sections` : ""}`, cls: "sp-home-hit-sub" });
      const snip = item.createDiv({ cls: "sp-home-snippet" });
      const file = this.resolve(h.stem);
      let target = h.stem;
      if (file) {
        const text = snippet(await this.app.vault.cachedRead(file), h.section, terms);
        if (gen !== this.gen) return;
        if (text != null) {
          snip.append(sanitizeHTMLToDom(text));
          target = `${h.stem}#${h.section}`;
        }
      }
      item.onclick = () => this.open(target);
    }
  }

  private key(e: KeyboardEvent) {
    if (e.key === "Enter") {
      if (this.mode === "contents") return this.refresh(true);
      const h = this.titleHits[this.selected];
      if (h) this.open(h.path);
      return;
    }
    if (this.mode !== "titles" || !this.titleHits.length || (e.key !== "ArrowDown" && e.key !== "ArrowUp")) return;
    e.preventDefault();
    this.selected = (this.selected + (e.key === "ArrowDown" ? 1 : this.titleHits.length - 1)) % this.titleHits.length;
    this.results.querySelectorAll(".sp-home-hit").forEach((x, k) => x.toggleClass("is-selected", k === this.selected));
  }
}
