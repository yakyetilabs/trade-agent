interface AppLogoProps {
  /** Hide the wordmark, showing only the mark (e.g. on very narrow layouts). */
  markOnly?: boolean;
  className?: string;
}

/** The three-node "pipeline" mark - the same glyph as the favicon, echoing the four-stage run. */
function PipelineMark({ size = 30 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className="shrink-0"
    >
      <rect width="32" height="32" rx="7" fill="var(--color-elevated)" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="6.5" fill="none" stroke="var(--color-hairline)" />
      <path
        d="M11.5 16h2M18.5 16h2"
        stroke="var(--color-accent)"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.5"
      />
      <circle cx="9" cy="16" r="2.6" fill="var(--color-accent)" />
      <circle cx="16" cy="16" r="2.6" fill="var(--color-accent)" opacity="0.6" />
      <circle cx="23" cy="16" r="2.6" fill="var(--color-accent)" opacity="0.32" />
    </svg>
  );
}

export function AppLogo({ markOnly = false, className }: AppLogoProps) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className ?? ""}`}>
      <PipelineMark />
      {markOnly ? null : (
        <span className="flex flex-col leading-none">
          <span className="font-mono text-[15px] font-semibold tracking-tight text-fg">
            trade-agent
          </span>
          <span className="mt-1 text-[10px] font-medium uppercase tracking-[0.16em] text-fg-subtle">
            Analyst Console
          </span>
        </span>
      )}
    </span>
  );
}
