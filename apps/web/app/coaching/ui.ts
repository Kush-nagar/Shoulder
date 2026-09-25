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

export const field = `block min-h-11 w-full rounded-lg border border-control-border bg-surface px-3 text-[16px] text-ink transition-colors duration-150 hover:border-ink-2 disabled:opacity-45 ${focus}`;

export const label = "block text-[16px] font-semibold";

export const hint = "text-[14px] leading-5 text-muted";

export const fieldError = "text-[15px] leading-6 text-error";

export const lead = "max-w-[60ch] text-[16px] leading-6 text-ink-2";

export const meta = "text-[13px] leading-[1.4] text-muted tabular-nums";

/** Checkbox/radio styled as a pill; the input stays real and focusable. */
export const toggleChip = `relative inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border border-control-border px-4 text-[15px] font-semibold text-ink-2 transition-colors duration-150 ease-out hover:bg-surface-subtle has-[:checked]:border-ink has-[:checked]:bg-ink has-[:checked]:text-paper has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-45 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus`;

export const successBox =
  "rounded-xl border border-line-strong bg-action-soft p-4 text-[16px] leading-6 text-ink";

export const emptyBox =
  "rounded-xl border border-dashed border-control-border px-5 py-8 md:px-8";

/** Destructive action reads as destructive in words, not colour alone. */
export const quietDanger = `-ml-1 inline-flex min-h-11 items-center gap-2 rounded-lg px-1 text-[16px] font-semibold text-ink-2 underline-offset-4 hover:text-error hover:underline ${focus}`;
