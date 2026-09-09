import Link from "next/link";
import type { ReactNode } from "react";
import { ShoulderMark } from "../../components/brand";
import { fetchTeams } from "../../lib/api";
import { coachSession } from "./session";
import { focus, metadata } from "./ui";

export const dynamic = "force-dynamic";

const rail =
  "flex items-center gap-3 border-b border-line bg-paper px-5 py-3 lg:fixed lg:inset-y-0 lg:left-0 lg:z-10 lg:w-18 lg:flex-col lg:items-stretch lg:gap-6 lg:overflow-y-auto lg:border-r lg:border-b-0 lg:px-2 lg:py-4 xl:w-54 xl:px-3";

const item =
  "group relative flex h-10 items-center gap-3 rounded-lg px-3 text-[15px] font-medium transition-colors duration-140 lg:justify-center xl:justify-start";

/** Between 1024px and 1280px the rail is icon-only, so the label is a tooltip. */
function RailLabel({ children }: { children: string }) {
  return (
    <>
      <span aria-hidden="true" className="lg:hidden xl:inline">
        {children}
      </span>
      <span
        aria-hidden="true"
        className="pointer-events-none invisible absolute left-full z-20 ml-2 hidden whitespace-nowrap rounded-lg border border-line bg-white px-3 py-1 text-[13px] font-normal text-ink lg:block lg:group-hover:visible lg:group-focus-visible:visible xl:hidden"
      >
        {children}
      </span>
    </>
  );
}

const iconProps = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  width: 20,
  height: 20,
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  focusable: false,
} as const;

function ListIcon() {
  return (
    <svg {...iconProps} aria-hidden="true" role="presentation">
      <path d="M4 6.5h16M4 12h16M4 17.5h16" />
    </svg>
  );
}

function PeopleIcon() {
  return (
    <svg {...iconProps} aria-hidden="true" role="presentation">
      <path d="M9 11a3.25 3.25 0 1 0 0-6.5A3.25 3.25 0 0 0 9 11Z" />
      <path d="M2.75 19.25a6.25 6.25 0 0 1 12.5 0" />
      <path d="M16 5.25a3.25 3.25 0 0 1 0 6.5M17.25 14.5a6.25 6.25 0 0 1 4 4.75" />
    </svg>
  );
}

function ExitIcon() {
  return (
    <svg {...iconProps} aria-hidden="true" role="presentation">
      <path d="M14.5 4.75H6.75A1.75 1.75 0 0 0 5 6.5v11a1.75 1.75 0 0 0 1.75 1.75h7.75" />
      <path d="M17 8.5 20.5 12 17 15.5M20 12h-9" />
    </svg>
  );
}

export default async function CoachLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await coachSession();
  const team = session ? (await fetchTeams(session.token))[0] : undefined;
  return (
    <div className="min-h-dvh">
      <header className={rail}>
        <Link
          href="/coach/roster"
          aria-label="Shoulder"
          className={`flex h-10 shrink-0 items-center rounded-lg px-3 lg:justify-center xl:justify-start ${focus}`}
        >
          <ShoulderMark className="size-6" />
        </Link>
        <nav
          aria-label="Coach"
          className="flex flex-1 items-center gap-1 lg:flex-none lg:flex-col lg:items-stretch"
        >
          <button
            type="button"
            disabled
            aria-label="Dashboard"
            title="Coming soon"
            className={`${item} cursor-not-allowed text-muted opacity-70`}
          >
            <ListIcon />
            <RailLabel>Dashboard</RailLabel>
          </button>
          {/* ponytail: every live page in this block sits under Players, so the
              current section is static. Read the pathname when /coach grows. */}
          <Link
            href="/coach/roster"
            aria-label="Players"
            aria-current="page"
            className={`${item} bg-line/50 text-ink hover:bg-line ${focus}`}
          >
            <PeopleIcon />
            <RailLabel>Players</RailLabel>
          </Link>
        </nav>
        <div className="flex items-center gap-3 lg:mt-auto lg:flex-col lg:items-stretch lg:gap-3 lg:border-t lg:border-line lg:pt-4">
          {team ? (
            <p className={`${metadata} hidden xl:block xl:px-3`}>
              <span className="block font-medium text-ink">{team.name}</span>
              <span className="block">{team.season_label}</span>
            </p>
          ) : null}
          <form action="/auth/sign-out" method="post">
            <button
              type="submit"
              aria-label="Sign out"
              className={`${item} w-full text-muted hover:text-ink ${focus}`}
            >
              <ExitIcon />
              <RailLabel>Sign out</RailLabel>
            </button>
          </form>
        </div>
      </header>
      <div className="lg:ml-18 xl:ml-54">
        {/* A landmark, not a bare paragraph: below the labelled rail this is
            the only place the current team and season appear. */}
        {team ? (
          <section
            aria-label="Current team"
            className={`${metadata} border-b border-line px-5 py-2 md:px-6 lg:px-8 xl:hidden`}
          >
            {team.name} · {team.season_label}
          </section>
        ) : null}
        <main className="mx-auto max-w-360">{children}</main>
      </div>
    </div>
  );
}
