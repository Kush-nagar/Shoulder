import type { NextRequest } from "next/server";
import { forward } from "../../../../../lib/bff";

const PATH = "/v1/player/leaderboard-membership";

export async function GET(request: NextRequest) {
  return forward(request, PATH, "GET");
}

/** Joins the team board, or changes the nickname, as the signed-in player. */
export async function PUT(request: NextRequest) {
  return forward(request, PATH, "PUT");
}

/** Leaves the team board; the player disappears from it at once. */
export async function DELETE(request: NextRequest) {
  return forward(request, PATH, "DELETE");
}
