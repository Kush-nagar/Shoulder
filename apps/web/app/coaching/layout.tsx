import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { marketplaceEnabled } from "../../lib/marketplace";
import { MarketplaceShell } from "./shell";

export const dynamic = "force-dynamic";

export default function CoachingLayout({ children }: { children: ReactNode }) {
  if (!marketplaceEnabled()) notFound();
  return (
    <MarketplaceShell set="coaching" title="Coaching">
      {children}
    </MarketplaceShell>
  );
}
