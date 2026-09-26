"use client";

import { useSyncExternalStore } from "react";
import { problemSlug } from "./format";

/** JSON call to a same-origin marketplace BFF route. Status 0 = offline. */
export async function send<T>(
  path: string,
  method: "GET" | "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<{ status: number; data: T | null; problem: string | null }> {
  try {
    const response = await fetch(path, {
      method,
      cache: "no-store",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const json: unknown = await response.json().catch(() => null);
    return response.ok
      ? { status: response.status, data: json as T | null, problem: null }
      : { status: response.status, data: null, problem: problemSlug(json) };
  } catch {
    return { status: 0, data: null, problem: null };
  }
}

const noop = () => () => {};

/**
 * False during the server render and hydration, true after. Times are shown in
 * the viewer's own time zone, which only the browser knows.
 */
export function useInBrowser(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
}

export function dayKey(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export const dayLabel = (iso: string) =>
  new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  }).format(new Date(iso));

export const timeLabel = (iso: string) =>
  new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));

export const dateTimeLabel = (iso: string) =>
  new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));

/** Day-picker parts: "Tue", "29", "Sep". */
export const dayParts = (iso: string) => {
  const d = new Date(iso);
  const f = (o: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat(undefined, o).format(d);
  return {
    weekday: f({ weekday: "short" }),
    day: f({ day: "numeric" }),
    month: f({ month: "short" }),
  };
};

/** Server-rendered pages drop this in wherever a session time appears. */
export function When({ iso, className }: { iso: string; className?: string }) {
  const ready = useInBrowser();
  return (
    <time dateTime={iso} className={className}>
      {ready ? dateTimeLabel(iso) : " "}
    </time>
  );
}
