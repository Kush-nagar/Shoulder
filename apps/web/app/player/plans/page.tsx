import { ArrowLeft, CalendarDays, History } from "lucide-react";
import Link from "next/link";
import { fetchPlayerPlans } from "../../../lib/api";
import { mondayOf } from "../../../lib/plans";
import { SectionHeading } from "../heading";
import { requirePlayerSession } from "../session";
import { backLink, errorBox, pageTitle } from "../ui";
import { PlayerPlanCard } from "./plan-card";

export default async function PlayerPlansPage() {
  const { token } = await requirePlayerSession("/player/plans");
  const plans = await fetchPlayerPlans(token);
  const thisWeek = mondayOf(new Date());
  const current = plans?.filter((plan) => plan.week_of >= thisWeek) ?? [];
  const earlier = plans?.filter((plan) => plan.week_of < thisWeek) ?? [];

  return (
    <div className="max-w-[680px]">
      <Link href="/player" className={backLink}>
        <ArrowLeft size={20} strokeWidth={2} aria-hidden="true" />
        Home
      </Link>
      <h1 className={`${pageTitle} mt-4`}>From your coach</h1>
      <p className="mt-2 text-[16px] leading-6 text-ink-2">
        Drills your coach picked for you and your team.
      </p>
      {plans === null ? (
        <p role="alert" className={`${errorBox} mt-6`}>
          Your plans couldn&apos;t load. Try again in a moment.
        </p>
      ) : plans.length === 0 ? (
        <p className="mt-6 text-[16px] leading-6 text-ink-2">
          Your coach hasn&apos;t shared a plan yet. It&apos;ll show up here.
        </p>
      ) : (
        <>
          <section aria-labelledby="current-plans" className="mt-8">
            <SectionHeading id="current-plans" Icon={CalendarDays}>
              This week and ahead
            </SectionHeading>
            {current.length ? (
              <div className="sh-stagger mt-3 space-y-4">
                {current.map((plan) => (
                  <PlayerPlanCard key={plan.id} plan={plan} />
                ))}
              </div>
            ) : (
              <p className="mt-2 text-[16px] leading-6 text-ink-2">
                Nothing new this week.
              </p>
            )}
          </section>
          {earlier.length ? (
            <section aria-labelledby="earlier-plans" className="mt-10">
              <SectionHeading id="earlier-plans" Icon={History}>
                Earlier plans
              </SectionHeading>
              <div className="mt-3 space-y-4">
                {earlier.map((plan) => (
                  <PlayerPlanCard key={plan.id} plan={plan} />
                ))}
              </div>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
