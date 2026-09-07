import { type NextRequest, NextResponse } from "next/server";
import { authConfig } from "../../../../lib/auth/policy";
import { authError, routeAuth } from "../../../../lib/auth/route";
import { verifiedToken } from "../../../../lib/auth/server";

export async function GET(request: NextRequest) {
  const auth = routeAuth(request);
  try {
    const token = await verifiedToken(auth.client);
    if (!token) {
      auth.clear();
      return auth.finish(authError(401));
    }
    const upstream = await fetch(
      `${authConfig(process.env).apiUrl}/v1/auth/identity`,
      {
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(5000),
      },
    );
    if (!upstream.ok)
      return auth.finish(authError(upstream.status === 401 ? 401 : 503));
    return auth.finish(NextResponse.json(await upstream.json()));
  } catch {
    return auth.finish(authError(503));
  }
}
