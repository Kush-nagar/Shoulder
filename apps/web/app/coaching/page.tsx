import { ChevronRight, MapPin, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { dollars, formatLabel, specialtyLabel } from "./format";
import { adultOnly } from "./gate";
import { read } from "./server";
import { type MarketplaceCoach, SPECIALTIES, type Specialty } from "./types";
import {
  emptyBox,
  errorBox,
  field,
  focus,
  label,
  lead,
  pageTitle,
  secondaryButton,
} from "./ui";

const chipBase = `inline-flex min-h-11 items-center rounded-full border px-4 text-[15px] font-semibold transition-colors duration-150 ease-out ${focus}`;
const chipOn = "border-ink bg-ink text-paper";
const chipOff =
  "border-control-border text-ink-2 hover:bg-surface-subtle hover:text-ink";

export default async function CoachingPage({
  searchParams,
}: {
  searchParams: Promise<{
    specialty?: string;
    city?: string;
    birthday?: string;
  }>;
}) {
  const query = await searchParams;
  const gate = await adultOnly("/coaching", query.birthday);
  if (!gate.token) return gate.blocked;
  const specialty = SPECIALTIES.find((s) => s === query.specialty) ?? null;
  const city = (query.city ?? "").trim().slice(0, 80);
  const params = new URLSearchParams();
  if (specialty) params.set("specialty", specialty);
  if (city) params.set("city", city);
  const coaches = await read<MarketplaceCoach[]>(
    gate.token,
    `/v1/marketplace/coaches${params.size ? `?${params}` : ""}`,
  );
  const href = (s: Specialty | null) => {
    const next = new URLSearchParams();
    if (s) next.set("specialty", s);
    if (city) next.set("city", city);
    return next.size ? `/coaching?${next}` : "/coaching";
  };

  return (
    <div>
      <h1 className={pageTitle}>Find a coach</h1>
      <p className={`${lead} mt-3`}>
        Independent coaches for paid 1:1 sessions. Every coach listed here has
        had their background-check document checked by the Shoulder team.
      </p>

      <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-12">
        <div className="min-w-0 lg:order-2">
          <form action="/coaching" className="space-y-2">
            {specialty ? (
              <input type="hidden" name="specialty" value={specialty} />
            ) : null}
            <label htmlFor="city" className={label}>
              City
            </label>
            <div className="flex gap-2">
              <input
                id="city"
                name="city"
                defaultValue={city}
                maxLength={80}
                autoComplete="address-level2"
                className={`${field} min-w-0 flex-1`}
              />
              <button type="submit" className={secondaryButton}>
                Search
              </button>
            </div>
          </form>
          <nav aria-label="Specialty" className="mt-6">
            <p className={label}>Specialty</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              <li>
                <Link
                  href={href(null)}
                  scroll={false}
                  aria-current={specialty === null ? "true" : undefined}
                  className={`${chipBase} ${specialty === null ? chipOn : chipOff}`}
                >
                  Any
                </Link>
              </li>
              {SPECIALTIES.map((s) => (
                <li key={s}>
                  <Link
                    href={href(s)}
                    scroll={false}
                    aria-current={s === specialty ? "true" : undefined}
                    className={`${chipBase} ${s === specialty ? chipOn : chipOff}`}
                  >
                    {specialtyLabel[s]}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>

        <section aria-labelledby="results-title" className="min-w-0 lg:order-1">
          <h2 id="results-title" className="sr-only">
            Coaches
          </h2>
          {coaches.data === null ? (
            <p role="alert" className={errorBox}>
              Coaches couldn&apos;t load. Try again in a moment.
            </p>
          ) : coaches.data.length === 0 ? (
            <div className={emptyBox}>
              <p className="text-[16px] font-semibold">
                No coaches match {specialty || city ? "these filters" : "yet"}.
              </p>
              <p className="mt-1 text-[16px] leading-6 text-ink-2">
                {specialty || city
                  ? "Try another city or specialty."
                  : "The pilot is small. New coaches appear once the Shoulder team has checked them."}
              </p>
              {specialty || city ? (
                <Link href="/coaching" className={`${secondaryButton} mt-4`}>
                  Clear filters
                </Link>
              ) : null}
            </div>
          ) : (
            <ul className="divide-y divide-line border-y border-line">
              {coaches.data.map((coach) => (
                <li key={coach.id}>
                  <Link
                    href={`/coaching/coaches/${coach.id}`}
                    className={`group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 rounded-lg px-2 py-5 transition-colors duration-150 ease-out hover:bg-surface-subtle md:px-4 ${focus}`}
                  >
                    <span className="min-w-0">
                      <span className="block font-display text-[26px] leading-[1.1] md:text-[28px]">
                        {coach.display_name}
                      </span>
                      <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px] text-ink-2">
                        <span className="inline-flex items-center gap-1">
                          <MapPin
                            size={16}
                            strokeWidth={2}
                            aria-hidden="true"
                          />
                          {coach.city}
                        </span>
                        <span>
                          {coach.formats
                            .map((f) => formatLabel[f])
                            .join(" or ")}
                        </span>
                        <span className="inline-flex items-center gap-1">
                          <ShieldCheck
                            size={16}
                            strokeWidth={2}
                            aria-hidden="true"
                          />
                          Background check verified
                        </span>
                      </span>
                      <span className="mt-2 block text-[15px] leading-6 text-muted">
                        {coach.specialties
                          .map((s) => specialtyLabel[s])
                          .join(", ")}
                      </span>
                    </span>
                    <span className="flex items-center gap-2 text-right">
                      <span>
                        <span className="block text-[20px] font-semibold tabular-nums">
                          {dollars(coach.rate_cents)}
                        </span>
                        <span className="block text-[13px] text-muted">
                          per hour
                        </span>
                      </span>
                      <ChevronRight
                        size={20}
                        strokeWidth={2}
                        aria-hidden="true"
                        className="text-muted transition-transform duration-150 ease-out group-hover:translate-x-0.5 motion-reduce:transition-none"
                      />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-6 text-[14px] leading-5 text-muted">
            Coaches are listed in no particular order. Shoulder doesn&apos;t
            rate or rank coaches.
          </p>
        </section>
      </div>
    </div>
  );
}
