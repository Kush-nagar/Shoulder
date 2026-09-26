import { CalendarClock, MapPin, Search, SearchX } from "lucide-react";
import Link from "next/link";
import { When } from "./client";
import { dollars, formatLabel, specialtyLabel } from "./format";
import { adultOnly } from "./gate";
import { DemoTag, isDemo, Monogram, shownName, VerifiedBadge } from "./parts";
import { read } from "./server";
import {
  type MarketplaceCoach,
  type MarketplaceCoachDetail,
  SPECIALTIES,
  type Specialty,
} from "./types";
import {
  caption,
  emptyBox,
  errorBox,
  field,
  filterChip,
  focus,
  lead,
  pageTitle,
  primaryButton,
  secondaryButton,
} from "./ui";

// ponytail: one detail read per card for "next open time", capped; add
// `next_slot_at` to the list function if the pilot grows past this.
const NEXT_SLOT_READS = 12;

async function nextSlots(
  token: string,
  coaches: MarketplaceCoach[],
): Promise<Map<string, string | null>> {
  const found = await Promise.all(
    coaches.slice(0, NEXT_SLOT_READS).map(async (coach) => {
      const detail = await read<MarketplaceCoachDetail>(
        token,
        `/v1/marketplace/coaches/${coach.id}`,
      );
      if (!detail.data) return [coach.id, undefined] as const;
      const first = detail.data.slots
        .map((s) => s.starts_at)
        .sort()
        .at(0);
      return [coach.id, first ?? null] as const;
    }),
  );
  const map = new Map<string, string | null>();
  for (const [id, first] of found) if (first !== undefined) map.set(id, first);
  return map;
}

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
  const next = coaches.data?.length
    ? await nextSlots(gate.token, coaches.data)
    : new Map<string, string | null>();
  const href = (s: Specialty | null) => {
    const q = new URLSearchParams();
    if (s) q.set("specialty", s);
    if (city) q.set("city", city);
    return q.size ? `/coaching?${q}` : "/coaching";
  };
  const filtered = Boolean(specialty || city);

  return (
    <div>
      <div className="sh-rise max-w-[720px]">
        <h1 className={`${pageTitle} md:text-[40px]`}>Find a coach</h1>
        <p className={`${lead} mt-3`}>
          Paid 1:1 sessions with independent coaches. Every coach here has had
          their background check confirmed by the Shoulder team.
        </p>
      </div>

      <div
        className="sh-rise mt-7 rounded-2xl border border-line bg-surface p-3 md:p-4"
        style={{ "--i": 1 } as React.CSSProperties}
      >
        <form action="/coaching" className="flex gap-2">
          {specialty ? (
            <input type="hidden" name="specialty" value={specialty} />
          ) : null}
          <label htmlFor="city" className="sr-only">
            City
          </label>
          <div className="relative min-w-0 flex-1">
            <MapPin
              size={18}
              strokeWidth={2}
              aria-hidden="true"
              className="pointer-events-none absolute inset-y-0 left-3 my-auto text-muted"
            />
            <input
              id="city"
              name="city"
              defaultValue={city}
              maxLength={80}
              placeholder="City"
              autoComplete="address-level2"
              className={`${field} pl-10`}
            />
          </div>
          <button type="submit" className={primaryButton}>
            <Search size={18} strokeWidth={2} aria-hidden="true" />
            <span className="max-[374px]:sr-only">Search</span>
          </button>
        </form>
        <nav
          aria-label="Specialty"
          className="-mx-3 mt-3 overflow-x-auto px-3 pb-1 md:-mx-4 md:px-4 [scrollbar-width:none]"
        >
          <ul className="flex gap-2 md:flex-wrap">
            <li>
              <Link
                href={href(null)}
                scroll={false}
                aria-current={specialty === null ? "true" : undefined}
                className={filterChip(specialty === null)}
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
                  className={filterChip(s === specialty)}
                >
                  {specialtyLabel[s]}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      <section aria-labelledby="results-title" className="mt-8">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 id="results-title" className="text-[17px] font-semibold">
            {coaches.data?.length
              ? `${coaches.data.length} ${coaches.data.length === 1 ? "coach" : "coaches"}${city ? ` in or near ${city}` : ""}`
              : "Coaches"}
          </h2>
          <p className={caption}>
            In no particular order. Shoulder doesn&apos;t rate or rank coaches.
          </p>
        </div>

        {coaches.data === null ? (
          <p role="alert" className={`${errorBox} mt-4`}>
            Coaches couldn&apos;t load. Try again in a moment.
          </p>
        ) : coaches.data.length === 0 ? (
          <div className={`${emptyBox} mt-4 flex flex-col items-start gap-1`}>
            <SearchX
              size={28}
              strokeWidth={1.75}
              aria-hidden="true"
              className="mb-2 text-muted"
            />
            <p className="text-[17px] font-semibold">
              No coaches match {filtered ? "these filters" : "yet"}.
            </p>
            <p className="max-w-[52ch] text-[16px] leading-6 text-ink-2">
              {filtered
                ? "Try a nearby city or another specialty."
                : "The pilot is small. New coaches appear once the Shoulder team has checked them."}
            </p>
            {filtered ? (
              <Link href="/coaching" className={`${secondaryButton} mt-4`}>
                Clear filters
              </Link>
            ) : null}
          </div>
        ) : (
          <ul className="sh-stagger mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {coaches.data.map((coach) => (
              <li key={coach.id} className="min-w-0">
                <CoachCard coach={coach} next={next.get(coach.id)} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function CoachCard({
  coach,
  next,
}: {
  coach: MarketplaceCoach;
  next: string | null | undefined;
}) {
  const shown = coach.specialties.slice(0, 3);
  const more = coach.specialties.length - shown.length;
  return (
    <Link
      href={`/coaching/coaches/${coach.id}`}
      className={`group flex h-full flex-col rounded-xl border border-line bg-surface p-5 transition-[border-color,background-color,transform] duration-200 ease-out hover:-translate-y-0.5 hover:border-line-strong hover:bg-surface-subtle motion-reduce:transition-none motion-reduce:hover:translate-y-0 ${focus}`}
    >
      <span className="flex items-start gap-4">
        <Monogram name={coach.display_name} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-display text-[24px] leading-[1.1] group-hover:underline group-hover:decoration-2 group-hover:underline-offset-4">
              {shownName(coach.display_name, coach.bio)}
            </span>
            {isDemo(coach.bio) ? <DemoTag /> : null}
          </span>
          <span className="mt-1 flex items-center gap-1 text-[15px] text-ink-2">
            <MapPin size={15} strokeWidth={2} aria-hidden="true" />
            {coach.city}
          </span>
        </span>
      </span>

      <span className="mt-4">
        <VerifiedBadge compact />
      </span>

      <span className="mt-4 mb-5 flex flex-wrap gap-1.5">
        {shown.map((s) => (
          <span
            key={s}
            className="inline-flex min-h-7 items-center rounded-md bg-surface-subtle px-2 text-[13px] font-semibold text-ink-2"
          >
            {specialtyLabel[s]}
          </span>
        ))}
        {more > 0 ? (
          <span className="inline-flex min-h-7 items-center px-1 text-[13px] font-semibold text-muted">
            +{more} more
          </span>
        ) : null}
      </span>

      <span className="mt-auto grid grid-cols-[minmax(0,1fr)_auto] items-end gap-x-3 border-t border-line pt-4">
        <span className="min-w-0">
          <span className="block text-[14px] text-ink-2">
            {coach.formats.map((f) => formatLabel[f]).join(" or ")}
          </span>
          <span className="mt-1 flex items-center gap-1.5 text-[14px] text-muted">
            <CalendarClock
              size={15}
              strokeWidth={2}
              aria-hidden="true"
              className="shrink-0"
            />
            {next === undefined ? (
              "See open times"
            ) : next === null ? (
              "No open times yet"
            ) : (
              <span className="truncate">
                Next <When iso={next} className="tabular-nums text-ink-2" />
              </span>
            )}
          </span>
        </span>
        <span className="text-right">
          <span className="block text-[22px] font-semibold leading-none tabular-nums">
            {dollars(coach.rate_cents)}
          </span>
          <span className={caption}>per hour</span>
        </span>
      </span>
    </Link>
  );
}
