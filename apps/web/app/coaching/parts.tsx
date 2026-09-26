import { ShieldCheck } from "lucide-react";
import type { BookingStatus } from "./types";

/** Demo profiles from `scripts/seed_demo_coaches.py` open their bio with this. */
const DEMO_PREFIX = "Demo coach profile.";

export const isDemo = (bio: string) => bio.startsWith(DEMO_PREFIX);

/** The bio without the demo marker; the "Demo" tag says it instead. */
export const bioText = (bio: string) =>
  isDemo(bio) ? bio.slice(DEMO_PREFIX.length).trim() : bio;

/** Demo names carry "(demo)"; the tag says it, so the name drops it. */
export const shownName = (name: string, bio: string) =>
  isDemo(bio) ? name.replace(/\s*\(demo\)\s*$/i, "") : name;

export function initials(name: string): string {
  const words = name
    .trim()
    .split(/\s+/)
    .filter((w) => /^\p{L}/u.test(w));
  const first = words[0]?.[0] ?? "?";
  const last = words.length > 1 ? (words.at(-1)?.[0] ?? "") : "";
  return `${first}${last}`.toUpperCase();
}

// Token pairs only, so every tint follows the theme.
const TINTS = [
  "border border-line-strong bg-surface-subtle text-ink",
  "border border-line bg-popover text-ink-2",
  "border border-line-strong bg-surface text-ink",
];

/** Initials on a tinted tile: no photos of anyone, no external images. */
export function Monogram({
  name,
  size = "size-14 text-[24px]",
}: {
  name: string;
  size?: string;
}) {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return (
    <span
      aria-hidden="true"
      className={`${size} ${TINTS[hash % TINTS.length]} flex shrink-0 items-center justify-center rounded-xl font-display leading-none tracking-wide`}
    >
      {initials(name)}
    </span>
  );
}

export function VerifiedBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border border-line-strong font-medium text-ink-2 ${
        compact ? "min-h-7 px-2.5 text-[13px]" : "min-h-8 px-3 text-[14px]"
      }`}
    >
      <ShieldCheck
        size={compact ? 15 : 16}
        strokeWidth={2.25}
        aria-hidden="true"
        className="shrink-0 text-ink-2"
      />
      Background check verified
    </span>
  );
}

export function DemoTag() {
  return (
    <span className="inline-flex min-h-6 items-center rounded-md border border-line-strong px-2 text-[12px] font-semibold leading-none text-muted">
      Demo
    </span>
  );
}

const TONE: Record<BookingStatus, string> = {
  pending_payment: "border border-control-border text-ink-2",
  confirmed: "bg-action-soft text-ink",
  completed: "bg-surface-subtle text-ink-2",
  cancelled_by_player: "bg-surface-subtle text-muted",
  cancelled_by_coach: "bg-surface-subtle text-muted",
  expired: "bg-surface-subtle text-muted",
};

export function StatusChip({
  status,
  label,
}: {
  status: BookingStatus;
  label: string;
}) {
  return (
    <span
      className={`inline-flex min-h-7 items-center rounded-full px-2.5 text-[13px] font-semibold leading-none ${TONE[status]}`}
    >
      {label}
    </span>
  );
}
