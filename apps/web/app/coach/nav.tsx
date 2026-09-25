"use client";

import { ClipboardList, LayoutDashboard, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { sideRow, sideTip } from "../player/ui";
import { focus } from "./ui";

const links = [
  { href: "/coach", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/coach/roster", label: "Players", Icon: Users },
  { href: "/coach/plans", label: "Plans", Icon: ClipboardList },
] as const;

/** Match, upload, and review pages all hang off a player's roster row. */
function section(pathname: string): string {
  if (pathname === "/coach") return "/coach";
  if (pathname.startsWith("/coach/plans")) return "/coach/plans";
  return "/coach/roster";
}

/**
 * `side`: the sidebar/rail rows (icon only with a tooltip when collapsed).
 * `bar`: the phone top bar, icon and label side by side.
 */
export function CoachNav({ variant }: { variant: "side" | "bar" }) {
  const current = section(usePathname());
  if (variant === "bar")
    return (
      <nav
        aria-label="Coach"
        className="flex flex-1 items-center gap-1 overflow-x-auto"
      >
        {links.map(({ href, label, Icon }) => {
          const active = current === href;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex h-10 min-w-11 shrink-0 items-center justify-center gap-2 rounded-lg px-3 text-[15px] font-medium transition-colors duration-150 ${
                active
                  ? "bg-action-soft text-ink"
                  : "text-ink-2 hover:bg-surface-subtle hover:text-ink"
              } ${focus}`}
            >
              <Icon size={18} strokeWidth={2} aria-hidden="true" />
              {/* Icon-first: only the current section spells out its name. */}
              <span className={active ? "" : "sr-only"}>{label}</span>
            </Link>
          );
        })}
      </nav>
    );
  return (
    <nav aria-label="Coach">
      <ul className="space-y-1">
        {links.map(({ href, label, Icon }) => {
          const active = current === href;
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`${sideRow} group ${
                  active
                    ? "bg-action-soft font-semibold text-ink"
                    : "font-medium text-ink-2 hover:bg-surface-subtle hover:text-ink"
                }`}
              >
                {active ? (
                  <span
                    aria-hidden="true"
                    style={{ viewTransitionName: "sh-nav-marker" }}
                    className="absolute inset-y-2.5 -left-3 w-[3px] rounded-r-full bg-action"
                  />
                ) : null}
                <Icon
                  size={21}
                  strokeWidth={2}
                  aria-hidden="true"
                  className="shrink-0 transition-transform duration-150 ease-out group-hover:scale-105 group-active:scale-95"
                />
                <span className="sh-sb-label">{label}</span>
                <span aria-hidden="true" className={sideTip}>
                  {label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
