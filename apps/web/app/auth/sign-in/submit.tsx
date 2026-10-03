"use client";

import type { ReactNode } from "react";
import { useFormStatus } from "react-dom";

/** Submit button that shows the form is working once pressed. */
export function Submit({
  className,
  pending: pendingLabel,
  children,
}: {
  className: string;
  pending: string;
  children: ReactNode;
}) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      aria-busy={pending}
      className={`${className} disabled:cursor-progress`}
    >
      {pending ? (
        <>
          <span
            aria-hidden="true"
            className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent"
          />
          {pendingLabel}
        </>
      ) : (
        children
      )}
    </button>
  );
}
