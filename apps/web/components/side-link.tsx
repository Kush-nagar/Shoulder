import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { sideRow, sideRowState, sideTip } from "../app/player/ui";

/**
 * One sidebar destination, shared by the player, coach, and coaching shells.
 * Active: lime indicator on the rail edge, a faint lime tint, lime icon. The
 * indicator carries a view-transition name, so it slides to the next item on
 * navigation (ADR 0024, 0026).
 */
export function SideLink({
  href,
  label,
  Icon,
  current,
}: {
  href: string;
  label: string;
  Icon: LucideIcon;
  current: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className={`${sideRow} group ${sideRowState(current)}`}
    >
      {current ? (
        <span
          aria-hidden="true"
          style={{ viewTransitionName: "sh-nav-marker" }}
          className="absolute inset-y-2 -left-2.5 w-0.5 rounded-r-sm bg-signal"
        />
      ) : null}
      <Icon
        size={18}
        strokeWidth={current ? 2 : 1.75}
        aria-hidden="true"
        className={`shrink-0 transition-transform duration-140 ease-out group-active:scale-95 ${current ? "text-signal" : "text-muted group-hover:text-ink"}`}
      />
      <span className="sh-sb-label">{label}</span>
      <span aria-hidden="true" className={sideTip}>
        {label}
      </span>
    </Link>
  );
}
