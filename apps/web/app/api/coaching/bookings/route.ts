import type { NextRequest } from "next/server";
import { forwardMarketplace } from "../../../../lib/marketplace";

/** Holds a slot and returns the Stripe Checkout URL. */
export async function POST(request: NextRequest) {
  return forwardMarketplace(request, "/v1/marketplace/bookings", "POST");
}
