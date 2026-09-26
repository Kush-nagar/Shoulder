import type { ReactNode } from "react";

/**
 * Empty state (ADR 0026): a short mono label, one plain sentence, and at most
 * one action, over faint halfway-line geometry. No illustration.
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
      className={`sh-pitch flex flex-col items-center rounded-xl border border-line bg-surface px-6 py-12 text-center ${className}`}
    >
      <p className="font-mono text-[12px] text-muted uppercase">{label}</p>
      <div className="mt-2 max-w-[42ch] text-[15px] leading-[1.5] text-ink">
        {children}
      </div>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
