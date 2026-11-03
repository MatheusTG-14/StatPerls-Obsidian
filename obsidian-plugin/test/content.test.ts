import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { makeSearcher, shardKey, snippet, tokenize } from "../src/content";

const cases: { text: string; tokens: string[] }[] = JSON.parse(readFileSync(join(__dirname, "tokenize-cases.json"), "utf8"));

// Same fixture as tests/test_search_index.py: ("A","Intro","heart failure heart"), ("B","Treatment","failure")
const files: Record<string, string> = {
  "meta.json": JSON.stringify({ n: 2, avgdl: 2.0, version: 1 }),
  "docs.json": JSON.stringify([["A", "Intro", 3], ["B", "Treatment", 1]]),
  "terms/k-hea.json": JSON.stringify({ heart: [[0, 2]] }),
  "terms/k-fai.json": JSON.stringify({ failure: [[0, 1], [1, 1]] }),
};
const load = async (rel: string) => files[rel] ?? null;

describe("tokenize", () => {
  it("matches the shared Python cases", () => {
    for (const c of cases) expect(tokenize(c.text), c.text).toEqual(c.tokens);
  });
  it("pads short shard keys", () => {
    expect(shardKey("mg")).toBe("mg_");
  });
});

describe("search", () => {
  it("requires every term in one section", async () => {
    const hits = await makeSearcher(load)("heart failure");
    expect(hits.map((h) => [h.stem, h.section, h.sections])).toEqual([["A", "Intro", 1]]);
  });
  it("returns all matching articles, best score first", async () => {
    const hits = await makeSearcher(load)("failure");
    expect(hits.map((h) => h.stem).sort()).toEqual(["A", "B"]);
    expect(hits[0].score).toBeGreaterThanOrEqual(hits[1].score);
  });
  it("filters by section", async () => {
    const hits = await makeSearcher(load)("failure", { section: "Treatment" });
    expect(hits.map((h) => h.stem)).toEqual(["B"]);
  });
  it("returns nothing for stopwords, punctuation or unknown terms", async () => {
    const s = makeSearcher(load);
    expect(await s("the")).toEqual([]);
    expect(await s("?!")).toEqual([]);
    expect(await s("zzzz")).toEqual([]);
  });
});

describe("snippet", () => {
  const note = "# T\n\n## Intro\n\nHeart [[Heart Failure|failure]] is common. Other text.\n\n## Treatment \\/ Management\n\nRest & <care>.\n";
  it("marks the hit in the first matching sentence, links reduced to text", () => {
    expect(snippet(note, "Intro", ["failure"])).toBe("Heart <mark>failure</mark> is common.");
  });
  it("finds escaped headings and escapes HTML", () => {
    expect(snippet(note, "Treatment / Management", ["rest"])).toBe("<mark>Rest</mark> &amp; &lt;care&gt;.");
  });
  it("returns null when the heading is missing", () => {
    expect(snippet(note, "Prognosis", ["failure"])).toBeNull();
  });
});

describe("snippet highlighting", () => {
  it("never marks inside HTML escapes", () => {
    const note = "## Intro\n\nAmp & lt values.\n";
    expect(snippet(note, "Intro", ["amp"])).toBe("<mark>Amp</mark> &amp; lt values.");
  });
});
