import { ArrowLeft, ChevronRight, Footprints } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { drillBySlug, drills } from "../../../../content/drills";
import { requirePlayerSession } from "../../session";
import { backLink, focus, primaryButton, sectionTitle } from "../../ui";
import { DrillMeta } from "../drill-tile";

export default async function DrillPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  await requirePlayerSession(`/player/drills/${encodeURIComponent(slug)}`);
  const drill = drillBySlug(slug);
  if (!drill) notFound();
  const others = drills.filter((item) => item.slug !== drill.slug);
  const more = [
    ...others.filter((item) => item.focus === drill.focus),
    ...others.filter((item) => item.focus !== drill.focus),
  ].slice(0, 3);
  const sameFocus = more.every((item) => item.focus === drill.focus);

  return (
    <article aria-labelledby="drill-title" className="max-w-[680px]">
      <Link href="/player/drills" className={backLink}>
        <ArrowLeft size={20} strokeWidth={2} aria-hidden="true" />
        Drills
      </Link>
      <p className="mt-5 text-[14px] font-semibold text-action">
        {drill.focus}
      </p>
      <h1
        id="drill-title"
        className="mt-1 font-display text-[36px] leading-[1.02] text-balance md:text-[48px]"
      >
        {drill.title}
      </h1>
      <DrillMeta drill={drill} className="mt-4 text-[14px]" />

      <section
        aria-labelledby="why-title"
        className="mt-8 border-t border-line pt-6"
      >
        <h2 id="why-title" className={sectionTitle}>
          Why it helps
        </h2>
        <p className="mt-2 text-[17px] leading-7 text-ink-2">{drill.why}</p>
      </section>

      <section aria-labelledby="how-title" className="mt-8">
        <h2 id="how-title" className={sectionTitle}>
          How to do it
        </h2>
        <ol className="mt-4 space-y-4">
          {drill.steps.map((step, index) => (
            <li key={step} className="grid grid-cols-[2rem_1fr] gap-3">
              <span
                aria-hidden="true"
                className="font-display text-[24px] leading-7 text-brand tabular-nums"
              >
                {index + 1}
              </span>
              <span className="text-[16px] leading-7">{step}</span>
            </li>
          ))}
        </ol>
      </section>

      <section
        aria-labelledby="harder-title"
        className="mt-8 rounded-xl bg-surface-subtle p-4 md:p-5"
      >
        <h2
          id="harder-title"
          className="text-[17px] font-semibold leading-[1.35]"
        >
          Make it harder
        </h2>
        <p className="mt-1 text-[16px] leading-6 text-ink-2">{drill.harder}</p>
      </section>

      <div className="mt-8">
        <Link
          href={`/player/practice/new?title=${encodeURIComponent(drill.title)}`}
          className={`${primaryButton} w-full sm:w-auto`}
        >
          <Footprints size={20} strokeWidth={2} aria-hidden="true" />
          Film this drill
        </Link>
        <p className="mt-2 text-[14px] leading-5 text-muted">
          Film only yourself. Only you can see the video.
        </p>
      </div>

      <section
        aria-labelledby="more-title"
        className="mt-12 border-t border-line pt-6"
      >
        <h2 id="more-title" className={sectionTitle}>
          {sameFocus
            ? `More ${drill.focus.toLowerCase()} drills`
            : "More drills"}
        </h2>
        <ul className="mt-3 divide-y divide-line">
          {more.map((item) => (
            <li key={item.slug}>
              <Link
                href={`/player/drills/${item.slug}`}
                className={`group flex min-h-16 items-center justify-between gap-4 rounded-lg py-3 ${focus}`}
              >
                <span className="min-w-0">
                  <span className="block text-[17px] font-semibold leading-[1.35] group-hover:underline group-hover:underline-offset-4">
                    {item.title}
                  </span>
                  <span className="mt-0.5 block text-[13px] text-muted tabular-nums">
                    {item.focus}, {item.minutes} min
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
      </section>
    </article>
  );
}
