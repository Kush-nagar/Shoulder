"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * A 2 px signal line at the top of the viewport while an in-app navigation
 * is pending. It starts on a same-origin link click and finishes when the
 * pathname changes; skeletons from `loading.tsx` take over below it.
 * ponytail: link clicks only; form/router.push navigations show no bar.
 */
export function RouteProgress() {
  const path = usePathname();
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const link = (event.target as Element | null)?.closest?.("a[href]");
      if (!(link instanceof HTMLAnchorElement)) return;
      if (link.target && link.target !== "_self") return;
      if (link.hasAttribute("download")) return;
      const url = new URL(link.href, location.href);
      if (url.origin !== location.origin) return;
      // Search-only changes keep the pathname, so they would never finish.
      if (url.pathname === location.pathname) return;
      setState("busy");
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: finish on every pathname change.
  useEffect(() => {
    setState((s) => (s === "busy" ? "done" : s));
    const id = window.setTimeout(() => setState("idle"), 450);
    return () => window.clearTimeout(id);
  }, [path]);

  // A link that never changes the route (a file download) must not stick.
  useEffect(() => {
    if (state !== "busy") return;
    const id = window.setTimeout(() => setState("idle"), 10000);
    return () => window.clearTimeout(id);
  }, [state]);

  return <div aria-hidden="true" className="sh-progress" data-state={state} />;
}
