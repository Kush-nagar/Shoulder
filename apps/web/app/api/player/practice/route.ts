import type { NextRequest } from "next/server";
import { forward } from "../../../../lib/bff";

export async function GET(request: NextRequest) {
  return forward(request, "/v1/player/practice-videos", "GET");
}

/** Starts an upload; the reply carries one presigned PUT for the browser. */
export async function POST(request: NextRequest) {
  return forward(request, "/v1/player/practice-videos", "POST");
}
