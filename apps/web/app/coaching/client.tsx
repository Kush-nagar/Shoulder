"use client";

import { useSyncExternalStore } from "react";

/** JSON call to a same-origin marketplace BFF route. Status 0 = offline. */
export async function send<T>(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body?: unknown,
): Promise<{ status: number; data: T | null }> {
  try {
    const response = await fetch(path, {
      method,
      cache: "no-store",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = response.ok
      ? ((await response.json().catch(() => null)) as T | null)
      : null;
    return { status: response.status, data };
  } catch {
    return { status: 0, data: null };
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

/** Server-rendered pages drop this in wherever a session time appears. */
export function When({ iso, className }: { iso: string; className?: string }) {
  const ready = useInBrowser();
  return (
    <time dateTime={iso} className={className}>
      {ready ? dateTimeLabel(iso) : " "}
    </time>
  );
}
