import "server-only";
import { type NextRequest, NextResponse } from "next/server";
import { forward } from "./bff";

/** Block 10M pilot flag. Off unless exactly "on"; inlined at build time. */
export function marketplaceEnabled(): boolean {
  return process.env.NEXT_PUBLIC_MARKETPLACE_ENABLED === "on";
}

/** `forward`, but the route does not exist while the pilot flag is off. */
export function forwardMarketplace(
  request: NextRequest,
  path: string,
  method: "GET" | "POST" | "PUT" | "DELETE",
): Promise<NextResponse> | NextResponse {
  if (!marketplaceEnabled())
    return NextResponse.json(
      { error: "Not found" },
      { status: 404, headers: { "Cache-Control": "private, no-store" } },
    );
  return forward(request, path, method);
}
