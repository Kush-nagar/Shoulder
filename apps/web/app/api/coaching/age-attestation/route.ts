import type { NextRequest } from "next/server";
import { forwardMarketplace } from "../../../../lib/marketplace";

/** Records the adult age attestation (birth year only). */
export async function PUT(request: NextRequest) {
  return forwardMarketplace(request, "/v1/me/age-attestation", "PUT");
}
