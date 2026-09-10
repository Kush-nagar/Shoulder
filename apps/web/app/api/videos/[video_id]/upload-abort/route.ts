import type { NextRequest } from "next/server";
import { badRequest, forward, uuid } from "../../../../../lib/bff";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ video_id: string }> },
) {
  const videoId = uuid((await params).video_id);
  if (!videoId) return badRequest();
  return forward(request, `/v1/videos/${videoId}/upload-abort`, "POST");
}
