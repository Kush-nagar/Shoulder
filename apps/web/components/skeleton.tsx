import type { ReactNode } from "react";

/** One placeholder shape. Rounded like a control unless told otherwise. */
export function Bone({ className = "" }: { className?: string }) {
  const radius = /\brounded(-|\b)/.test(className) ? "" : "rounded-lg";
  return (
    <div aria-hidden="true" className={`sh-skel ${radius} ${className}`} />
  );
}

/** Announces a loading region once; its shapes stay silent. */
export function Loading({
  label = "Loading",
  className = "",
  children,
}: {
  label?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={label}
      className={className}
    >
      {children}
    </div>
  );
}

/** Stable keys for a run of identical placeholder shapes. */
export function keys(count: number) {
  return Array.from({ length: count }, (_, n) => `bone-${n}`);
}
