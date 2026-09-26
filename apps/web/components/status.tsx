import type { ReactNode } from "react";

export type Tone = "ready" | "pending" | "error" | "neutral";

const dot: Record<Tone, string> = {
  ready: "bg-signal",
  pending: "bg-warning",
  error: "bg-error",
  neutral: "bg-muted",
};

/**
 * Literal status text led by a small state dot (docs/09 "Statuses"). The
 * words carry the meaning; the dot only speeds up scanning a list.
 */
export function Status({
  tone,
  children,
  className = "",
}: {
  tone: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[13px] leading-[1.35] text-ink-2 ${className}`}
    >
      <span
        aria-hidden="true"
        className={`size-1.5 shrink-0 rounded-full ${dot[tone]}`}
      />
      {children}
    </span>
  );
}
