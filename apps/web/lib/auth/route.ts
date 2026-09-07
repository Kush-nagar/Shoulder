import "server-only";
import type { CookieOptions } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";
import { authConfig } from "./policy";
import { cookieName, createAuthClient } from "./server";

export function routeAuth(request: NextRequest) {
  const cacheHeaders = new Headers({
    "Cache-Control": "private, no-store",
    Pragma: "no-cache",
    Expires: "0",
  });
  const updates = new Map<
    string,
    { name: string; value: string; options: CookieOptions }
  >();
  const client = createAuthClient({
    getAll: () => request.cookies.getAll(),
    setAll: (cookies, headers) => {
      for (const [name, value] of Object.entries(headers))
        cacheHeaders.set(name, value);
      for (const cookie of cookies) {
        updates.set(cookie.name, cookie);
        request.cookies.set(cookie.name, cookie.value);
      }
    },
  });
  function finish(response: NextResponse) {
    for (const { name, value, options } of updates.values())
      response.cookies.set(name, value, options);
    cacheHeaders.forEach((value, name) => {
      response.headers.set(name, value);
    });
    response.headers.set("Referrer-Policy", "same-origin");
    return response;
  }
  function clear() {
    for (const { name } of [...request.cookies.getAll(), ...updates.values()]) {
      if (
        name === cookieName ||
        name.startsWith(`${cookieName}.`) ||
        name.startsWith(`${cookieName}-`)
      ) {
        const options: CookieOptions = {
          maxAge: 0,
          path: "/",
          httpOnly: true,
          secure: authConfig(process.env).secure,
          sameSite: "lax",
        };
        updates.set(name, { name, value: "", options });
        request.cookies.delete(name);
      }
    }
  }
  // An unsuccessful new PKCE request must not replace an existing pending flow.
  const discardWrites = () => updates.clear();
  return { client, finish, clear, discardWrites };
}

export function authError(status: number) {
  return NextResponse.json(
    {
      error:
        status === 401
          ? "Authentication required"
          : "Authentication unavailable",
    },
    { status, headers: { "Cache-Control": "private, no-store" } },
  );
}
