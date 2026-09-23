import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../../lib/bff";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const id = uuid((await params).id);
  if (!id) return badRequest();
  return forward(
    request,
    `/v1/player/practice-videos/${id}/ai-feedback`,
    "GET",
  );
}

/** Body is the on-device features JSON; FastAPI validates its size and shape. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const id = uuid((await params).id);
  if (!id) return badRequest();
  return forward(
    request,
    `/v1/player/practice-videos/${id}/ai-feedback`,
    "POST",
  );
}
