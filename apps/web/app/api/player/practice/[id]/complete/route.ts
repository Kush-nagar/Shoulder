import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../../lib/bff";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const id = uuid((await params).id);
  if (!id) return badRequest();
  return forward(request, `/v1/player/practice-videos/${id}/complete`, "POST");
}
