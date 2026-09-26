// Shared coach class strings (ADR 0026). Only the semantic tokens defined in
// globals.css are used; no arbitrary hex value is introduced here or in any
// coach component. Coach pages are dense desktop tools: 36 px controls,
// 13 to 15 px UI type, mono for match data.

/** Result of a coach form action: one plain sentence plus a success flag. */
export type ActionState = { message: string; ok?: boolean };

export const focus =
  "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

/** Focus ring drawn inside the element, for rows in clipped panels. */
export const focusInset =
  "outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus";

const press =
  "transition-[background-color,border-color,color,transform] duration-140 ease-out active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100";

/** Disabled primaries go neutral: a dimmed lime reads as olive, not "off". */
export const primary = `inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-lg bg-action px-3.5 text-[14px] font-semibold text-on-action hover:bg-action-hover ${press} disabled:bg-surface-subtle disabled:text-muted ${focus}`;

export const secondary = `inline-flex h-9 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-line-strong bg-surface-subtle px-3.5 text-[14px] font-medium text-ink hover:border-control-border hover:bg-popover ${press} disabled:opacity-40 ${focus}`;

export const tertiary = `rounded-sm text-[14px] text-ink underline decoration-line-strong underline-offset-4 hover:decoration-signal ${focus}`;

/** Destructive controls read as destructive in words, never by color alone. */
export const destructive = `rounded-sm text-[14px] font-medium text-ink-2 underline decoration-dotted underline-offset-4 hover:text-error ${focus}`;

export const field = `h-9 w-full rounded-md border border-control-border bg-surface px-3 text-[14px] text-ink placeholder:text-muted hover:border-ink-2 ${focus}`;

export const label = "block text-[13px] font-medium leading-[1.35] text-ink";

export const metadata = "text-[13px] leading-[1.4] text-muted";

/** Match data: timestamps, halves, shirt numbers (Geist Mono). */
export const data = "font-mono text-[12px] leading-4 text-muted";

export const panel = "rounded-xl border border-line bg-surface";

export const pageTitle =
  "font-display text-[26px] leading-[1.05] text-balance md:text-[30px]";

export const sectionTitle = "text-[16px] font-semibold leading-[1.3]";

export const componentTitle = "text-[15px] font-semibold leading-[1.35]";

/** Dense list row: hover lifts contrast, never adds a shadow. */
export const row = `flex min-h-11 items-center gap-4 px-4 py-2 transition-colors duration-140 hover:bg-surface-subtle ${focusInset}`;

/** The one approved floating-dialog treatment. */
export const dialog =
  "sh-dialog m-auto w-[min(520px,calc(100vw-2.5rem))] rounded-2xl border-0 bg-popover p-0 text-ink shadow-pop backdrop:bg-scrim";
