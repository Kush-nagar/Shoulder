import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../../lib/bff";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ game_id: string }> },
) {
  const gameId = uuid((await params).game_id);
  if (!gameId) return badRequest();
  return forward(request, `/v1/games/${gameId}/videos/uploads`, "POST");
}
