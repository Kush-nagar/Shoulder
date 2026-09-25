"use client";

import {
  Footprints,
  Handshake,
  House,
  ListChecks,
  Route,
  Timer,
} from "lucide-react";
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
    match: (path: string) =>
      path.startsWith("/player/sessions") || path.startsWith("/player/team"),
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

// Rail and sidebar only; on phones it sits in the account menu (≤5 tabs).
const sideTabs =
  process.env.NEXT_PUBLIC_MARKETPLACE_ENABLED === "on"
    ? [
        ...tabs,
        {
          href: "/coaching",
          label: "Coaching",
          Icon: Handshake,
          match: (path: string) => path.startsWith("/coaching"),
        },
      ]
    : tabs;

const ring =
  "outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus";

/** Phone: thumb-reach tabs. The only client code is knowing which is open. */
export function BottomTabs() {
  const path = usePathname();
  return (
    <nav
      aria-label="Player navigation"
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-paper/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
    >
      <ul className="grid h-16 grid-cols-5 px-0.5">
        {tabs.map(({ href, label, Icon, match }) => {
          const current = match(path);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={current ? "page" : undefined}
                className={`group relative flex h-full flex-col items-center justify-center gap-1 rounded-lg text-[12px] leading-none transition-colors duration-150 ease-out ${ring} ${
                  current
                    ? "font-semibold text-ink"
                    : "font-medium text-muted hover:text-ink"
                }`}
              >
                {current ? (
                  <span
                    aria-hidden="true"
                    style={{ viewTransitionName: "sh-tab-marker" }}
                    className="absolute inset-x-4 top-0 h-0.5 rounded-full bg-action"
                  />
                ) : null}
                <Icon
                  size={22}
                  strokeWidth={current ? 2.25 : 2}
                  aria-hidden="true"
                  className="transition-transform duration-150 ease-out group-active:scale-90"
                />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

const tip =
  "sh-sb-tip rounded-md bg-ink px-2.5 py-1.5 text-[13px] font-medium leading-none text-paper shadow-[0_4px_16px_rgba(23,21,18,.18)]";

/** Icon rail with tooltips that opens into the labelled desktop sidebar. */
export function SideNav() {
  const path = usePathname();
  return (
    <nav aria-label="Player navigation">
      <ul className="space-y-1 px-3">
        {sideTabs.map(({ href, label, Icon, match }) => {
          const current = match(path);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={current ? "page" : undefined}
                className={`sh-sb-row group relative flex h-11 items-center justify-center gap-3 rounded-lg text-[15px] transition-colors duration-150 ease-out ${ring} ${
                  current
                    ? "bg-surface-subtle font-semibold text-ink"
                    : "font-medium text-ink-2 hover:bg-surface-subtle hover:text-ink"
                }`}
              >
                {current ? (
                  <span
                    aria-hidden="true"
                    style={{ viewTransitionName: "sh-nav-marker" }}
                    className="absolute inset-y-2.5 -left-3 w-[3px] rounded-r-full bg-action"
                  />
                ) : null}
                <Icon
                  size={21}
                  strokeWidth={current ? 2.25 : 2}
                  aria-hidden="true"
                  className="shrink-0 transition-transform duration-150 ease-out group-hover:scale-105 group-active:scale-95"
                />
                <span className="sh-sb-label">{label}</span>
                <span aria-hidden="true" className={tip}>
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

const titles: [string, string][] = [
  ["/player/practice/new", "Film practice"],
  ["/player/practice", "Practice"],
  ["/player/sessions/new", "Record a session"],
  ["/player/sessions", "Sessions"],
  ["/player/team", "Team board"],
  ["/player/drills", "Drills"],
  ["/player/progress", "Progress"],
  ["/player/profile", "Profile"],
  ["/player/goals", "Your clips"],
  ["/player/plans", "Plans"],
  ["/coaching", "Coaching"],
];

/** Phone top bar title; Home shows none because its greeting is the title. */
export function TopBarTitle() {
  const path = usePathname();
  const title = titles.find(([prefix]) => path.startsWith(prefix))?.[1];
  return title ? (
    <span className="truncate text-[16px] font-semibold">{title}</span>
  ) : null;
}
