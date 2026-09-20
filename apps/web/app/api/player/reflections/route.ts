import type { NextRequest } from "next/server";
import { forward } from "../../../../lib/bff";

export async function GET(request: NextRequest) {
  return forward(request, "/v1/me/reflections", "GET");
}
