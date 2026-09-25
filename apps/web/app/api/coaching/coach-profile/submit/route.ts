import type { NextRequest } from "next/server";
import { forwardMarketplace } from "../../../../../lib/marketplace";

/** Sends the profile for admin review. */
export async function POST(request: NextRequest) {
  return forwardMarketplace(request, "/v1/coach-profile/submit", "POST");
}
