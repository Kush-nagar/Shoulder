/** Shared player class strings (ADR 0022). Tokens only; no raw colours. */

export const focus =
  "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

const press =
  "transition-[background-color,border-color,color,transform] duration-150 ease-out active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 disabled:active:scale-100";

export const primaryButton = `inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-action px-5 text-[16px] font-semibold text-on-action hover:bg-action-hover ${press} ${focus}`;

export const secondaryButton = `inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-control-border bg-surface px-4 text-[16px] font-semibold text-ink hover:bg-surface-subtle ${press} ${focus}`;

export const textLink = `inline-flex min-h-11 items-center gap-1 rounded-lg text-[16px] font-semibold text-action underline-offset-4 hover:underline ${focus}`;

export const backLink = `-ml-1 inline-flex min-h-11 items-center gap-1.5 rounded-lg px-1 text-[16px] font-medium text-ink-2 hover:text-ink ${focus}`;

export const pageTitle =
  "font-display text-[28px] leading-[1.1] text-balance md:text-[34px]";

export const sectionTitle =
  "text-[20px] font-semibold leading-[1.25] md:text-[22px]";

export const errorBox =
  "rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error";

export const panel = "rounded-xl border border-line bg-surface";

export const chip =
  "inline-flex min-h-8 items-center rounded-full border border-control-border px-3 text-[13px] font-semibold leading-none text-ink-2";

/** App-shell sidebar row: icon-only rail, labelled when the sidebar is open. */
export const sideRow = `sh-sb-row relative flex h-11 items-center justify-center gap-3 rounded-lg text-[15px] transition-[background-color,color,transform] duration-150 ease-out ${focus}`;

/** Rail tooltip body; `sh-sb-tip` positions and reveals it (globals.css). */
export const tipStyle =
  "rounded-md bg-ink px-2.5 py-1.5 text-[13px] font-medium leading-none text-paper shadow-[0_4px_16px_rgba(23,21,18,.18)]";

export const sideTip = `sh-sb-tip ${tipStyle}`;
