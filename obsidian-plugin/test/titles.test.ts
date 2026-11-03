import { describe, expect, it } from "vitest";
import { fold, rankTitles } from "../src/titles";

const titles = ["Heart Failure", "Acute Heart Failure", "Heartburn", "Congestive Heart Failure (Nursing)", "Sjögren Syndrome"];
const entries = titles.map((title) => ({ title, path: `${title}.md` }));
const names = (q: string) => rankTitles(q, entries).map((e) => e.title);

describe("rankTitles", () => {
  it("puts the exact match first", () => {
    expect(names("heart failure")[0]).toBe("Heart Failure");
  });
  it("ranks prefix before word-prefix, shorter first", () => {
    expect(names("heart").slice(0, 3)).toEqual(["Heartburn", "Heart Failure", "Acute Heart Failure"]);
  });
  it("ignores accents and case", () => {
    expect(names("SJOGREN")).toEqual(["Sjögren Syndrome"]);
  });
  it("returns nothing for an empty or blank query", () => {
    expect(names("")).toEqual([]);
    expect(names("   ")).toEqual([]);
  });
  it("respects the limit", () => {
    expect(rankTitles("a", entries, 2).length).toBeLessThanOrEqual(2);
  });
});

describe("fold", () => {
  it("lowercases, strips accents and maps Greek letters", () => {
    expect(fold("Sjögren α-Thal")).toBe("sjogren alpha-thal");
  });
});
