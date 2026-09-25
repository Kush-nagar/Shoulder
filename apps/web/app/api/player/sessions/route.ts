import type { NextRequest } from "next/server";
import { forward } from "../../../../lib/bff";

export async function GET(request: NextRequest) {
  return forward(request, "/v1/player/sessions", "GET");
}

/** Saves one finished session: aggregates only, never coordinates. */
export async function POST(request: NextRequest) {
  return forward(request, "/v1/player/sessions", "POST");
}
