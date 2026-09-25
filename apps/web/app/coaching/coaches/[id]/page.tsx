import { ArrowLeft, MapPin, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { dollars, formatLabel, specialtyLabel } from "../../format";
import { BookForm } from "../../forms";
import { adultOnly } from "../../gate";
import { read } from "../../server";
import type { MarketplaceCoachDetail } from "../../types";
import {
  backLink,
  chip,
  errorBox,
  pageTitle,
  panel,
  sectionTitle,
} from "../../ui";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function CoachDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const gate = await adultOnly(`/coaching/coaches/${id}`);
  if (!gate.token) return gate.blocked;
  const coach = await read<MarketplaceCoachDetail>(
    gate.token,
    `/v1/marketplace/coaches/${id}`,
  );
  if (coach.status === 404) notFound();

  return (
    <div>
      <Link href="/coaching" className={backLink}>
        <ArrowLeft size={18} strokeWidth={2} aria-hidden="true" />
        All coaches
      </Link>
      {coach.data === null ? (
        <p role="alert" className={`${errorBox} mt-6 max-w-[560px]`}>
          This coach couldn&apos;t load. Try again in a moment.
        </p>
      ) : (
        <div className="mt-4 grid gap-10 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-14">
          <article className="min-w-0">
            <h1 className={`${pageTitle} md:text-[44px]`}>
              {coach.data.display_name}
            </h1>
            <p className="mt-3 inline-flex items-center gap-2 text-[15px] font-semibold">
              <ShieldCheck
                size={18}
                strokeWidth={2}
                aria-hidden="true"
                className="text-action"
              />
              Background check verified
            </p>
            <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-y border-line py-5 sm:grid-cols-3">
              <div>
                <dt className="text-[13px] text-muted">Rate</dt>
                <dd className="mt-0.5 text-[20px] font-semibold tabular-nums">
                  {dollars(coach.data.rate_cents)}
                  <span className="text-[15px] font-normal text-ink-2">
                    {" "}
                    / hour
                  </span>
                </dd>
              </div>
              <div>
                <dt className="text-[13px] text-muted">City</dt>
                <dd className="mt-0.5 inline-flex items-center gap-1 text-[16px] font-semibold">
                  <MapPin size={16} strokeWidth={2} aria-hidden="true" />
                  {coach.data.city}
                </dd>
              </div>
              <div>
                <dt className="text-[13px] text-muted">Sessions</dt>
                <dd className="mt-0.5 text-[16px] font-semibold">
                  {coach.data.formats.map((f) => formatLabel[f]).join(" or ")}
                </dd>
              </div>
            </dl>
            <h2 className="sr-only">About</h2>
            <p className="mt-6 max-w-[65ch] whitespace-pre-line text-[17px] leading-7 text-ink">
              {coach.data.bio}
            </p>
            <h2 className="mt-8 text-[16px] font-semibold">Works on</h2>
            <ul className="mt-2 flex flex-wrap gap-2">
              {coach.data.specialties.map((s) => (
                <li key={s} className={chip}>
                  {specialtyLabel[s]}
                </li>
              ))}
            </ul>
            <p className="mt-8 max-w-[60ch] text-[14px] leading-5 text-muted">
              In-person sessions happen at the public venue shown on each time.
              Keep contact and payment inside Shoulder.
            </p>
          </article>

          <section
            aria-labelledby="book-title"
            className={`${panel} self-start p-5 md:p-6 lg:sticky lg:top-36`}
          >
            <h2 id="book-title" className={sectionTitle}>
              Book a time
            </h2>
            <p className="mt-1 mb-5 text-[15px] leading-6 text-ink-2">
              Times are in your time zone. Cancel more than 24 hours before for
              a full refund.
            </p>
            <BookForm
              slots={coach.data.slots}
              rateCents={coach.data.rate_cents}
            />
          </section>
        </div>
      )}
    </div>
  );
}
