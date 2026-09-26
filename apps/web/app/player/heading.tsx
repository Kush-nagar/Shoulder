import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { sectionTitle } from "./ui";

/** Section title led by a quiet icon (ADR 0024, 0026). */
export function SectionHeading({
  id,
  Icon,
  className = "",
  children,
}: {
  id?: string;
  Icon: LucideIcon;
  className?: string;
  children: ReactNode;
}) {
  return (
    <h2
      id={id}
      className={`${sectionTitle} flex items-center gap-2.5 ${className}`}
    >
      <Icon
        size={20}
        strokeWidth={2}
        aria-hidden="true"
        className="shrink-0 text-muted"
      />
      {children}
    </h2>
  );
}
