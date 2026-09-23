import Link from "next/link";
import type { ReactNode } from "react";
import { ShoulderMark } from "../../components/brand";
import { PlayerNav } from "./player-nav";
import { requirePlayerSession } from "./session";
import { PlayerSignOutForm } from "./sign-out-form";

const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

export const dynamic = "force-dynamic";

export default async function PlayerLayout({
  children,
}: {
  children: ReactNode;
}) {
  await requirePlayerSession();
  return (
    <div className="min-h-dvh bg-paper pt-[env(safe-area-inset-top)] text-ink">
      <header className="h-13 border-b border-line bg-paper">
        <div className="mx-auto flex h-full max-w-140 items-center justify-between px-5 md:px-6">
          <Link
            href="/player"
            aria-label="Shoulder home"
            className={`-ml-2.5 flex min-h-11 min-w-11 items-center justify-center rounded-lg ${focus}`}
          >
            <ShoulderMark className="size-7" />
          </Link>
          <details className="group relative">
            <summary
              aria-label="Account menu"
              className={`flex min-h-11 min-w-11 cursor-pointer list-none items-center justify-center rounded-lg px-3 text-[15px] font-medium text-ink-2 transition-colors duration-150 hover:bg-surface-subtle group-open:bg-surface-subtle [&::-webkit-details-marker]:hidden ${focus}`}
            >
              Menu
            </summary>
            <div className="absolute right-0 z-20 mt-2 w-44 rounded-xl border border-line bg-surface p-1.5 shadow-[0_16px_48px_rgba(23,21,18,.14)]">
              <PlayerSignOutForm />
            </div>
          </details>
        </div>
      </header>
      <main className="mx-auto max-w-140 px-5 pt-8 pb-[calc(6rem+env(safe-area-inset-bottom))] md:px-6 md:pt-10">
        {children}
      </main>
      <PlayerNav />
    </div>
  );
}
