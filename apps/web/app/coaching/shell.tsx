import { ArrowLeft, Info } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { ShoulderMark } from "../../components/brand";
import { savedTheme, themeAttribute } from "../../lib/theme";
import { focus } from "../player/ui";
import { SectionNav } from "./nav";

/**
 * Marketplace shell: its own top bar because any adult account may land here,
 * player or not. Themes like the player app (ADR 0022). The pilot note is
 * always visible: adults only, Stripe test mode.
 */
export async function MarketplaceShell({
  set,
  title,
  children,
}: {
  set: "coaching" | "admin";
  title: string;
  children: ReactNode;
}) {
  const theme = themeAttribute(await savedTheme());
  return (
    <div data-theme={theme} className="sh-themed min-h-dvh bg-paper text-ink">
      <header className="sticky top-0 z-20 border-b border-line bg-paper pt-[env(safe-area-inset-top)]">
        <div className="mx-auto flex h-14 max-w-[1200px] items-center gap-2 px-2 min-[375px]:px-3 md:h-16 md:px-6">
          <Link
            href="/"
            aria-label="Back to Shoulder"
            className={`flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-lg text-ink-2 hover:text-ink ${focus}`}
          >
            <ArrowLeft size={18} strokeWidth={2} aria-hidden="true" />
            <ShoulderMark className="size-7 text-ink" aria-hidden="true" />
          </Link>
          <p className="font-display text-[22px] leading-none md:text-[24px]">
            {title}
          </p>
          <p className="ml-auto hidden items-center gap-2 text-[13px] leading-[1.4] text-muted md:flex">
            <Info size={16} strokeWidth={2} aria-hidden="true" />
            Adults-only pilot. Payments run in Stripe test mode.
          </p>
        </div>
        <div className="mx-auto max-w-[1200px]">
          <SectionNav set={set} />
        </div>
      </header>
      <p className="flex items-start gap-2 border-b border-line bg-surface-subtle px-4 py-2.5 text-[14px] leading-5 text-ink-2 min-[375px]:px-5 md:hidden">
        <Info
          size={16}
          strokeWidth={2}
          aria-hidden="true"
          className="mt-0.5 shrink-0"
        />
        Adults-only pilot. Payments run in Stripe test mode, so no real money
        moves.
      </p>
      <main className="mx-auto w-full max-w-[1200px] px-4 pt-6 pb-16 min-[375px]:px-5 md:px-8 md:pt-10">
        {children}
      </main>
    </div>
  );
}

/** Pilot note and section links when `/coaching` sits in the player shell. */
export function CoachingSubheader() {
  return (
    <div className="-mt-2 mb-6 md:-mt-4 md:mb-8">
      <p className="flex items-start gap-2 text-[14px] leading-5 text-muted">
        <Info
          size={16}
          strokeWidth={2}
          aria-hidden="true"
          className="mt-0.5 shrink-0"
        />
        Adults-only pilot. Payments run in Stripe test mode, so no real money
        moves.
      </p>
      <div className="-mx-4 mt-2 border-b border-line min-[375px]:-mx-5 md:-mx-6">
        <SectionNav set="coaching" />
      </div>
    </div>
  );
}
