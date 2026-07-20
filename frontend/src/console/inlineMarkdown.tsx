import type { ReactNode } from "react";

// The reasoning stream (the model's raw thinking) arrives with light inline markdown: **bold**
// section headers and `code` tool names. We render just those two spans rather than pull in a full
// markdown dependency for advisory text. Only balanced pairs match, so an unclosed marker - a
// partial token mid-typewriter reveal, e.g. "**Investigating" before its closing "**" is typed -
// falls through as literal text instead of throwing or swallowing the rest of the line.
const INLINE_PATTERN = /\*\*(.+?)\*\*|`([^`]+?)`/g;

/** Turn a subset of inline markdown (**bold**, `code`) into React nodes; everything else is literal. */
export function renderInlineMarkdown(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;

  for (const match of text.matchAll(INLINE_PATTERN)) {
    const start = match.index ?? 0;
    if (start > lastIndex) {
      nodes.push(text.slice(lastIndex, start));
    }
    if (match[1] !== undefined) {
      nodes.push(
        <strong key={key++} className="font-semibold text-fg">
          {match[1]}
        </strong>,
      );
    } else {
      nodes.push(
        <code key={key++} className="rounded bg-fg/10 px-1 py-0.5 font-mono text-[0.9em] text-fg">
          {match[2]}
        </code>,
      );
    }
    lastIndex = start + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}
