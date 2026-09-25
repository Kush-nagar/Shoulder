import "server-only";
import { cookies } from "next/headers";

export type ThemeChoice = "system" | "light" | "dark";

/**
 * Saved appearance (ADR 0022). Read on the server and rendered as
 * `data-theme` on the themed wrapper, so there is no flash and no inline
 * script; "system" leaves it to `prefers-color-scheme`.
 */
export async function savedTheme(): Promise<ThemeChoice> {
  const value = (await cookies()).get("sh-theme")?.value;
  return value === "light" || value === "dark" ? value : "system";
}

export function themeAttribute(theme: ThemeChoice) {
  return theme === "system" ? undefined : theme;
}

/** Desktop sidebar state (ADR 0024), read on the server so SSR never flashes. */
export async function sidebarCollapsed(): Promise<boolean> {
  return (await cookies()).get("sh-sidebar")?.value === "collapsed";
}
