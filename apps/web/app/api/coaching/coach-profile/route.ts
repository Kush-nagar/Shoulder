import type { NextRequest } from "next/server";
import { forwardMarketplace } from "../../../../lib/marketplace";

/** Creates or updates the caller's coach profile. */
export async function PUT(request: NextRequest) {
  return forwardMarketplace(request, "/v1/coach-profile", "PUT");
}
