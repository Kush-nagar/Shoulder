import type { NextRequest } from "next/server";
import { forwardMarketplace } from "../../../../../lib/marketplace";

/** Starts a document upload; returns a presigned PUT. */
export async function POST(request: NextRequest) {
  return forwardMarketplace(request, "/v1/coach-profile/documents", "POST");
}
