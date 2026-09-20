import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../../lib/bff";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ judgment_id: string }> },
) {
  const judgmentId = uuid((await params).judgment_id);
  if (!judgmentId) return badRequest();
  return forward(request, `/v1/me/judgments/${judgmentId}/clip-url`, "POST");
}
