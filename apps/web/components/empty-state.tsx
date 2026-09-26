import type { ReactNode } from "react";

/**
 * Empty state (ADR 0026): a short mono label, one plain sentence, and at most
 * one action, under a small centre-circle mark. No illustration.
 */
export function EmptyState({
  label,
  children,
  action,
  className = "",
}: {
  label: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center rounded-xl border border-line bg-surface px-6 py-10 text-center ${className}`}
    >
      <span aria-hidden="true" className="sh-pitch mb-4" />
      <p className="font-mono text-[12px] text-muted uppercase">{label}</p>
      <div className="mt-2 max-w-[42ch] text-[15px] leading-[1.5] text-ink">
        {children}
      </div>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
