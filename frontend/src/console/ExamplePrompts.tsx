import type { Vendor } from "../types/api";
import { buildExamplePrompts } from "./promptCatalog";

interface ExamplePromptsProps {
  /** The selected vendor scope; prompts are grounded in its categories. */
  vendor: Vendor;
  /** The full vendor list, so the scope-guard prompt can name a DIFFERENT real vendor. */
  vendors: Vendor[];
  /** Pre-fills the composer with the chosen prompt; never submits. */
  onSelect: (prompt: string) => void;
}

/**
 * Idle-state example prompts: a guided tour of the agent pipeline and its deterministic
 * safeguards for a cold visitor who does not know what a trade-compliance inquiry looks
 * like. A click only pre-fills the composer - the visitor always triggers the run.
 * Prompt curation lives in `promptCatalog.ts`.
 */
export function ExamplePrompts({ vendor, vendors, onSelect }: ExamplePromptsProps) {
  const prompts = buildExamplePrompts(vendor, vendors);
  return (
    <section className="mb-6" aria-label="Example inquiries">
      <p className="text-sm font-medium text-fg">Try one of these</p>
      <p className="mt-1 text-xs text-fg-subtle">
        Each prompt exercises a different part of the system - from the full grounded draft to
        the deterministic guards that never reach the model.
      </p>
      <ul className="mt-3 flex flex-col gap-1">
        {prompts.map(({ label, prompt }) => (
          <li key={label}>
            <button
              type="button"
              onClick={() => onSelect(prompt)}
              className="w-full rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            >
              <span className="font-mono text-[11px] tracking-wider text-accent uppercase">
                {label}
              </span>
              <span className="mt-0.5 block text-sm text-fg-muted">{prompt}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
