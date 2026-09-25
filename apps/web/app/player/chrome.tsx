import { ChevronRight, CircleUser, Handshake, Video } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { ShoulderMark, ShoulderWordmark } from "../../components/brand";
import {
  AccountSheet,
  PageTransition,
  SidebarToggle,
} from "../../components/shell-client";
import type { Me } from "../../lib/api";
import { marketplaceEnabled } from "../../lib/marketplace";
import { savedTheme, sidebarCollapsed, themeAttribute } from "../../lib/theme";
import { initial } from "./identity";
import { BottomTabs, SideNav, TopBarTitle } from "./player-nav";
import { PlayerSignOutForm } from "./sign-out-form";
import { focus, sideRow, sideTip, tipStyle } from "./ui";

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

const sheetRow = `flex min-h-12 items-center gap-3 rounded-lg px-3 text-[16px] hover:bg-surface-subtle ${focus}`;

/**
 * Responsive player shell (ADR 0022, 0023): bottom tabs below 768 px, an icon
 * rail from 768 px that opens as an overlay, and a 248 px sidebar from
 * 1024 px that collapses to the rail. Shared with `/coaching`.
 */
export async function PlayerChrome({
  me,
  children,
}: {
  me: Pick<Me, "display_name" | "email">;
  children: ReactNode;
}) {
  const letter = initial(me.display_name);
  const [theme, collapsed] = await Promise.all([
    savedTheme(),
    sidebarCollapsed(),
  ]);
  return (
    <div
      data-theme={themeAttribute(theme)}
      data-sidebar={collapsed ? "collapsed" : undefined}
      className="sh-themed sh-shell sh-animate min-h-dvh bg-paper text-ink"
    >
      <aside
        aria-label="Shoulder sections"
        className="sticky top-0 z-30 hidden h-dvh md:block"
      >
        <div className="sh-side-panel flex h-full flex-col border-r border-line bg-paper pt-[env(safe-area-inset-top)]">
          <Link
            href="/player"
            aria-label="Shoulder home"
            className={`mx-3 mt-3 flex h-20 shrink-0 items-center justify-center rounded-xl ${focus}`}
          >
            <ShoulderMark
              className="sh-sb-narrow size-10 text-ink"
              aria-hidden="true"
            />
            <ShoulderWordmark
              className="sh-sb-wide h-auto w-[164px] text-ink"
              aria-hidden="true"
            />
          </Link>
          <div className="mt-4">
            <SideNav />
          </div>
          <div className="mt-5 px-3">
            <Link
              href="/player/practice/new"
              className={`${sideRow} bg-action font-semibold text-on-action hover:bg-action-hover active:scale-[0.98]`}
            >
              <Video size={20} strokeWidth={2} aria-hidden="true" />
              <span className="sh-sb-label">Film practice</span>
              <span aria-hidden="true" className={sideTip}>
                Film practice
              </span>
            </Link>
          </div>
          <div className="mt-auto space-y-1 px-3 pb-4">
            <SidebarToggle
              collapsed={collapsed}
              className={`${sideRow} w-full text-muted hover:bg-surface-subtle hover:text-ink`}
              tipClassName={tipStyle}
            />
            <Link
              href="/player/profile"
              aria-label="Profile and settings"
              className={`${sideRow} h-14 hover:bg-surface-subtle`}
            >
              <Avatar letter={letter} />
              <span className="sh-sb-label min-w-0 flex-1">
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
                className="sh-sb-wide shrink-0 text-muted"
              />
              <span aria-hidden="true" className={sideTip}>
                Profile and settings
              </span>
            </Link>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 border-b border-line bg-paper/95 pt-[env(safe-area-inset-top)] md:hidden">
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
            <AccountSheet trigger={<Avatar letter={letter} />}>
              <div className="flex items-center gap-3 px-3 pt-1 pb-3">
                <Avatar letter={letter} size="size-11" />
                <div className="min-w-0">
                  <p className="truncate text-[16px] font-semibold">
                    {me.display_name}
                  </p>
                  <p className="truncate text-[13px] text-muted">{me.email}</p>
                </div>
              </div>
              <Link href="/player/profile" className={sheetRow}>
                <CircleUser size={20} strokeWidth={2} aria-hidden="true" />
                Profile and settings
              </Link>
              {marketplaceEnabled() ? (
                <Link href="/coaching" className={sheetRow}>
                  <Handshake size={20} strokeWidth={2} aria-hidden="true" />
                  Coaching
                </Link>
              ) : null}
              <PlayerSignOutForm className="min-h-12" />
            </AccountSheet>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1200px] px-4 pt-6 pb-[calc(64px+env(safe-area-inset-bottom)+32px)] min-[375px]:px-5 md:px-8 md:pt-10 md:pb-16">
          <PageTransition>{children}</PageTransition>
        </main>
      </div>
      <BottomTabs />
    </div>
  );
}
