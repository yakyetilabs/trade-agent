import { type KeyboardEvent, type Ref } from "react";

const MAX_INQUIRY_LENGTH = 4000;

interface InquiryFormProps {
  /** The selected vendor scope; submission is blocked until one is chosen. */
  vendorId: string | null;
  /** A run is connecting or streaming - the input locks until it finishes. */
  running: boolean;
  /** Controlled composer text - the page owns it so example prompts can pre-fill it. */
  value: string;
  onChange: (text: string) => void;
  onSubmit: (inquiry: string) => void;
  /** Lets the page focus the textarea after a prompt chip pre-fills it. */
  inputRef?: Ref<HTMLTextAreaElement>;
}

/**
 * The natural-language inquiry input (1-4000 chars, matching `InquiryRequest`). Cmd/Ctrl+Enter
 * submits. Submission is disabled with no vendor scope, while a run is in flight, or when the text is
 * empty or over the limit; the counter turns red past the cap so an over-long paste is visible rather
 * than silently truncated. The text is controlled (`value`/`onChange`) so the idle example prompts
 * can pre-fill the composer from outside.
 */
export function InquiryForm({
  vendorId,
  running,
  value,
  onChange,
  onSubmit,
  inputRef,
}: InquiryFormProps) {
  const trimmedLength = value.trim().length;
  const overLimit = value.length > MAX_INQUIRY_LENGTH;
  const canSubmit = Boolean(vendorId) && !running && trimmedLength > 0 && !overLimit;

  function submit() {
    if (!canSubmit) return;
    onSubmit(value.trim());
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form
      className="rounded-xl border border-hairline bg-surface p-5"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor="inquiry" className="block text-sm font-medium text-fg">
        Inquiry
      </label>
      <p className="mt-1 text-xs text-fg-subtle">
        Ask about a held or flagged shipment, a tariff code, or clearance requirements for the
        selected vendor.
      </p>

      <textarea
        id="inquiry"
        ref={inputRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={running}
        rows={4}
        placeholder="e.g. Why is shipment S-1003 held, and what is required to clear HTS 8542.31.0001?"
        className="mt-3 w-full resize-y rounded-lg border border-hairline bg-elevated px-3 py-2.5 text-sm text-fg placeholder:text-fg-subtle focus-visible:border-accent/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-60"
      />

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-xs text-fg-subtle" aria-live="polite">
          {vendorId ? (
            <>
              Scoped to <span className="font-mono text-fg-muted">{vendorId}</span>
            </>
          ) : (
            "Select a vendor to run an inquiry."
          )}
        </span>
        <div className="ml-auto flex items-center gap-3">
          <span
            className={`font-mono text-xs ${overLimit ? "text-danger" : "text-fg-subtle"}`}
            aria-live="polite"
          >
            {value.length.toLocaleString("en-US")} / {MAX_INQUIRY_LENGTH.toLocaleString("en-US")}
          </span>
          <button type="submit" className="btn btn-primary" disabled={!canSubmit}>
            {running ? "Running…" : "Run inquiry"}
          </button>
        </div>
      </div>
    </form>
  );
}
