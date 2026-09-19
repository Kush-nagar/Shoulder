import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../lib/bff";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ observation_id: string }> },
) {
  const observationId = uuid((await params).observation_id);
  if (!observationId) return badRequest();
  return forward(request, `/v1/observations/${observationId}/judgment`, "GET");
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ observation_id: string }> },
) {
  const observationId = uuid((await params).observation_id);
  if (!observationId) return badRequest();
  return forward(
    request,
    `/v1/observations/${observationId}/judgments`,
    "POST",
  );
}
