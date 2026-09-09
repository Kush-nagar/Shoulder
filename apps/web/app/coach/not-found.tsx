import Link from "next/link";
import { pageTitle, tertiary } from "./ui";

/** One surface for absent and for hidden-by-authorization. It names neither. */
export default function CoachNotFound() {
  return (
    <section className="mx-auto max-w-170 px-5 py-16 md:px-6 lg:px-8">
      <h1 className={pageTitle}>Not found</h1>
      <p className="mt-4 text-[15px] leading-[1.5] text-muted">
        This page is not available, or it is not yours to open. Nothing was
        changed.
      </p>
      <p className="mt-6">
        <Link href="/coach/roster" className={tertiary}>
          Back to players
        </Link>
      </p>
    </section>
  );
}
