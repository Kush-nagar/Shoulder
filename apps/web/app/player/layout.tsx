import { ChevronRight, CircleUser, Footprints } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { ShoulderMark, ShoulderWordmark } from "../../components/brand";
import { initial } from "./identity";
import { BottomTabs, SideNav, TopBarTitle } from "./player-nav";
import { savedTheme, themeAttribute } from "../../lib/theme";
import { requirePlayerSession } from "./session";
import { PlayerSignOutForm } from "./sign-out-form";
import { focus, primaryButton } from "./ui";

export const dynamic = "force-dynamic";

function Avatar({
  letter,
  size = "size-9",
}: {
  letter: string;
  size?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={`${size} flex shrink-0 items-center justify-center rounded-full bg-ink text-[15px] font-semibold text-paper`}
    >
      {letter}
    </span>
  );
}

/**
 * Responsive player shell (ADR 0022): bottom tabs below 768 px, an 88 px rail
 * from 768 px, and a 240 px sidebar from 1024 px. Same four destinations.
 */
export default async function PlayerLayout({
  children,
}: {
  children: ReactNode;
}) {
  const { me } = await requirePlayerSession();
  const letter = initial(me.display_name);
  const theme = themeAttribute(await savedTheme());
  return (
    <div
      data-theme={theme}
      className="sh-themed min-h-dvh bg-paper text-ink md:grid md:grid-cols-[88px_minmax(0,1fr)] lg:grid-cols-[240px_minmax(0,1fr)]"
    >
      <aside
        aria-label="Shoulder sections"
        className="sticky top-0 hidden h-dvh flex-col border-r border-line pt-[env(safe-area-inset-top)] md:flex"
      >
        <Link
          href="/player"
          aria-label="Shoulder home"
          className={`mx-auto mt-5 mb-6 flex min-h-11 min-w-11 items-center justify-center rounded-lg lg:mx-5 lg:justify-start ${focus}`}
        >
          <ShoulderMark className="size-7 lg:hidden" aria-hidden="true" />
          <ShoulderWordmark
            className="hidden h-auto w-28 lg:block"
            aria-hidden="true"
          />
        </Link>
        <SideNav />
        <div className="mt-6 hidden px-5 lg:block">
          <Link
            href="/player/practice/new"
            className={`${primaryButton} w-full`}
          >
            <Footprints size={20} strokeWidth={2} aria-hidden="true" />
            Film practice
          </Link>
        </div>
        <Link
          href="/player/profile"
          aria-label="Profile and settings"
          className={`mt-auto mb-4 flex min-h-14 items-center justify-center gap-3 rounded-lg px-2 hover:bg-surface-subtle lg:mx-3 lg:justify-start ${focus}`}
        >
          <Avatar letter={letter} />
          <span className="hidden min-w-0 flex-1 lg:block">
            <span className="block truncate text-[15px] font-semibold">
              {me.display_name}
            </span>
            <span className="block truncate text-[13px] text-muted">
              {me.email}
            </span>
          </span>
          <ChevronRight
            size={18}
            strokeWidth={2}
            aria-hidden="true"
            className="hidden shrink-0 text-muted lg:block"
          />
        </Link>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 border-b border-line bg-paper pt-[env(safe-area-inset-top)] md:hidden">
          <div className="flex h-14 items-center gap-2 px-2 min-[375px]:px-3">
            <Link
              href="/player"
              aria-label="Shoulder home"
              className={`flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-lg ${focus}`}
            >
              <ShoulderMark className="size-7" aria-hidden="true" />
            </Link>
            <div className="min-w-0 flex-1">
              <TopBarTitle />
            </div>
            <details className="group relative">
              <summary
                aria-label="Account menu"
                className={`flex min-h-11 min-w-11 cursor-pointer list-none items-center justify-center rounded-full [&::-webkit-details-marker]:hidden ${focus}`}
              >
                <Avatar letter={letter} />
              </summary>
              <div className="absolute right-0 z-30 mt-2 w-[min(18rem,calc(100vw-1.5rem))] rounded-xl border border-line bg-surface p-2 shadow-[0_16px_48px_rgba(23,21,18,.14)]">
                <div className="px-3 pt-2 pb-3">
                  <p className="truncate text-[16px] font-semibold">
                    {me.display_name}
                  </p>
                  <p className="truncate text-[13px] text-muted">{me.email}</p>
                </div>
                <Link
                  href="/player/profile"
                  className={`flex min-h-11 items-center gap-3 rounded-lg px-3 text-[16px] hover:bg-surface-subtle ${focus}`}
                >
                  <CircleUser size={20} strokeWidth={2} aria-hidden="true" />
                  Profile and settings
                </Link>
                <PlayerSignOutForm />
              </div>
            </details>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1200px] px-4 pt-6 pb-[calc(64px+env(safe-area-inset-bottom)+32px)] min-[375px]:px-5 md:px-8 md:pt-10 md:pb-16">
          {children}
        </main>
      </div>
      <BottomTabs />
    </div>
  );
}
