import type { NextRequest } from "next/server";
import { badRequest, uuid } from "../../../../../../lib/bff";
import { forwardMarketplace } from "../../../../../../lib/marketplace";

/** Admin resolves a report. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const id = uuid((await params).id);
  if (!id) return badRequest();
  return forwardMarketplace(request, `/v1/admin/reports/${id}/resolve`, "POST");
}
