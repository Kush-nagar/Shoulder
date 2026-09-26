import { ChevronLeft, Upload } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { focus, pageTitle, secondary } from "./ui";

/**
 * The content header: page title, one quiet line of context, and the
 * persistent "Upload match" action (`docs/05-ui.md`). Pages that are the
 * upload flow, or that carry their own primary action, pass `action`.
 */
export function PageHeader({
  title,
  description,
  action,
  crumb,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  /** The list this page belongs to, shown as a quiet way back above the title. */
  crumb?: { href: string; label: string };
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 px-5 pt-6 pb-5 md:px-6 lg:px-8 lg:pt-8">
      <div className="min-w-0">
        {crumb ? (
          <Link
            href={crumb.href}
            className={`-ml-1 mb-1.5 inline-flex h-7 items-center gap-0.5 rounded-md pr-1.5 text-[13px] text-muted hover:text-ink ${focus}`}
          >
            <ChevronLeft size={15} strokeWidth={1.75} aria-hidden="true" />
            {crumb.label}
          </Link>
        ) : null}
        <h1 className={pageTitle}>{title}</h1>
        {description ? (
          <p className="mt-1.5 text-[14px] leading-[1.45] text-muted">
            {description}
          </p>
        ) : null}
      </div>
      {action === undefined ? (
        <Link href="/coach/upload" className={secondary}>
          <Upload size={16} strokeWidth={1.75} aria-hidden="true" />
          Upload match
        </Link>
      ) : (
        action
      )}
    </header>
  );
}
