"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/main.ts
var main_exports = {};
__export(main_exports, {
  default: () => StatPearlsPlugin
});
module.exports = __toCommonJS(main_exports);
var import_obsidian2 = require("obsidian");

// src/home.ts
var import_obsidian = require("obsidian");

// src/titles.ts
var GREEK = { "\u03B1": "alpha", "\u03B2": "beta", "\u03B3": "gamma", "\u03B4": "delta", "\u03BA": "kappa", "\u03BC": "mu" };
function fold(s) {
  const plain = s.toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "");
  return [...plain].map((ch) => GREEK[ch] ?? ch).join("");
}
function bucket(title, q) {
  if (title === q) return 0;
  if (title.startsWith(q)) return 1;
  if (title.split(/[^a-z0-9]+/).some((w, i, ws) => ws.slice(i).join(" ").startsWith(q))) return 2;
  if (title.includes(q)) return 3;
  return -1;
}
function rankTitles(query, entries, limit = 15) {
  const q = fold(query).trim().replace(/\s+/g, " ");
  if (!q) return [];
  const best = /* @__PURE__ */ new Map();
  for (const e of entries) {
    const t = fold(e.title);
    const b = bucket(t, q);
    if (b < 0) continue;
    const key = [b, t.length, t];
    const old = best.get(e.path);
    if (!old || cmp(key, old.key) < 0) best.set(e.path, { e, key });
  }
  return [...best.values()].sort((a, b) => cmp(a.key, b.key)).slice(0, limit).map((x) => x.e);
}
function cmp(a, b) {
  return a[0] - b[0] || a[1] - b[1] || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0);
}

// src/content.ts
var STOPWORDS = new Set(
  "a an and are as at be been being but by can for from has have in into is it its may no not of on or such than that the their then there these this those to was were which will with would also should".split(" ")
);
function tokenize(text) {
  return fold(text).split(/[^a-z0-9]+/).filter((t) => t.length > 1 && !STOPWORDS.has(t));
}
function shardKey(term) {
  return term.slice(0, 3).padEnd(3, "_");
}
var K1 = 1.2;
var B = 0.75;
function makeSearcher(load) {
  let base = null;
  const shards = /* @__PURE__ */ new Map();
  const json = async (rel, empty) => {
    const text = await load(rel);
    return text == null ? empty : JSON.parse(text);
  };
  const shard = (key) => {
    if (!shards.has(key)) shards.set(key, json(`terms/k-${key}.json`, {}));
    return shards.get(key);
  };
  return async function search(query, opts = {}) {
    const terms = [...new Set(tokenize(query))];
    if (!terms.length) return [];
    base ?? (base = Promise.all([json("meta.json", { n: 0, avgdl: 1 }), json("docs.json", [])]).then(([meta2, docs2]) => ({ meta: meta2, docs: docs2 })));
    const { meta, docs } = await base;
    const postings = await Promise.all(terms.map(async (t) => (await shard(shardKey(t)))[t] ?? []));
    if (postings.some((p) => !p.length)) return [];
    const order = postings.map((p, k) => k).sort((a, b) => postings[a].length - postings[b].length);
    let scores = /* @__PURE__ */ new Map();
    for (const [step, k] of order.entries()) {
      const plist = postings[k];
      const idf = Math.log(1 + (meta.n - plist.length + 0.5) / (plist.length + 0.5));
      const next = /* @__PURE__ */ new Map();
      for (const [doc, tf] of plist) {
        if (step > 0 && !scores.has(doc)) continue;
        const dl = docs[doc][2];
        next.set(doc, (scores.get(doc) ?? 0) + idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / meta.avgdl)));
      }
      scores = next;
    }
    const byStem = /* @__PURE__ */ new Map();
    for (const [doc, score] of scores) {
      const [stem, section] = docs[doc];
      if (opts.section && section !== opts.section) continue;
      const h = byStem.get(stem);
      if (!h) byStem.set(stem, { stem, section, score, sections: 1 });
      else {
        h.sections += 1;
        if (score > h.score) Object.assign(h, { section, score });
      }
    }
    return [...byStem.values()].sort((a, b) => b.score - a.score || (a.stem < b.stem ? -1 : 1)).slice(0, opts.limit ?? 30);
  };
}
var escapeHtml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
var unescapeMd = (s) => s.replace(/\\(.)/g, "$1");
function snippet(noteText, section, terms) {
  const lines = noteText.split("\n");
  const start = lines.findIndex((l) => l.startsWith("## ") && unescapeMd(l.slice(3).trim()) === section);
  if (start < 0) return null;
  const body = [];
  for (const l of lines.slice(start + 1)) {
    if (l.startsWith("## ")) break;
    body.push(l);
  }
  const text = unescapeMd(
    body.join(" ").replace(/!?\[\[[^\]|]*\|([^\]]*)\]\]/g, "$1").replace(/!?\[\[([^\]]*)\]\]/g, "$1").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
  ).replace(/\s+/g, " ").trim();
  const sentences = text.split(/(?<=[.!?])\s+/).filter(Boolean);
  const want = new Set(terms);
  const hit = sentences.find((s) => tokenize(s).some((t) => want.has(t))) ?? sentences[0] ?? "";
  return hit.slice(0, 300).split(/([\p{L}\p{N}]+)/u).map((part, k) => k % 2 && tokenize(part).some((t) => want.has(t)) ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part)).join("");
}

// src/home.ts
var INDEX = "StatPearls/_meta/search/";
var ROOTS = ["StatPearls/Articles/", "StatPearls/Nursing/", "StatPearls/Hubs/"];
var CHIPS = [
  "Treatment / Management",
  "Evaluation",
  "Etiology",
  "Pathophysiology",
  "Differential Diagnosis",
  "Complications",
  "Prognosis",
  "Epidemiology",
  "History and Physical",
  "Indications",
  "Contraindications",
  "Mechanism of Action"
];
var PUBMED = "https://pubmed.ncbi.nlm.nih.gov/?term=";
var STATPEARLS = "https://www.ncbi.nlm.nih.gov/books/NBK430685/?term=";
var searcher = null;
var HomeView = class extends import_obsidian.MarkdownRenderChild {
  constructor(app, el, data) {
    super(el);
    this.app = app;
    this.data = data;
    this.mode = "titles";
    this.section = null;
    this.selected = 0;
    this.titleHits = [];
    this.gen = 0;
  }
  onload() {
    const root = this.containerEl.createDiv({ cls: "sp-home" });
    const row = root.createDiv({ cls: "sp-home-search" });
    this.input = row.createEl("input", { type: "search", placeholder: "Search StatPearls\u2026", cls: "sp-home-input" });
    const modes = row.createDiv({ cls: "sp-home-modes" });
    for (const [m, label] of [["titles", "Titles"], ["contents", "Contents"]]) {
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
  web(base) {
    const q = this.input.value.trim();
    window.open(base + encodeURIComponent(q));
  }
  /** A vault path, or a basename resolved under StatPearls (pipeline notes win over same-named Mine/ notes). */
  resolve(link) {
    if (link.includes("/")) {
      const f = this.app.vault.getAbstractFileByPath(link);
      return f instanceof import_obsidian.TFile ? f : null;
    }
    const named = this.app.vault.getFiles().filter((f) => (f.extension === "md" ? f.basename : f.name) === link);
    return named.find((f) => ROOTS.some((r) => f.path.startsWith(r))) ?? named.find((f) => f.path.startsWith("StatPearls/")) ?? null;
  }
  /** Opens only existing files: openLinkText on an unresolved name would create a new empty note. */
  open(target) {
    const cut = target.indexOf("#");
    const file = this.resolve(cut < 0 ? target : target.slice(0, cut));
    if (!file) return void new import_obsidian.Notice(`StatPearls: "${target}" not found; rebuild the vault?`);
    this.app.workspace.openLinkText(file.path + (cut < 0 ? "" : target.slice(cut)), "", false);
  }
  renderBrowse() {
    const tiles = this.browse.createDiv({ cls: "sp-home-tiles" });
    for (const c of this.data.categories) {
      const t = tiles.createDiv({ cls: "sp-home-tile" });
      t.createDiv({ text: c.name, cls: "sp-home-tile-name" });
      t.createDiv({ text: `${c.count} articles`, cls: "sp-home-tile-count" });
      t.onclick = () => this.open(c.hub);
    }
    const row = (label, items) => {
      const r = this.browse.createDiv({ cls: "sp-home-row" });
      r.createSpan({ text: label, cls: "sp-home-row-label" });
      for (const it of items) r.createEl("button", { text: it.text, cls: "sp-home-chip" }).onclick = () => this.open(it.target);
    };
    row("Themes", this.data.themes.map((t) => ({ text: t.name, target: t.hub })));
    row("Tables", this.data.tables.map((b) => ({ text: b.replace(/\.base$/, ""), target: b })));
  }
  titleEntries() {
    const out = [];
    for (const f of this.app.vault.getMarkdownFiles()) {
      if (!ROOTS.some((r) => f.path.startsWith(r))) continue;
      out.push({ title: f.basename, path: f.path });
      const aliases = this.app.metadataCache.getFileCache(f)?.frontmatter?.aliases;
      for (const a of Array.isArray(aliases) ? aliases : []) if (typeof a === "string") out.push({ title: a, path: f.path });
    }
    return out;
  }
  refresh(now) {
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
  showTitles(q) {
    this.titleHits = rankTitles(q, this.titleEntries());
    this.selected = 0;
    if (!this.titleHits.length) return void this.results.createDiv({ text: "No matching titles.", cls: "sp-home-empty" });
    const list = this.results.createDiv({ cls: "sp-home-list" });
    this.titleHits.forEach((h, k) => {
      const item = list.createDiv({ cls: "sp-home-hit" });
      item.toggleClass("is-selected", k === this.selected);
      item.createDiv({ text: h.title, cls: "sp-home-hit-title" });
      const base = h.path.split("/").pop().replace(/\.md$/, "");
      if (base !== h.title) item.createDiv({ text: base, cls: "sp-home-hit-sub" });
      item.onclick = () => this.open(h.path);
    });
  }
  async showContents(q) {
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
    const status = this.results.createDiv({ text: "Searching\u2026", cls: "sp-home-status" });
    const t0 = performance.now();
    searcher ?? (searcher = makeSearcher(async (rel) => {
      try {
        return await this.app.vault.adapter.read(INDEX + rel);
      } catch {
        return null;
      }
    }));
    const hits = await searcher(q, { section: this.section ?? void 0 });
    if (gen !== this.gen) return;
    status.setText(`${hits.length} articles \xB7 ${Math.round(performance.now() - t0)} ms`);
    const terms = tokenize(q);
    const list = this.results.createDiv({ cls: "sp-home-list" });
    for (const h of hits) {
      const item = list.createDiv({ cls: "sp-home-hit" });
      item.createDiv({ text: h.stem, cls: "sp-home-hit-title" });
      item.createDiv({ text: `${h.section}${h.sections > 1 ? ` \xB7 ${h.sections} sections` : ""}`, cls: "sp-home-hit-sub" });
      const snip = item.createDiv({ cls: "sp-home-snippet" });
      const file = this.resolve(h.stem);
      let target = h.stem;
      if (file) {
        const text = snippet(await this.app.vault.cachedRead(file), h.section, terms);
        if (gen !== this.gen) return;
        if (text != null) {
          snip.append((0, import_obsidian.sanitizeHTMLToDom)(text));
          target = `${h.stem}#${h.section}`;
        }
      }
      item.onclick = () => this.open(target);
    }
  }
  key(e) {
    if (e.key === "Enter") {
      if (this.mode === "contents") return this.refresh(true);
      const h = this.titleHits[this.selected];
      if (h) this.open(h.path);
      return;
    }
    if (this.mode !== "titles" || !this.titleHits.length || e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    this.selected = (this.selected + (e.key === "ArrowDown" ? 1 : this.titleHits.length - 1)) % this.titleHits.length;
    this.results.querySelectorAll(".sp-home-hit").forEach((x, k) => x.toggleClass("is-selected", k === this.selected));
  }
};

// src/main.ts
var HOME = "StatPearls/Hubs/Home (hub).md";
var StatPearlsPlugin = class extends import_obsidian2.Plugin {
  constructor() {
    super(...arguments);
    this.settings = { openHomeOnStart: true };
  }
  async onload() {
    this.settings = { ...this.settings, ...await this.loadData() };
    this.registerMarkdownCodeBlockProcessor("statpearls-home", (source, el, ctx) => {
      let data;
      try {
        data = JSON.parse(source);
      } catch {
        el.createDiv({ text: "StatPearls Home: the data block is not valid JSON; rebuild the vault." });
        return;
      }
      ctx.addChild(new HomeView(this.app, el, data));
    });
    this.addCommand({ id: "open-home", name: "Open home", callback: () => this.openHome() });
    this.addRibbonIcon("search", "StatPearls home", () => this.openHome());
    this.addSettingTab(new StatPearlsSettings(this.app, this));
    this.app.workspace.onLayoutReady(() => {
      if (this.settings.openHomeOnStart) this.openHome();
    });
  }
  async openHome() {
    const file = this.app.vault.getAbstractFileByPath(HOME);
    if (file instanceof import_obsidian2.TFile) await this.app.workspace.getLeaf(false).openFile(file, { state: { mode: "preview" } });
  }
};
var StatPearlsSettings = class extends import_obsidian2.PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }
  display() {
    this.containerEl.empty();
    new import_obsidian2.Setting(this.containerEl).setName("Open Home on start").setDesc("Open StatPearls Home in reading view when the vault opens.").addToggle(
      (t) => t.setValue(this.plugin.settings.openHomeOnStart).onChange(async (v) => {
        this.plugin.settings.openHomeOnStart = v;
        await this.plugin.saveData(this.plugin.settings);
      })
    );
  }
};
