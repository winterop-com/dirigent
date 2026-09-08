import { describe, expect, it } from "vitest";

import { tokenizeJson } from "@/lib/json-tokens";

describe("tokenizeJson", () => {
  it("tells a key from a string by the colon that follows it", () => {
    expect(tokenizeJson('{"station": "st-1"}')).toEqual([
      { kind: "punctuation", text: "{" },
      { kind: "key", text: '"station"' },
      { kind: "punctuation", text: ":" },
      { kind: "punctuation", text: " " },
      { kind: "string", text: '"st-1"' },
      { kind: "punctuation", text: "}" },
    ]);
  });

  it("reads numbers, literals, and negative floats", () => {
    const kinds = tokenizeJson("[4.5, -3.4, true, null, 1e-3]").map(
      (token) => token.kind,
    );
    expect(kinds).toEqual([
      "punctuation",
      "number",
      "punctuation",
      "number",
      "punctuation",
      "literal",
      "punctuation",
      "literal",
      "punctuation",
      "number",
      "punctuation",
    ]);
  });

  it("keeps an escaped quote inside a string, and a colon inside a value is not a key", () => {
    expect(
      tokenizeJson('{"note": "a \\"quoted\\" word: here"}').map(
        (token) => token.kind,
      ),
    ).toEqual([
      "punctuation",
      "key",
      "punctuation",
      "punctuation",
      "string",
      "punctuation",
    ]);
  });

  it("reassembles to exactly the input", () => {
    const text = '{\n  "value": [\n    {"celsius": -3.4, "ok": false}\n  ]\n}';
    expect(
      tokenizeJson(text)
        .map((token) => token.text)
        .join(""),
    ).toBe(text);
  });
});
