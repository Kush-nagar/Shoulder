import Link from "next/link";
import type { ReactNode } from "react";
import { ShoulderMark } from "../../components/brand";
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
    <div className="min-h-dvh bg-paper pb-[env(safe-area-inset-bottom)] text-ink">
      <header className="h-13 border-b border-line bg-paper">
        <div className="mx-auto flex h-full max-w-140 items-center justify-between px-5 md:px-6">
          <Link
            href="/player"
            aria-label="Shoulder home"
            className={`flex min-h-11 min-w-11 items-center gap-2 rounded-lg text-[17px] font-semibold ${focus}`}
          >
            <ShoulderMark className="size-6" />
            <span>Your clips</span>
          </Link>
          <details className="relative">
            <summary
              aria-label="Account menu"
              className={`flex min-h-11 min-w-11 cursor-pointer list-none items-center justify-center rounded-lg border border-line text-[14px] font-semibold [&::-webkit-details-marker]:hidden ${focus}`}
            >
              Menu
            </summary>
            <div className="absolute right-0 z-20 mt-2 w-36 rounded-xl border border-line bg-surface p-2">
              <Link
                href="/player/progress"
                className={`flex min-h-11 items-center rounded-lg px-3 text-[16px] hover:bg-surface-subtle ${focus}`}
              >
                Reflections
              </Link>
              <PlayerSignOutForm />
            </div>
          </details>
        </div>
      </header>
      <main className="mx-auto max-w-140 px-5 py-8 md:px-6 md:py-10">
        {children}
      </main>
    </div>
  );
}
