import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../../lib/bff";

async function path(
  params: Promise<{ judgment_id: string }>,
): Promise<string | null> {
  const judgmentId = uuid((await params).judgment_id);
  return judgmentId ? `/v1/me/judgments/${judgmentId}/reflection` : null;
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ judgment_id: string }> },
) {
  const upstream = await path(params);
  if (!upstream) return badRequest();
  return forward(request, upstream, "PUT");
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ judgment_id: string }> },
) {
  const upstream = await path(params);
  if (!upstream) return badRequest();
  return forward(request, upstream, "DELETE");
}
