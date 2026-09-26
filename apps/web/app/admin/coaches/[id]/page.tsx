import { ArrowLeft, FileText } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { formatBytes } from "../../../../lib/upload";
import { When } from "../../../coaching/client";
import { dollars, formatLabel, specialtyLabel } from "../../../coaching/format";
import { Monogram } from "../../../coaching/parts";
import { read, requireSignedIn } from "../../../coaching/server";
import type { CoachReviewDetail, CoachStatus } from "../../../coaching/types";
import {
  backLink,
  chip,
  errorBox,
  pageTitle,
  panel,
  sectionTitle,
} from "../../../coaching/ui";
import { DecisionForm, OpenDocument } from "../forms";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const statusName: Record<CoachStatus, string> = {
  draft: "Draft",
  pending_review: "Waiting for review",
  rejected: "Changes needed",
  verified: "Verified",
  suspended: "Suspended",
};

const statusTone: Record<CoachStatus, string> = {
  draft: "border border-control-border text-ink-2",
  pending_review: "border border-action text-action",
  rejected: "bg-error-soft text-error",
  verified: "bg-action-soft text-ink",
  suspended: "bg-ink text-paper",
};

const kindName = {
  background_check: "Background check",
  id: "ID",
  certification: "Certification",
} as const;

export default async function AdminCoachPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const token = await requireSignedIn(`/admin/coaches/${id}`);
  const coach = await read<CoachReviewDetail>(
    token,
    `/v1/admin/coach-reviews/${id}`,
  );
  if (coach.status === 403 || coach.status === 404) notFound();

  return (
    <div>
      <Link href="/admin/coaches" className={backLink}>
        <ArrowLeft size={18} strokeWidth={2} aria-hidden="true" />
        Coach reviews
      </Link>
      {coach.data === null ? (
        <p role="alert" className={`${errorBox} mt-6 max-w-[560px]`}>
          This profile couldn&apos;t load. Try again in a moment.
        </p>
      ) : (
        <div className="mt-4 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-14">
          <article className="min-w-0">
            <div className="flex items-center gap-4">
              <Monogram
                name={coach.data.display_name}
                size="size-16 text-[26px]"
              />
              <div className="min-w-0">
                <h1 className={pageTitle}>{coach.data.display_name}</h1>
                <p className="mt-2 flex flex-wrap items-center gap-2 text-[15px] text-ink-2">
                  <span
                    className={`inline-flex min-h-7 items-center rounded-full px-2.5 text-[13px] font-semibold ${statusTone[coach.data.status]}`}
                  >
                    {statusName[coach.data.status]}
                  </span>
                  {coach.data.verified_at ? (
                    <>
                      {"verified "}
                      <When iso={coach.data.verified_at} />
                    </>
                  ) : null}
                </p>
              </div>
            </div>
            <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-y border-line py-5 sm:grid-cols-4">
              <div>
                <dt className="text-[13px] text-muted">Rate</dt>
                <dd className="text-[16px] font-semibold tabular-nums">
                  {dollars(coach.data.rate_cents)} / h
                </dd>
              </div>
              <div>
                <dt className="text-[13px] text-muted">City</dt>
                <dd className="text-[16px] font-semibold">{coach.data.city}</dd>
              </div>
              <div>
                <dt className="text-[13px] text-muted">Sessions</dt>
                <dd className="text-[16px] font-semibold">
                  {coach.data.formats.map((f) => formatLabel[f]).join(", ")}
                </dd>
              </div>
              <div>
                <dt className="text-[13px] text-muted">Payouts</dt>
                <dd className="text-[16px] font-semibold">
                  {coach.data.charges_enabled ? "Ready" : "Not set up"}
                </dd>
              </div>
            </dl>
            <p className="mt-6 max-w-[65ch] whitespace-pre-line text-[16px] leading-7">
              {coach.data.bio}
            </p>
            <ul className="mt-4 flex flex-wrap gap-2">
              {coach.data.specialties.map((s) => (
                <li key={s} className={chip}>
                  {specialtyLabel[s]}
                </li>
              ))}
            </ul>

            <h2 className={`${sectionTitle} mt-10`}>Documents</h2>
            <p className="mt-1 text-[14px] leading-5 text-muted">
              Each document opens in a new tab through a link that stops working
              after about a minute. Every open is recorded.
            </p>
            {coach.data.documents.length ? (
              <ul className="mt-4 space-y-2">
                {coach.data.documents.map((doc) => (
                  <li
                    key={doc.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-surface p-3 md:px-4"
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <span
                        aria-hidden="true"
                        className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-surface-subtle text-ink-2"
                      >
                        <FileText size={20} strokeWidth={2} />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[16px] font-semibold">
                          {kindName[doc.kind]}
                        </span>
                        <span className="block text-[13px] text-muted tabular-nums">
                          {doc.content_type
                            .replace("application/", "")
                            .replace("image/", "")
                            .toUpperCase()}
                          , {formatBytes(doc.size_bytes)}
                          {doc.uploaded_at ? (
                            <>
                              {", "}
                              <When iso={doc.uploaded_at} />
                            </>
                          ) : (
                            ", not uploaded yet"
                          )}
                        </span>
                      </span>
                    </span>
                    {doc.status === "ready" ? (
                      <OpenDocument profileId={id} documentId={doc.id} />
                    ) : (
                      <span className="text-[14px] text-muted">
                        Upload not finished
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 text-[16px] text-muted">
                No documents uploaded.
              </p>
            )}
          </article>

          <section
            aria-labelledby="decide-title"
            className={`${panel} self-start p-5 md:p-6 lg:sticky lg:top-36`}
          >
            <h2 id="decide-title" className={sectionTitle}>
              Decide
            </h2>
            {coach.data.review_note ? (
              <p className="mt-2 rounded-lg bg-surface-subtle p-3 text-[15px] leading-6">
                <span className="block text-[13px] font-semibold text-muted">
                  Last note
                </span>
                {coach.data.review_note}
              </p>
            ) : null}
            <div className="mt-4">
              <DecisionForm id={coach.data.id} status={coach.data.status} />
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
