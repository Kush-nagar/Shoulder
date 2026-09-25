"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { usePathname } from "next/navigation";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
  ViewTransition,
} from "react";

const WIDE = "(min-width: 1024px)";

function shell() {
  return document.querySelector<HTMLElement>(".sh-shell");
}

function typing(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
  );
}

/**
 * Collapse/expand for the app-shell sidebar (ADR 0024). From 1024 px it
 * collapses the sidebar to an icon rail and remembers that in the
 * `sh-sidebar` cookie, so the server renders the same state next time. On the
 * 768 to 1023 px rail it opens a labelled overlay with a scrim instead. `[`
 * toggles it from anywhere outside a text field, as in Linear.
 */
export function SidebarToggle({
  collapsed: initialCollapsed,
  className = "",
  tipClassName = "",
}: {
  collapsed: boolean;
  className?: string;
  tipClassName?: string;
}) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [railOpen, setRailOpen] = useState(false);
  const [wide, setWide] = useState(false);
  const path = usePathname();

  useEffect(() => {
    const query = window.matchMedia(WIDE);
    const update = () => {
      setWide(query.matches);
      if (query.matches) setRailOpen(false);
    };
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const root = shell();
    if (!root) return;
    if (collapsed) root.dataset.sidebar = "collapsed";
    else delete root.dataset.sidebar;
    // biome-ignore lint/suspicious/noDocumentCookie: Cookie Store API is missing in Safari and Firefox; this cookie is a non-sensitive preference.
    document.cookie = collapsed
      ? "sh-sidebar=collapsed; path=/; max-age=31536000; samesite=lax"
      : "sh-sidebar=; path=/; max-age=0; samesite=lax";
  }, [collapsed]);

  useEffect(() => {
    const root = shell();
    if (!root) return;
    if (railOpen) root.dataset.rail = "open";
    else delete root.dataset.rail;
  }, [railOpen]);

  // A destination was chosen: the overlay has done its job.
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs on route change only.
  useEffect(() => setRailOpen(false), [path]);

  const toggle = useCallback(() => {
    if (window.matchMedia(WIDE).matches) setCollapsed((value) => !value);
    else setRailOpen((value) => !value);
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && shell()?.dataset.rail === "open") {
        setRailOpen(false);
        return;
      }
      if (
        event.key !== "[" ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        typing(event.target) ||
        !window.matchMedia("(min-width: 768px)").matches
      )
        return;
      event.preventDefault();
      toggle();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [toggle]);

  const expanded = wide ? !collapsed : railOpen;
  const label = expanded ? "Collapse sidebar" : "Expand sidebar";
  const Icon = expanded ? PanelLeftClose : PanelLeftOpen;
  return (
    <>
      {railOpen ? (
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          onClick={() => setRailOpen(false)}
          className="fixed inset-0 -z-10 cursor-default bg-ink/30 lg:hidden"
        />
      ) : null}
      <button
        type="button"
        aria-expanded={expanded}
        aria-keyshortcuts="["
        onClick={toggle}
        className={className}
      >
        <Icon size={20} strokeWidth={2} aria-hidden="true" />
        <span className="sh-sb-label">{label}</span>
        <span aria-hidden="true" className={`sh-sb-tip ${tipClassName}`}>
          {label} <kbd className="ml-1 font-sans text-muted">[</kbd>
        </span>
      </button>
    </>
  );
}

/**
 * The content region re-enters on every route change (native View
 * Transitions through React's `<ViewTransition>`); Suspense reveals and
 * refreshes are untyped and do not animate it. Browsers without the API
 * simply swap the content.
 */
export function PageTransition({ children }: { children: ReactNode }) {
  const path = usePathname();
  return (
    <ViewTransition key={path} enter="sh-page" exit="sh-page" default="none">
      <div>{children}</div>
    </ViewTransition>
  );
}

/**
 * Phone account sheet (ADR 0024): a native `<details>` so it works before
 * hydration, upgraded with a sliding panel, scrim, Escape, a focus loop that
 * includes the trigger, focus return, and an exit animation.
 */
export function AccountSheet({
  trigger,
  children,
}: {
  trigger: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const path = usePathname();

  const close = useCallback((restoreFocus: boolean) => {
    const details = ref.current;
    if (!details?.open || details.dataset.closing !== undefined) return;
    const finish = () => {
      delete details.dataset.closing;
      details.open = false;
      if (restoreFocus) details.querySelector("summary")?.focus();
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      finish();
      return;
    }
    details.dataset.closing = "";
    window.setTimeout(finish, 160);
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: runs on route change only.
  useEffect(() => {
    const details = ref.current;
    if (!details) return;
    delete details.dataset.closing;
    details.open = false;
  }, [path]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const details = ref.current;
      if (!details?.open) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close(true);
        return;
      }
      if (event.key !== "Tab") return;
      const items = [
        ...details.querySelectorAll<HTMLElement>(
          "summary, a[href], button:not([disabled])",
        ),
      ].filter((item) => item.getAttribute("tabindex") !== "-1");
      const first = items[0];
      const last = items.at(-1);
      if (!first || !last) return;
      if (!details.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close]);

  return (
    <details ref={ref} className="relative">
      {/* biome-ignore lint/a11y/noStaticElementInteractions: <summary> is the native disclosure button; the handler only animates its close. */}
      <summary
        aria-label="Account menu"
        onClick={(event) => {
          if (ref.current?.open) {
            event.preventDefault();
            close(false);
          }
        }}
        className="flex min-h-11 min-w-11 cursor-pointer list-none items-center justify-center rounded-full outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus [&::-webkit-details-marker]:hidden"
      >
        {trigger}
      </summary>
      <div className="sh-sheet">
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          onClick={() => close(true)}
          className="sh-sheet-scrim fixed inset-0 z-40 cursor-default bg-ink/40"
        />
        <div className="sh-sheet-panel fixed inset-x-0 bottom-0 z-50 rounded-t-2xl bg-surface px-2 pt-2 pb-[calc(env(safe-area-inset-bottom)+12px)] shadow-[0_-16px_48px_rgba(23,21,18,.18)]">
          <span
            aria-hidden="true"
            className="mx-auto mb-2 block h-1 w-10 rounded-full bg-line-strong"
          />
          {children}
        </div>
      </div>
    </details>
  );
}
