import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { marketplaceEnabled } from "../../lib/marketplace";
import { MarketplaceShell } from "../coaching/shell";

export const dynamic = "force-dynamic";

/** Platform-admin pages. The API is the authority; 403/404 renders not-found. */
export default function AdminLayout({ children }: { children: ReactNode }) {
  if (!marketplaceEnabled()) notFound();
  return (
    <MarketplaceShell set="admin" title="Admin">
      {children}
    </MarketplaceShell>
  );
}
