import { tokenizeCitations } from "./citations";

/**
 * Render a grounded draft with its cited HTS codes and shipment ids highlighted as monospace chips.
 * Shared by the Console draft panel (F2) and the Audit Trail trace detail (F3) so both surfaces cite
 * identically. Pure presentation over the framework-free `tokenizeCitations` tokenizer.
 */
export function CitedDraft({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
      {tokenizeCitations(text).map((token, index) =>
        token.kind === "text" ? (
          <span key={index}>{token.value}</span>
        ) : (
          <span
            key={index}
            className="mx-0.5 inline-block rounded bg-elevated px-1.5 py-0.5 font-mono text-[0.85em] text-accent"
          >
            {token.value}
          </span>
        ),
      )}
    </p>
  );
}
