"use client";

import { type ReactNode, useId, useRef, useState } from "react";
import { field, label, metadata } from "../ui";

/**
 * Local search over the server-rendered table. It hides rows rather than
 * re-rendering them, so the table stays a Server Component.
 */
export function RosterSearch({
  total,
  children,
}: {
  total: number;
  children: ReactNode;
}) {
  const region = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(total);
  const inputId = useId();

  function filter(value: string) {
    const query = value.trim().toLowerCase();
    let visible = 0;
    for (const row of region.current?.querySelectorAll<HTMLTableRowElement>(
      "tr[data-player]",
    ) ?? []) {
      const match = query === "" || (row.dataset.player ?? "").includes(query);
      row.hidden = !match;
      if (match) visible += 1;
    }
    setShown(visible);
  }

  return (
    <>
      <div className="mt-4 max-w-80">
        <label htmlFor={inputId} className={label}>
          Search players
        </label>
        <input
          id={inputId}
          type="search"
          autoComplete="off"
          onChange={(event) => filter(event.target.value)}
          className={`${field} mt-1`}
        />
      </div>
      <p aria-live="polite" className={`${metadata} mt-2`}>
        Showing {shown} of {total} players
      </p>
      <div ref={region}>{children}</div>
    </>
  );
}
