import "server-only";
import { type NextRequest, NextResponse } from "next/server";
import { authConfig, validOrigin } from "./auth/policy";
import { authError, routeAuth } from "./auth/route";
import { verifiedToken } from "./auth/server";

/**
 * Forward one same-origin browser call to a fixed FastAPI path.
 *
 * The upload screen is the first client component that has to talk to the API
 * while a page is open, so it needs JSON routes rather than server actions.
 * Each route names its upstream path literally: there is no pass-through
 * proxy, because a caller must never be able to choose which `/v1` endpoint
 * the session token reaches.
 *
 * The upstream problem document is returned as-is. It is already the sanitized
 * RFC 9457 body `services/api/problems.py` produces, and the client needs its
 * `type` slug to tell "this upload is closed" from "storage is unavailable".
 */
export async function forward(
  request: NextRequest,
  path: string,
  method: "GET" | "POST" | "PATCH",
): Promise<NextResponse> {
  const auth = routeAuth(request);
  const config = authConfig(process.env);
  // A state-changing same-origin route needs origin and host validation on top
  // of the SameSite cookie, per `docs/10-security-privacy.md`.
  if (method !== "GET" && !validOrigin(request.headers, config.origin))
    return auth.finish(authError(403));
  try {
    const token = await verifiedToken(auth.client);
    if (!token) {
      auth.clear();
      return auth.finish(authError(401));
    }
    const body = method === "GET" ? undefined : await request.text();
    const upstream = await fetch(`${config.apiUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(request.headers.get("If-Match")
          ? { "If-Match": request.headers.get("If-Match") as string }
          : {}),
      },
      body: body || undefined,
      cache: "no-store",
      redirect: "error",
      // Completion asks storage to assemble the object, which takes longer
      // than an ordinary JSON call.
      signal: AbortSignal.timeout(60_000),
    });
    const text = await upstream.text();
    return auth.finish(
      new NextResponse(text || null, {
        status: upstream.status,
        headers: {
          "Content-Type":
            upstream.headers.get("content-type") ?? "application/json",
          "Cache-Control": "private, no-store",
          ...(upstream.headers.get("etag")
            ? { ETag: upstream.headers.get("etag") as string }
            : {}),
        },
      }) as NextResponse,
    );
  } catch {
    return auth.finish(authError(503));
  }
}

/** Route-segment ids are UUIDs; anything else never reaches the API. */
export function uuid(value: string): string | null {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value,
  )
    ? value
    : null;
}

export function badRequest(): NextResponse {
  return NextResponse.json(
    { error: "Bad request" },
    { status: 400, headers: { "Cache-Control": "private, no-store" } },
  );
}
