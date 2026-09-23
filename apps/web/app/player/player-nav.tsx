"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  {
    href: "/player",
    label: "Home",
    match: (path: string) =>
      path === "/player" || path.startsWith("/player/goals"),
  },
  {
    href: "/player/practice",
    label: "Practice",
    match: (path: string) => path.startsWith("/player/practice"),
  },
  {
    href: "/player/progress",
    label: "Progress",
    match: (path: string) => path.startsWith("/player/progress"),
  },
];

/** Thumb-reach tabs; the only client code here is knowing which one is open. */
export function PlayerNav() {
  const path = usePathname();
  return (
    <nav
      aria-label="Player navigation"
      className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)]"
    >
      <ul className="mx-auto grid max-w-140 grid-cols-3 px-2">
        {tabs.map((tab) => {
          const current = tab.match(path);
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={current ? "page" : undefined}
                className={`relative flex min-h-14 items-center justify-center rounded-lg text-[15px] transition-colors duration-150 ease-out focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus ${
                  current
                    ? "font-semibold text-ink"
                    : "font-medium text-muted hover:text-ink"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`absolute inset-x-6 top-0 h-0.5 rounded-full bg-action transition-transform duration-150 ease-out ${
                    current ? "scale-x-100" : "scale-x-0"
                  }`}
                />
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
