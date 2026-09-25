import { LogOut } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { ShoulderMark } from "../../components/brand";
import { fetchTeams } from "../../lib/api";
import { CoachNav, RailLabel, railItem } from "./nav";
import { coachSession } from "./session";
import { focus, metadata } from "./ui";

export const dynamic = "force-dynamic";

const rail =
  "flex items-center gap-3 border-b border-line bg-surface px-4 py-3 md:px-5 lg:fixed lg:inset-y-0 lg:left-0 lg:z-10 lg:w-18 lg:flex-col lg:items-stretch lg:gap-6 lg:overflow-y-auto lg:border-r lg:border-b-0 lg:px-2 lg:py-4 xl:w-54 xl:px-3";

export default async function CoachLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await coachSession();
  const team = session ? (await fetchTeams(session.token))?.[0] : undefined;
  return (
    <div className="min-h-dvh bg-paper text-ink">
      <header className={rail}>
        <Link
          href="/coach"
          aria-label="Shoulder"
          className={`flex h-10 shrink-0 items-center rounded-lg px-2 lg:justify-center xl:justify-start xl:px-3 ${focus}`}
        >
          <ShoulderMark className="size-6" />
        </Link>
        <CoachNav />
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
              className={`${railItem} w-full text-muted hover:bg-surface-subtle hover:text-ink ${focus}`}
            >
              <LogOut size={20} strokeWidth={1.75} aria-hidden="true" />
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
