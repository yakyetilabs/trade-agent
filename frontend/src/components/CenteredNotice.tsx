import { AppLogo } from "./AppLogo";

type Tone = "default" | "warn" | "danger" | "success";

interface NoticeAction {
  label: string;
  onClick: () => void;
}

interface CenteredNoticeProps {
  tone?: Tone;
  title: string;
  body?: string;
  action?: NoticeAction;
  secondaryAction?: NoticeAction;
}

const TONE_DOT: Record<Tone, string> = {
  default: "bg-accent",
  warn: "bg-warn",
  danger: "bg-danger",
  success: "bg-success",
};

/** Full-viewport centered card for terminal auth states (misconfigured / forbidden / unavailable). */
export function CenteredNotice({
  tone = "default",
  title,
  body,
  action,
  secondaryAction,
}: CenteredNoticeProps) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-ink px-6">
      <AppLogo />
      <div className="w-full max-w-md rounded-2xl border border-hairline bg-surface p-8 shadow-2xl shadow-black/40">
        <span
          className={`inline-flex h-2.5 w-2.5 rounded-full ${TONE_DOT[tone]}`}
          aria-hidden="true"
        />
        <h1 className="mt-4 text-lg font-semibold text-fg">{title}</h1>
        {body ? <p className="mt-2 text-sm leading-relaxed text-fg-muted">{body}</p> : null}
        {action || secondaryAction ? (
          <div className="mt-6 flex flex-wrap gap-3">
            {action ? (
              <button type="button" className="btn btn-primary" onClick={action.onClick}>
                {action.label}
              </button>
            ) : null}
            {secondaryAction ? (
              <button type="button" className="btn btn-ghost" onClick={secondaryAction.onClick}>
                {secondaryAction.label}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
