import type { NextRequest } from "next/server";
import { badRequest, uuid } from "../../../../../../../../lib/bff";
import { forwardMarketplace } from "../../../../../../../../lib/marketplace";

/** One short-lived, audited URL for one coach document. */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; docId: string }> },
) {
  const { id, docId } = await params;
  const profile = uuid(id);
  const document = uuid(docId);
  if (!profile || !document) return badRequest();
  return forwardMarketplace(
    request,
    `/v1/admin/coach-reviews/${profile}/documents/${document}/url`,
    "GET",
  );
}
