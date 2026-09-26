/** Shared player class strings (ADR 0022, 0026). Tokens only; no raw colours. */

export const focus =
  "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

const press =
  "transition-[background-color,border-color,color,transform] duration-140 ease-out active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100";

/**
 * Signal lime in dark, ink in light: the one "do this next" per screen.
 * Disabled goes neutral, since dimmed lime reads as olive.
 */
export const primaryButton = `inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-action px-5 text-[15px] font-semibold text-on-action hover:bg-action-hover ${press} disabled:bg-surface-subtle disabled:text-muted ${focus}`;

export const secondaryButton = `inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-line-strong bg-surface-subtle px-4 text-[15px] font-medium text-ink hover:border-control-border hover:bg-popover ${press} disabled:opacity-40 ${focus}`;

export const textLink = `sh-nudge inline-flex min-h-11 items-center gap-1 rounded-md text-[15px] font-medium text-ink underline decoration-line-strong decoration-1 underline-offset-4 hover:decoration-signal ${focus}`;

export const backLink = `-ml-1 inline-flex min-h-11 items-center gap-1.5 rounded-md px-1 text-[15px] font-medium text-ink-2 hover:text-ink ${focus}`;

export const pageTitle =
  "font-display text-[28px] leading-[1.05] text-balance md:text-[32px]";

export const sectionTitle =
  "text-[18px] font-semibold leading-[1.3] md:text-[20px]";

/** Match data: timestamps, halves, shirt numbers (Geist Mono). */
export const data = "font-mono text-[12px] leading-4 text-muted";

export const errorBox =
  "rounded-xl border border-error/30 bg-error-soft p-4 text-[15px] leading-6 text-ink";

export const panel = "rounded-xl border border-line bg-surface";

export const chip =
  "inline-flex min-h-7 items-center rounded-md border border-line-strong px-2.5 text-[12px] font-medium leading-none text-ink-2";

/** App-shell sidebar row: icon-only rail, labelled when the sidebar is open. */
export const sideRow = `sh-sb-row relative flex h-9 items-center justify-center gap-2.5 rounded-md text-[14px] transition-[background-color,color,transform] duration-140 ease-out ${focus}`;

/** Active, hover, and resting states for a sidebar row. */
export const sideRowState = (active: boolean) =>
  active
    ? "bg-signal-soft font-medium text-ink"
    : "font-normal text-ink-2 hover:bg-surface-subtle hover:text-ink";

/** Rail tooltip body; `sh-sb-tip` positions and reveals it (globals.css). */
export const tipStyle =
  "rounded-md bg-popover px-2 py-1.5 text-[12px] font-medium leading-none text-ink shadow-pop";

export const sideTip = `sh-sb-tip ${tipStyle}`;
