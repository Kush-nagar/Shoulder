"use client";

import { ClipboardList, LayoutDashboard, Upload, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SideLink } from "../../components/side-link";
import { focus } from "./ui";

const links = [
  { href: "/coach", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/coach/roster", label: "Players", Icon: Users },
  { href: "/coach/plans", label: "Plans", Icon: ClipboardList },
] as const;

/** Match and review pages hang off a player's roster row or the dashboard. */
function section(pathname: string): string {
  if (pathname === "/coach") return "/coach";
  if (pathname.startsWith("/coach/plans")) return "/coach/plans";
  if (pathname.startsWith("/coach/upload")) return "/coach/upload";
  if (pathname.startsWith("/coach/games")) return "/coach";
  return "/coach/roster";
}

/**
 * `side`: the sidebar/rail rows (icon only with a tooltip when collapsed),
 * grouped as team work, then the match footage workflow.
 * `bar`: the phone top bar, icon and label side by side.
 */
export function CoachNav({ variant }: { variant: "side" | "bar" }) {
  const current = section(usePathname());
  if (variant === "bar")
    return (
      <nav
        aria-label="Coach"
        className="flex flex-1 items-center gap-0.5 overflow-x-auto"
      >
        {links.map(({ href, label, Icon }) => {
          const active = current === href;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`flex h-9 min-w-11 shrink-0 items-center justify-center gap-2 rounded-md px-2.5 text-[14px] font-medium transition-colors duration-140 ${
                active
                  ? "bg-signal-soft text-ink"
                  : "text-ink-2 hover:bg-surface-subtle hover:text-ink"
              } ${focus}`}
            >
              <Icon
                size={18}
                strokeWidth={active ? 2 : 1.75}
                aria-hidden="true"
                className={active ? "text-signal" : ""}
              />
              {/* Icon-first: only the current section spells out its name. */}
              <span className={active ? "" : "sr-only"}>{label}</span>
            </Link>
          );
        })}
      </nav>
    );
  return (
    <nav aria-label="Coach">
      <ul className="space-y-0.5">
        {links.map(({ href, label, Icon }) => (
          <li key={href}>
            <SideLink
              href={href}
              label={label}
              Icon={Icon}
              current={current === href}
            />
          </li>
        ))}
      </ul>
      <div className="mt-3 border-t border-line pt-3">
        <p className="sh-sb-wide px-2.5 pb-1.5 text-[12px] text-muted">
          Match footage
        </p>
        <ul className="space-y-0.5">
          <li>
            <SideLink
              href="/coach/upload"
              label="Upload match"
              Icon={Upload}
              current={current === "/coach/upload"}
            />
          </li>
        </ul>
      </div>
    </nav>
  );
}
