// Content search for Home (spec 3.4): BM25 over the sharded section index the build writes to
// StatPearls/_meta/search/ (src/render/search_index.py). Pure apart from the injected loader.

import { fold } from "./titles";

export const STOPWORDS = new Set(
  ("a an and are as at be been being but by can for from has have in into is it its may no not of on or such " +
    "than that the their then there these this those to was were which will with would also should").split(" "),
);

/** Same rules as search_index.tokenize: fold, split on non-alphanumerics, drop 1-char tokens and stopwords. */
export function tokenize(text: string): string[] {
  return fold(text).split(/[^a-z0-9]+/).filter((t) => t.length > 1 && !STOPWORDS.has(t));
}

export function shardKey(term: string): string {
  return term.slice(0, 3).padEnd(3, "_");
}

/** Reads a file relative to the index folder; null when it does not exist. */
export type Loader = (relPath: string) => Promise<string | null>;

export interface Hit {
  stem: string;
  section: string;
  score: number;
  sections: number;
}

type Meta = { n: number; avgdl: number };
type Doc = [string, string, number];
type Shard = Record<string, [number, number][]>;

const K1 = 1.2;
const B = 0.75;

/** Returns a search function that caches meta, docs and shards for the lifetime of the searcher. */
export function makeSearcher(load: Loader) {
  let base: Promise<{ meta: Meta; docs: Doc[] }> | null = null;
  const shards = new Map<string, Promise<Shard>>();
  const json = async <T>(rel: string, empty: T): Promise<T> => {
    const text = await load(rel);
    return text == null ? empty : (JSON.parse(text) as T);
  };
  const shard = (key: string) => {
    if (!shards.has(key)) shards.set(key, json<Shard>(`terms/k-${key}.json`, {}));
    return shards.get(key)!;
  };

  return async function search(query: string, opts: { section?: string; limit?: number } = {}): Promise<Hit[]> {
    const terms = [...new Set(tokenize(query))];
    if (!terms.length) return [];
    base ??= Promise.all([json<Meta>("meta.json", { n: 0, avgdl: 1 }), json<Doc[]>("docs.json", [])]).then(([meta, docs]) => ({ meta, docs }));
    const { meta, docs } = await base;
    const postings = await Promise.all(terms.map(async (t) => (await shard(shardKey(t)))[t] ?? []));
    if (postings.some((p) => !p.length)) return [];
    // AND: start from the rarest term's sections, keep only sections every term occurs in.
    const order = postings.map((p, k) => k).sort((a, b) => postings[a].length - postings[b].length);
    let scores = new Map<number, number>();
    for (const [step, k] of order.entries()) {
      const plist = postings[k];
      const idf = Math.log(1 + (meta.n - plist.length + 0.5) / (plist.length + 0.5));
      const next = new Map<number, number>();
      for (const [doc, tf] of plist) {
        if (step > 0 && !scores.has(doc)) continue;
        const dl = docs[doc][2];
        next.set(doc, (scores.get(doc) ?? 0) + (idf * tf * (K1 + 1)) / (tf + K1 * (1 - B + (B * dl) / meta.avgdl)));
      }
      scores = next;
    }
    const byStem = new Map<string, Hit>();
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
    return [...byStem.values()]
      .sort((a, b) => b.score - a.score || (a.stem < b.stem ? -1 : 1))
      .slice(0, opts.limit ?? 30);
  };
}

const escapeHtml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const unescapeMd = (s: string) => s.replace(/\\(.)/g, "$1");

/** First sentence of `## section` containing a term, links reduced to their text, HTML-escaped, hits in <mark>. */
export function snippet(noteText: string, section: string, terms: string[]): string | null {
  const lines = noteText.split("\n");
  const start = lines.findIndex((l) => l.startsWith("## ") && unescapeMd(l.slice(3).trim()) === section);
  if (start < 0) return null;
  const body: string[] = [];
  for (const l of lines.slice(start + 1)) {
    if (l.startsWith("## ")) break;
    body.push(l);
  }
  const text = unescapeMd(
    body
      .join(" ")
      .replace(/!?\[\[[^\]|]*\|([^\]]*)\]\]/g, "$1")
      .replace(/!?\[\[([^\]]*)\]\]/g, "$1")
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1"),
  )
    .replace(/\s+/g, " ")
    .trim();
  const sentences = text.split(/(?<=[.!?])\s+/).filter(Boolean);
  const want = new Set(terms);
  const hit = sentences.find((s) => tokenize(s).some((t) => want.has(t))) ?? sentences[0] ?? "";
  // Split on words first so escaping never creates text the highlighter could match (e.g. "amp").
  return hit
    .slice(0, 300)
    .split(/([\p{L}\p{N}]+)/u)
    .map((part, k) => (k % 2 && tokenize(part).some((t) => want.has(t)) ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part)))
    .join("");
}
