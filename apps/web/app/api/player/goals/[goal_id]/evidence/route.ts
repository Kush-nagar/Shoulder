import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../../lib/bff";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ goal_id: string }> },
) {
  const goalId = uuid((await params).goal_id);
  if (!goalId) return badRequest();
  return forward(request, `/v1/me/goals/${goalId}/evidence`, "GET");
}
