"use client";

import {
  CalendarCheck,
  ClipboardCheck,
  Flag,
  Search,
  UserRoundCheck,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { focus } from "../player/ui";

const sets = {
  coaching: [
    {
      href: "/coaching",
      label: "Find a coach",
      Icon: Search,
      match: (p: string) =>
        p === "/coaching" || p.startsWith("/coaching/coaches"),
    },
    {
      href: "/coaching/bookings",
      label: "Your bookings",
      Icon: CalendarCheck,
      match: (p: string) => p.startsWith("/coaching/bookings"),
    },
    {
      href: "/coaching/coach",
      label: "Coach on Shoulder",
      Icon: UserRoundCheck,
      match: (p: string) =>
        p.startsWith("/coaching/coach") && !p.startsWith("/coaching/coaches"),
    },
  ],
  admin: [
    {
      href: "/admin/coaches",
      label: "Coach reviews",
      Icon: ClipboardCheck,
      match: (p: string) => p.startsWith("/admin/coaches"),
    },
    {
      href: "/admin/coaches#reports",
      label: "Reports",
      Icon: Flag,
      match: () => false,
    },
  ],
};

/** Section links; the active one gets ink text and a 2 px action underline. */
export function SectionNav({ set }: { set: keyof typeof sets }) {
  const path = usePathname();
  return (
    <nav aria-label="Coaching sections" className="-mb-px overflow-x-auto">
      <ul className="flex gap-1 px-2 min-[375px]:px-3 md:px-6">
        {sets[set].map(({ href, label, Icon, match }) => {
          const active = match(path);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={`group relative flex min-h-12 items-center gap-2 whitespace-nowrap rounded-lg px-3 text-[15px] transition-colors duration-150 ease-out ${
                  active
                    ? "font-semibold text-ink"
                    : "text-ink-2 hover:text-ink"
                } ${focus}`}
              >
                {active ? (
                  <span
                    aria-hidden="true"
                    style={{ viewTransitionName: "sh-section-marker" }}
                    className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-action"
                  />
                ) : null}
                <Icon
                  size={18}
                  strokeWidth={2}
                  aria-hidden="true"
                  className="transition-transform duration-150 ease-out group-hover:scale-110"
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
