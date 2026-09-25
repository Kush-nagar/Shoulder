import { LogOut } from "lucide-react";
import { headers } from "next/headers";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { type ReactNode, Suspense } from "react";
import { ShoulderMark, ShoulderWordmark } from "../../components/brand";
import { PageTransition, SidebarToggle } from "../../components/shell-client";
import { fetchTeams } from "../../lib/api";
import { verifiedRedirectPath } from "../../lib/auth/policy";
import { sidebarCollapsed } from "../../lib/theme";
import { sideRow, sideTip, tipStyle } from "../player/ui";
import { CoachNav } from "./nav";
import { coachSession } from "./session";
import { focus, metadata } from "./ui";

export const dynamic = "force-dynamic";

/** Team and season stream in; the rail never waits for them. */
async function TeamLabel({
  token,
  variant,
}: {
  token: string;
  variant: "side" | "bar";
}) {
  const team = (await fetchTeams(token))?.[0];
  if (!team) return null;
  // A landmark, not a bare paragraph: below the labelled sidebar this is the
  // only place the current team and season appear.
  return variant === "side" ? (
    <p className={`${metadata} sh-sb-wide px-3 pb-2`}>
      <span className="block truncate font-medium text-ink">{team.name}</span>
      <span className="block truncate">{team.season_label}</span>
    </p>
  ) : (
    <section
      aria-label="Current team"
      className={`${metadata} border-b border-line px-5 py-2 md:px-6 lg:px-8 lg:hidden`}
    >
      {team.name} · {team.season_label}
    </section>
  );
}

/**
 * Coach shell (ADR 0024): the player shell's sidebar geometry, light only.
 * Gating happens here, above every loading boundary, so a signed-out visit
 * still redirects and a non-coach still gets a real 404.
 */
export default async function CoachLayout({
  children,
}: {
  children: ReactNode;
}) {
  const [session, collapsed] = await Promise.all([
    coachSession(),
    sidebarCollapsed(),
  ]);
  if (!session) {
    const next = verifiedRedirectPath((await headers()).get("x-shoulder-path"));
    redirect(
      next ? `/auth/sign-in?next=${encodeURIComponent(next)}` : "/auth/sign-in",
    );
  }
  if (!session.coach) notFound();
  return (
    <div
      data-sidebar={collapsed ? "collapsed" : undefined}
      className="sh-shell sh-animate min-h-dvh bg-paper text-ink"
    >
      <header className="sticky top-0 z-30 flex items-center gap-2 border-b border-line bg-surface px-3 py-2 md:hidden">
        <Link
          href="/coach"
          aria-label="Shoulder"
          className={`flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg ${focus}`}
        >
          <ShoulderMark className="size-7" />
        </Link>
        <CoachNav variant="bar" />
        <form action="/auth/sign-out" method="post">
          <button
            type="submit"
            aria-label="Sign out"
            className={`flex min-h-11 min-w-11 items-center justify-center rounded-lg text-muted hover:bg-surface-subtle hover:text-ink ${focus}`}
          >
            <LogOut size={20} strokeWidth={2} aria-hidden="true" />
          </button>
        </form>
      </header>

      <aside
        aria-label="Coach sections"
        className="sticky top-0 z-30 hidden h-dvh md:block"
      >
        <div className="sh-side-panel flex h-full flex-col border-r border-line bg-surface">
          <Link
            href="/coach"
            aria-label="Shoulder"
            className={`mx-3 mt-3 flex h-20 shrink-0 items-center justify-center rounded-xl ${focus}`}
          >
            <ShoulderMark className="sh-sb-narrow size-10" />
            <ShoulderWordmark
              className="sh-sb-wide h-auto w-[164px]"
              aria-hidden="true"
            />
          </Link>
          <div className="mt-4 px-3">
            <CoachNav variant="side" />
          </div>
          <div className="mt-auto space-y-1 border-t border-line px-3 pt-3 pb-4">
            <Suspense fallback={null}>
              <TeamLabel token={session.token} variant="side" />
            </Suspense>
            <SidebarToggle
              collapsed={collapsed}
              className={`${sideRow} w-full text-muted hover:bg-surface-subtle hover:text-ink`}
              tipClassName={tipStyle}
            />
            <form action="/auth/sign-out" method="post">
              <button
                type="submit"
                aria-label="Sign out"
                className={`${sideRow} w-full text-muted hover:bg-surface-subtle hover:text-ink`}
              >
                <LogOut size={20} strokeWidth={2} aria-hidden="true" />
                <span aria-hidden="true" className="sh-sb-label">
                  Sign out
                </span>
                <span aria-hidden="true" className={sideTip}>
                  Sign out
                </span>
              </button>
            </form>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <Suspense fallback={null}>
          <TeamLabel token={session.token} variant="bar" />
        </Suspense>
        <main className="mx-auto max-w-360">
          <PageTransition>{children}</PageTransition>
        </main>
      </div>
    </div>
  );
}
