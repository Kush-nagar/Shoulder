"use client";

import { Footprints, House, ListChecks, Route, Timer } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  {
    href: "/player",
    label: "Home",
    Icon: House,
    match: (path: string) =>
      path === "/player" || path.startsWith("/player/goals"),
  },
  {
    href: "/player/practice",
    label: "Practice",
    Icon: Footprints,
    match: (path: string) => path.startsWith("/player/practice"),
  },
  {
    href: "/player/sessions",
    label: "Sessions",
    Icon: Timer,
    match: (path: string) => path.startsWith("/player/sessions"),
  },
  {
    href: "/player/drills",
    label: "Drills",
    Icon: ListChecks,
    match: (path: string) => path.startsWith("/player/drills"),
  },
  {
    href: "/player/progress",
    label: "Progress",
    Icon: Route,
    match: (path: string) => path.startsWith("/player/progress"),
  },
];

const ring =
  "outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus";

/** Phone: thumb-reach tabs. The only client code is knowing which is open. */
export function BottomTabs() {
  const path = usePathname();
  return (
    <nav
      aria-label="Player navigation"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      <ul className="grid h-16 grid-cols-5 px-0.5">
        {tabs.map(({ href, label, Icon, match }) => {
          const current = match(path);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={current ? "page" : undefined}
                className={`relative flex h-full flex-col items-center justify-center gap-1 rounded-lg text-[13px] leading-none transition-colors duration-150 ease-out ${ring} ${
                  current
                    ? "font-semibold text-ink"
                    : "font-medium text-muted hover:text-ink"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`absolute inset-x-3 top-0 h-0.5 rounded-full bg-action transition-transform duration-180 ease-out ${
                    current ? "scale-x-100" : "scale-x-0"
                  }`}
                />
                <Icon size={22} strokeWidth={2} aria-hidden="true" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Tablet rail (icon over label) that becomes the desktop sidebar (rows). */
export function SideNav() {
  const path = usePathname();
  return (
    <nav aria-label="Player navigation">
      <ul className="space-y-1 px-2 lg:px-3">
        {tabs.map(({ href, label, Icon, match }) => {
          const current = match(path);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={current ? "page" : undefined}
                className={`relative flex min-h-16 flex-col items-center justify-center gap-1 rounded-lg text-[13px] leading-none transition-colors duration-150 ease-out lg:min-h-11 lg:flex-row lg:justify-start lg:gap-3 lg:px-3 lg:text-[15px] ${ring} ${
                  current
                    ? "bg-surface-subtle font-semibold text-ink"
                    : "font-medium text-ink-2 hover:bg-surface-subtle hover:text-ink"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`absolute inset-y-2 -left-2 w-0.5 rounded-full bg-action transition-transform duration-180 ease-out lg:-left-3 ${
                    current ? "scale-y-100" : "scale-y-0"
                  }`}
                />
                <Icon size={22} strokeWidth={2} aria-hidden="true" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

const titles: [string, string][] = [
  ["/player/practice/new", "Film practice"],
  ["/player/practice", "Practice"],
  ["/player/sessions/new", "Record a session"],
  ["/player/sessions", "Sessions"],
  ["/player/drills", "Drills"],
  ["/player/progress", "Progress"],
  ["/player/profile", "Profile"],
  ["/player/goals", "Your clips"],
];

/** Phone top bar title; Home shows none because its greeting is the title. */
export function TopBarTitle() {
  const path = usePathname();
  const title = titles.find(([prefix]) => path.startsWith(prefix))?.[1];
  return title ? (
    <span className="truncate text-[16px] font-semibold">{title}</span>
  ) : null;
}
