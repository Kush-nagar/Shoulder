// Shared class strings and the shared form-action result. Only the semantic
// tokens defined in globals.css are used (ADR 0022 palette, light only on
// coach pages); no arbitrary hex value is introduced here or in any coach
// component.

/** Result of a coach form action: one plain sentence plus a success flag. */
export type ActionState = { message: string; ok?: boolean };

export const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export const primary = `inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-action px-4 text-[15px] font-semibold text-on-action transition-[background-color,transform] duration-140 hover:bg-action-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 disabled:active:scale-100 ${focus}`;

export const secondary = `inline-flex h-10 items-center justify-center gap-2 rounded-lg border border-control-border bg-surface px-4 text-[15px] font-semibold text-ink transition-colors duration-140 hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-45 ${focus}`;

export const tertiary = `rounded-sm text-[15px] text-ink underline decoration-line-strong underline-offset-2 hover:text-action hover:decoration-action ${focus}`;

/** Destructive controls read as destructive in words, never by color alone. */
export const destructive = `rounded-sm text-[15px] font-medium text-ink underline decoration-dotted underline-offset-2 hover:text-error ${focus}`;

export const field = `h-10 w-full rounded-lg border border-control-border bg-surface px-3 text-[15px] text-ink placeholder:text-muted hover:border-ink-2 ${focus}`;

export const label = "block text-[13px] font-semibold leading-[1.35] text-ink";

export const metadata = "text-[13px] leading-[1.4] text-muted";

export const panel = "rounded-xl border border-line bg-surface";

export const pageTitle =
  "font-display text-[30px] leading-[1.05] text-balance md:text-[36px]";

export const sectionTitle = "text-[22px] font-semibold leading-[1.25]";

export const componentTitle = "text-[17px] font-semibold leading-[1.35]";

/** The one approved floating-dialog shadow from the design system. */
export const dialog =
  "w-[min(560px,calc(100vw-2.5rem))] rounded-xl border border-line bg-surface p-0 text-ink shadow-[0_16px_48px_rgba(23,21,18,0.14)] backdrop:bg-ink/40";
