import type { NextRequest } from "next/server";
import { badRequest, uuid } from "../../../../../../lib/bff";
import { forwardMarketplace } from "../../../../../../lib/marketplace";

/** Cancels a slot (and its booking, with full refund). */
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const id = uuid((await params).id);
  if (!id) return badRequest();
  return forwardMarketplace(request, `/v1/coach-profile/slots/${id}`, "DELETE");
}
