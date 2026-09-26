import {
  ArrowLeft,
  Clock3,
  Laptop,
  MapPin,
  MessageSquareOff,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { dollars, formatLabel, specialtyLabel } from "../../format";
import { BookForm } from "../../forms";
import { adultOnly } from "../../gate";
import {
  bioText,
  DemoTag,
  isDemo,
  Monogram,
  shownName,
  VerifiedBadge,
} from "../../parts";
import { read } from "../../server";
import type { MarketplaceCoachDetail } from "../../types";
import { backLink, errorBox, pageTitle, panel, sectionTitle } from "../../ui";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const meta = "inline-flex items-center gap-1.5 text-[15px] text-ink-2";

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
  const c = coach.data;

  return (
    <div>
      <Link href="/coaching" className={backLink}>
        <ArrowLeft size={18} strokeWidth={2} aria-hidden="true" />
        All coaches
      </Link>
      {c === null ? (
        <p role="alert" className={`${errorBox} mt-6 max-w-[560px]`}>
          This coach couldn&apos;t load. Try again in a moment.
        </p>
      ) : (
        <div className="mt-4 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_400px] lg:gap-14">
          <article className="min-w-0">
            <header className="sh-rise flex flex-col gap-5 sm:flex-row sm:items-center">
              <Monogram
                name={c.display_name}
                size="size-20 text-[34px] md:size-24 md:text-[40px]"
              />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                  <h1 className={`${pageTitle} md:text-[44px]`}>
                    {shownName(c.display_name, c.bio)}
                  </h1>
                  {isDemo(c.bio) ? <DemoTag /> : null}
                </div>
                <p className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                  <span className={meta}>
                    <MapPin size={16} strokeWidth={2} aria-hidden="true" />
                    {c.city}
                  </span>
                  <span className={meta}>
                    <Laptop size={16} strokeWidth={2} aria-hidden="true" />
                    {c.formats.map((f) => formatLabel[f]).join(" or ")}
                  </span>
                  <span className={meta}>
                    <Wallet size={16} strokeWidth={2} aria-hidden="true" />
                    <span className="tabular-nums">
                      <span className="font-semibold text-ink">
                        {dollars(c.rate_cents)}
                      </span>{" "}
                      per hour
                    </span>
                  </span>
                </p>
              </div>
            </header>

            <div
              className="sh-rise mt-6"
              style={{ "--i": 1 } as React.CSSProperties}
            >
              <VerifiedBadge />
            </div>

            <section
              aria-labelledby="about-title"
              className="sh-rise mt-8 border-t border-line pt-7"
              style={{ "--i": 2 } as React.CSSProperties}
            >
              <h2 id="about-title" className={sectionTitle}>
                About
              </h2>
              <p className="mt-3 max-w-[65ch] whitespace-pre-line text-[17px] leading-7 text-ink">
                {bioText(c.bio)}
              </p>
              <h3 className="mt-7 text-[15px] font-semibold text-ink-2">
                Works on
              </h3>
              <ul className="mt-2 flex flex-wrap gap-2">
                {c.specialties.map((s) => (
                  <li
                    key={s}
                    className="inline-flex min-h-9 items-center rounded-lg bg-surface-subtle px-3 text-[15px] font-semibold text-ink"
                  >
                    {specialtyLabel[s]}
                  </li>
                ))}
              </ul>
            </section>

            <section
              aria-labelledby="how-title"
              className="sh-rise mt-8 border-t border-line pt-7"
              style={{ "--i": 3 } as React.CSSProperties}
            >
              <h2 id="how-title" className={sectionTitle}>
                How sessions work
              </h2>
              <ul className="mt-4 grid gap-4 sm:grid-cols-2">
                <li className="flex gap-3">
                  <MapPin
                    size={20}
                    strokeWidth={2}
                    aria-hidden="true"
                    className="mt-0.5 shrink-0 text-muted"
                  />
                  <p className="text-[15px] leading-6 text-ink-2">
                    <span className="block font-semibold text-ink">
                      Public venues only
                    </span>
                    In-person sessions happen at the public venue shown on each
                    time.
                  </p>
                </li>
                <li className="flex gap-3">
                  <MessageSquareOff
                    size={20}
                    strokeWidth={2}
                    aria-hidden="true"
                    className="mt-0.5 shrink-0 text-muted"
                  />
                  <p className="text-[15px] leading-6 text-ink-2">
                    <span className="block font-semibold text-ink">
                      Stay on Shoulder
                    </span>
                    Keep contact and payment inside Shoulder so refunds and
                    reports work.
                  </p>
                </li>
                <li className="flex gap-3">
                  <Clock3
                    size={20}
                    strokeWidth={2}
                    aria-hidden="true"
                    className="mt-0.5 shrink-0 text-muted"
                  />
                  <p className="text-[15px] leading-6 text-ink-2">
                    <span className="block font-semibold text-ink">
                      Your time zone
                    </span>
                    Every time on this page is shown in your own time zone.
                  </p>
                </li>
              </ul>
            </section>
          </article>

          <section
            aria-labelledby="book-title"
            className={`${panel} sh-rise self-start p-5 md:p-6 lg:sticky lg:top-28`}
            style={{ "--i": 1 } as React.CSSProperties}
          >
            <h2 id="book-title" className={sectionTitle}>
              Book a time
            </h2>
            <p className="mt-1 mb-5 text-[15px] leading-6 text-ink-2">
              Times are in your time zone. You pay on the next step.
            </p>
            <BookForm slots={c.slots} rateCents={c.rate_cents} />
          </section>
        </div>
      )}
    </div>
  );
}
