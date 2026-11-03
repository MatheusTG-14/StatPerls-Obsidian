// Title search for Home: rank note titles and aliases (spec 3.3). Pure; no Obsidian API.

export interface TitleEntry {
  title: string;
  path: string;
}

const GREEK: Record<string, string> = { "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "κ": "kappa", "μ": "mu" };

/** Lowercase, Greek letters to names, accents stripped (same folding as src/render/search_index.py). */
export function fold(s: string): string {
  // Greek map after NFKD so the micro sign (U+00B5) becomes U+03BC and maps to "mu" too.
  const plain = s.toLowerCase().normalize("NFKD").replace(/\p{M}/gu, "");
  return [...plain].map((ch) => GREEK[ch] ?? ch).join("");
}

function bucket(title: string, q: string): number {
  if (title === q) return 0;
  if (title.startsWith(q)) return 1;
  if (title.split(/[^a-z0-9]+/).some((w, i, ws) => ws.slice(i).join(" ").startsWith(q))) return 2;
  if (title.includes(q)) return 3;
  return -1;
}

/** exact > prefix > word-prefix > substring, then shorter title, then alphabetical; one hit per path. */
export function rankTitles(query: string, entries: TitleEntry[], limit = 15): TitleEntry[] {
  const q = fold(query).trim().replace(/\s+/g, " ");
  if (!q) return [];
  const best = new Map<string, { e: TitleEntry; key: [number, number, string] }>();
  for (const e of entries) {
    const t = fold(e.title);
    const b = bucket(t, q);
    if (b < 0) continue;
    const key: [number, number, string] = [b, t.length, t];
    const old = best.get(e.path);
    if (!old || cmp(key, old.key) < 0) best.set(e.path, { e, key });
  }
  return [...best.values()].sort((a, b) => cmp(a.key, b.key)).slice(0, limit).map((x) => x.e);
}

function cmp(a: [number, number, string], b: [number, number, string]): number {
  return a[0] - b[0] || a[1] - b[1] || (a[2] < b[2] ? -1 : a[2] > b[2] ? 1 : 0);
}
