/** Marketplace class strings: the player set (ADR 0022) plus form parts. */
import { focus } from "../player/ui";

export {
  backLink,
  chip,
  errorBox,
  focus,
  pageTitle,
  panel,
  primaryButton,
  secondaryButton,
  sectionTitle,
  textLink,
} from "../player/ui";

export const field = `block min-h-11 w-full rounded-md border border-control-border bg-surface px-3 text-[16px] text-ink transition-colors duration-140 placeholder:text-muted hover:border-ink-2 disabled:opacity-40 ${focus}`;

export const label = "block text-[15px] font-medium";

export const hint = "text-[14px] leading-5 text-muted";

export const fieldError = "text-[15px] leading-6 text-error";

export const lead = "max-w-[60ch] text-[16px] leading-6 text-ink-2";

export const meta = "text-[13px] leading-[1.4] text-muted tabular-nums";

/** Match data: dates, times, prices (Geist Mono). */
export const data = "font-mono text-[12px] leading-4 text-muted";

/** Checkbox/radio styled as a pill; the input stays real and focusable. */
export const toggleChip = `relative inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-line-strong px-4 text-[15px] font-medium text-ink-2 transition-colors duration-140 ease-out hover:bg-surface-subtle hover:text-ink has-[:checked]:border-signal has-[:checked]:bg-signal-soft has-[:checked]:text-ink has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-40 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus`;

/** Link-based filter pill (browse specialties, admin status). */
export const filterChip = (on: boolean) =>
  `inline-flex min-h-10 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg border px-3.5 text-[14px] font-medium transition-[background-color,border-color,color,transform] duration-140 ease-out active:scale-[0.97] ${focus} ${
    on
      ? "border-signal bg-signal-soft text-ink"
      : "border-line-strong bg-surface text-ink-2 hover:border-control-border hover:text-ink"
  }`;

/** Small uppercase-free field caption used in cards and summaries. */
export const caption = "text-[13px] leading-[1.35] text-muted";

export const successBox =
  "rounded-xl border border-signal/30 bg-signal-soft p-4 text-[15px] leading-6 text-ink";

export const emptyBox =
  "rounded-xl border border-line bg-surface px-5 py-8 md:px-8";

/** Destructive action reads as destructive in words, not colour alone. */
export const quietDanger = `-ml-1 inline-flex min-h-11 items-center gap-2 rounded-md px-1 text-[15px] font-medium text-ink-2 underline-offset-4 hover:text-error hover:underline ${focus}`;
