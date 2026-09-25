"use client";

import { ClipboardList, LayoutDashboard, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { focus } from "./ui";

export const railItem =
  "group relative flex h-10 items-center gap-3 rounded-lg px-3 text-[15px] font-medium transition-colors duration-140 lg:justify-center xl:justify-start";

/** Between 1024px and 1280px the rail is icon-only, so the label is a tooltip. */
export function RailLabel({ children }: { children: string }) {
  return (
    <>
      <span aria-hidden="true" className="lg:hidden xl:inline">
        {children}
      </span>
      <span
        aria-hidden="true"
        className="pointer-events-none invisible absolute left-full z-20 ml-2 hidden whitespace-nowrap rounded-lg border border-line bg-surface px-3 py-1 text-[13px] font-normal text-ink lg:block lg:group-hover:visible lg:group-focus-visible:visible xl:hidden"
      >
        {children}
      </span>
    </>
  );
}

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

export function CoachNav() {
  const current = section(usePathname());
  return (
    <nav
      aria-label="Coach"
      className="flex flex-1 items-center gap-1 overflow-x-auto lg:flex-none lg:flex-col lg:items-stretch lg:overflow-visible"
    >
      {links.map(({ href, label, Icon }) => {
        const active = current === href;
        return (
          <Link
            key={href}
            href={href}
            aria-label={label}
            aria-current={active ? "page" : undefined}
            className={`${railItem} ${
              active
                ? "bg-action-soft text-ink"
                : "text-ink-2 hover:bg-surface-subtle hover:text-ink"
            } ${focus}`}
          >
            <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
            <RailLabel>{label}</RailLabel>
          </Link>
        );
      })}
    </nav>
  );
}
