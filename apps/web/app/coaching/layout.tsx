import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { marketplaceEnabled } from "../../lib/marketplace";
import { PlayerChrome } from "../player/chrome";
import { playerMe } from "./server";
import { CoachingSubheader, MarketplaceShell } from "./shell";

export const dynamic = "force-dynamic";

/** Players keep their app chrome here; any other adult gets the plain shell. */
export default async function CoachingLayout({
  children,
}: {
  children: ReactNode;
}) {
  if (!marketplaceEnabled()) notFound();
  const me = await playerMe();
  if (me)
    return (
      <PlayerChrome me={me}>
        <CoachingSubheader />
        {children}
      </PlayerChrome>
    );
  return (
    <MarketplaceShell set="coaching" title="Coaching">
      {children}
    </MarketplaceShell>
  );
}
