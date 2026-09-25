import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { When } from "../../coaching/client";
import { read, requireSignedIn } from "../../coaching/server";
import type {
  CoachReviewSummary,
  CoachStatus,
  MarketplaceReport,
} from "../../coaching/types";
import {
  emptyBox,
  errorBox,
  focus,
  pageTitle,
  sectionTitle,
} from "../../coaching/ui";
import { ResolveReport } from "./forms";

const TABS: [CoachStatus, string][] = [
  ["pending_review", "Waiting"],
  ["rejected", "Changes needed"],
  ["verified", "Verified"],
  ["suspended", "Suspended"],
];

const chipBase = `inline-flex min-h-11 items-center rounded-full border px-4 text-[15px] font-semibold transition-colors duration-150 ease-out ${focus}`;
const chipOn = "border-ink bg-ink text-paper";
const chipOff =
  "border-control-border text-ink-2 hover:bg-surface-subtle hover:text-ink";

export default async function AdminCoachesPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const token = await requireSignedIn("/admin/coaches");
  const query = await searchParams;
  const status =
    TABS.find(([s]) => s === query.status)?.[0] ?? "pending_review";
  const [queue, reports, resolvedReports] = await Promise.all([
    read<CoachReviewSummary[]>(
      token,
      `/v1/admin/coach-reviews?status=${status}`,
    ),
    read<MarketplaceReport[]>(token, "/v1/admin/reports?status=open"),
    read<MarketplaceReport[]>(token, "/v1/admin/reports?status=resolved"),
  ]);
  // Not an admin, or the pilot is off at the API: the page does not exist.
  if ([403, 404].includes(queue.status) || [403, 404].includes(reports.status))
    notFound();
  const open = reports.data ?? [];
  const resolved = resolvedReports.data ?? [];

  return (
    <div className="grid gap-12 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14">
      <section aria-labelledby="queue-title" className="min-w-0">
        <h1 id="queue-title" className={pageTitle}>
          Coach reviews
        </h1>
        <nav aria-label="Review status" className="mt-6">
          <ul className="flex flex-wrap gap-2">
            {TABS.map(([key, name]) => (
              <li key={key}>
                <Link
                  href={`/admin/coaches?status=${key}`}
                  scroll={false}
                  aria-current={key === status ? "true" : undefined}
                  className={`${chipBase} ${key === status ? chipOn : chipOff}`}
                >
                  {name}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        {queue.data === null ? (
          <p role="alert" className={`${errorBox} mt-6`}>
            The queue couldn&apos;t load. Try again in a moment.
          </p>
        ) : queue.data.length === 0 ? (
          <div className={`${emptyBox} mt-6`}>
            <p className="text-[16px] font-semibold">Nothing here.</p>
            <p className="mt-1 text-[16px] leading-6 text-ink-2">
              No coach profiles have this status.
            </p>
          </div>
        ) : (
          <ul className="mt-6 divide-y divide-line border-y border-line">
            {queue.data.map((coach) => (
              <li key={coach.id}>
                <Link
                  href={`/admin/coaches/${coach.id}`}
                  className={`flex min-h-16 items-center justify-between gap-4 rounded-lg px-2 py-3 hover:bg-surface-subtle ${focus}`}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[17px] font-semibold">
                      {coach.display_name}
                    </span>
                    <span className="block text-[14px] text-muted">
                      {coach.city}, updated <When iso={coach.updated_at} />
                    </span>
                  </span>
                  <ChevronRight
                    size={20}
                    strokeWidth={2}
                    aria-hidden="true"
                    className="shrink-0 text-muted"
                  />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        id="reports"
        aria-labelledby="reports-title"
        className="min-w-0 scroll-mt-40"
      >
        <h2 id="reports-title" className={sectionTitle}>
          Reports
        </h2>
        <p className="mt-1 text-[15px] leading-6 text-ink-2">
          An open report from a player who paid for a session with that coach
          stops new bookings. Other reports wait here without unlisting.
        </p>
        {reports.data === null ? (
          <p role="alert" className={`${errorBox} mt-4`}>
            Reports couldn&apos;t load. Try again in a moment.
          </p>
        ) : open.length === 0 ? (
          <p className="mt-4 text-[16px] text-muted">No open reports.</p>
        ) : (
          <ul className="mt-4 space-y-4">
            {open.map((report) => (
              <li
                key={report.id}
                className="rounded-xl border border-line-strong bg-surface p-4"
              >
                <p className="text-[14px] text-muted">
                  <When iso={report.created_at} />
                  {report.booking_id ? ", about a booking" : ""}
                </p>
                <Link
                  href={`/admin/coaches/${report.coach_profile_id}`}
                  className={`mt-1 inline-block text-[17px] font-semibold underline-offset-4 hover:underline ${focus}`}
                >
                  {report.coach_display_name}
                </Link>
                <p className="mt-2 whitespace-pre-line text-[16px] leading-6">
                  {report.reason}
                </p>
                <div className="mt-3">
                  <ResolveReport id={report.id} />
                </div>
              </li>
            ))}
          </ul>
        )}
        {resolved.length ? (
          <details className="mt-6">
            <summary
              className={`min-h-11 cursor-pointer rounded-lg py-2 text-[15px] font-semibold text-ink-2 ${focus}`}
            >
              Resolved ({resolved.length})
            </summary>
            <ul className="mt-2 divide-y divide-line">
              {resolved.map((report) => (
                <li key={report.id} className="py-3 text-[15px] leading-6">
                  <span className="font-semibold">
                    {report.coach_display_name}
                  </span>
                  <span className="text-muted">
                    , <When iso={report.created_at} />
                  </span>
                  <p className="text-ink-2">{report.reason}</p>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </section>
    </div>
  );
}
