import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../lib/bff";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const id = uuid((await params).id);
  if (!id) return badRequest();
  return forward(request, `/v1/player/sessions/${id}`, "GET");
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const id = uuid((await params).id);
  if (!id) return badRequest();
  return forward(request, `/v1/player/sessions/${id}`, "DELETE");
}
