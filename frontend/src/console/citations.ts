/**
 * Draft citation tokenizer. Splits the model's grounded draft into plain text and the two kinds of
 * cited identifier the Console renders as monospace chips: HTS codes and shipment ids
 * (docs/FRONTEND_PLAN.md, Console spec). Pure and framework-free so it is unit-tested directly.
 */

export type CitationKind = "text" | "hts" | "shipment";

export interface CitationToken {
  kind: CitationKind;
  value: string;
}

// HTS: a 4.2 heading or a full 4.2.4 code, not embedded in a longer number.
// Shipment: the seed id form `S-1001` (>= 3 digits). Lookarounds keep partial numbers from matching.
const CITATION_PATTERN = /(?<!\d)\d{4}\.\d{2}(?:\.\d{4})?(?!\d)|\bS-\d{3,}\b/g;

function classify(match: string): Exclude<CitationKind, "text"> {
  return match.startsWith("S-") ? "shipment" : "hts";
}

/**
 * Tokenize `text` into a flat sequence of text and citation tokens, in order. Adjacent runs of plain
 * text are preserved as single tokens so the renderer can emit them verbatim; empty input yields `[]`.
 */
export function tokenizeCitations(text: string): CitationToken[] {
  const tokens: CitationToken[] = [];
  let lastIndex = 0;

  for (const match of text.matchAll(CITATION_PATTERN)) {
    const value = match[0];
    const start = match.index;
    if (start > lastIndex) {
      tokens.push({ kind: "text", value: text.slice(lastIndex, start) });
    }
    tokens.push({ kind: classify(value), value });
    lastIndex = start + value.length;
  }

  if (lastIndex < text.length) {
    tokens.push({ kind: "text", value: text.slice(lastIndex) });
  }
  return tokens;
}
