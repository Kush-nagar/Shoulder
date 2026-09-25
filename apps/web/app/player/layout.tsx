import type { ReactNode } from "react";
import { PlayerChrome } from "./chrome";
import { requirePlayerSession } from "./session";

export const dynamic = "force-dynamic";

export default async function PlayerLayout({
  children,
}: {
  children: ReactNode;
}) {
  const { me } = await requirePlayerSession();
  return <PlayerChrome me={me}>{children}</PlayerChrome>;
}
