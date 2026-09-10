import Link from "next/link";

import { pageTitle, secondary } from "./ui";

/**
 * The 64px content header: page title plus the persistent primary action.
 * `docs/05-ui.md`: "Upload match" is the persistent primary action on ordinary
 * coach pages.
 */
export function PageHeader({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-line px-5 py-4 md:px-6 lg:min-h-16 lg:px-8">
      <div>
        <h1 className={pageTitle}>{title}</h1>
        {description ? (
          <p className="mt-1 text-[15px] leading-[1.5] text-muted">
            {description}
          </p>
        ) : null}
      </div>
      <Link href="/coach/upload" className={secondary}>
        Upload match
      </Link>
    </header>
  );
}
