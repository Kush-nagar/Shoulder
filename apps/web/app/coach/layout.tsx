import { LogOut } from "lucide-react";
import { headers } from "next/headers";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { type ReactNode, Suspense } from "react";
import { ShoulderMark, ShoulderWordmark } from "../../components/brand";
import { PageTransition, SidebarToggle } from "../../components/shell-client";
import { fetchTeams } from "../../lib/api";
import { verifiedRedirectPath } from "../../lib/auth/policy";
import { savedTheme, sidebarCollapsed, themeAttribute } from "../../lib/theme";
import { sideRow, sideTip, tipStyle } from "../player/ui";
import { CoachNav } from "./nav";
import { coachSession } from "./session";
import { focus } from "./ui";

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
    <div className="sh-sb-label px-2.5 pt-1 pb-3">
      <p className="truncate text-[13px] font-medium text-ink">{team.name}</p>
      <p className="truncate text-[12px] text-muted">{team.season_label}</p>
    </div>
  ) : (
    <section
      aria-label="Current team"
      className="flex items-center gap-2 border-b border-line bg-rail px-4 py-1.5 text-[12px] text-muted md:px-6 lg:hidden"
    >
      <span className="font-medium text-ink-2">{team.name}</span>
      <span>{team.season_label}</span>
    </section>
  );
}

/**
 * Coach shell (ADR 0024, 0026): the player shell's sidebar geometry, dark by
 * default and themed like the rest of the app. Gating happens here, above
 * every loading boundary, so a signed-out visit still redirects and a
 * non-coach still gets a real 404. The review workspace hides this chrome
 * (`.sh-review`, globals.css).
 */
export default async function CoachLayout({
  children,
}: {
  children: ReactNode;
}) {
  const [session, collapsed, theme] = await Promise.all([
    coachSession(),
    sidebarCollapsed(),
    savedTheme(),
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
      data-theme={themeAttribute(theme)}
      data-sidebar={collapsed ? "collapsed" : undefined}
      className="sh-themed sh-shell sh-animate min-h-dvh bg-paper text-ink"
    >
      <aside
        aria-label="Coach sections"
        className="sticky top-0 z-30 hidden h-dvh md:block"
      >
        <div className="sh-side-panel flex h-full flex-col border-r border-line bg-rail">
          <Link
            href="/coach"
            aria-label="Shoulder"
            className={`mx-2.5 mt-2.5 flex h-16 shrink-0 items-center justify-center rounded-lg ${focus}`}
          >
            <ShoulderMark className="sh-sb-narrow size-8 text-ink" />
            <ShoulderWordmark
              className="sh-sb-wide h-auto w-[128px] text-ink"
              aria-hidden="true"
            />
          </Link>
          <div className="mt-3 px-2.5">
            <CoachNav variant="side" />
          </div>
          <div className="mt-auto space-y-0.5 border-t border-line px-2.5 pt-3 pb-3">
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
                <LogOut size={18} strokeWidth={1.75} aria-hidden="true" />
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
        <header className="sticky top-0 z-30 flex items-center gap-1 border-b border-line bg-rail px-2 py-1.5 md:hidden">
          <Link
            href="/coach"
            aria-label="Shoulder"
            className={`flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg ${focus}`}
          >
            <ShoulderMark className="size-7 text-ink" />
          </Link>
          <CoachNav variant="bar" />
          <form action="/auth/sign-out" method="post">
            <button
              type="submit"
              aria-label="Sign out"
              className={`flex min-h-11 min-w-11 items-center justify-center rounded-lg text-muted hover:bg-surface-subtle hover:text-ink ${focus}`}
            >
              <LogOut size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </form>
        </header>
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
