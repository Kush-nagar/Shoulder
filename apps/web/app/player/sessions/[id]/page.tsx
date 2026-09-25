import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { uuid } from "../../../../lib/bff";
import { requirePlayerSession } from "../../session";
import { backLink, pageTitle, sectionTitle } from "../../ui";
import { Heatmap } from "../charts";
import {
  km,
  kmh,
  kindLabel,
  qualityLabel,
  sessionDate,
  stopwatch,
} from "../format";
import { fetchSession } from "../server";
import { DeleteSession } from "./delete-session";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-surface p-4">
      <dt className="text-[14px] font-semibold text-ink-2">{label}</dt>
      <dd className="mt-1 text-[24px] font-semibold leading-tight tabular-nums md:text-[28px]">
        {value}
      </dd>
    </div>
  );
}

export default async function SessionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const id = uuid((await params).id);
  if (!id) notFound();
  const { token } = await requirePlayerSession(`/player/sessions/${id}`);
  const reply = await fetchSession(token, id);
  // Another player's id and a missing id look the same, by design.
  if (reply.status === 404 || reply.status === 403) notFound();
  if (!reply.data) throw new Error("session-unavailable");
  const session = reply.data;
  const time = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(session.started_at));

  return (
    <article aria-labelledby="session-title">
      <Link href="/player/sessions" className={backLink}>
        <ArrowLeft size={20} strokeWidth={2} aria-hidden="true" />
        Sessions
      </Link>
      <h1 id="session-title" className={`${pageTitle} mt-3`}>
        {kindLabel[session.kind]}, {sessionDate(session.started_at)}
      </h1>
      <p className="mt-2 text-[13px] text-muted tabular-nums">
        Started {time} · {qualityLabel[session.gps_quality]}
      </p>
      {session.note ? (
        <p className="mt-4 max-w-[60ch] border-l-2 border-brand pl-4 text-[16px] leading-6">
          {session.note}
        </p>
      ) : null}

      <dl className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Distance" value={km(session.distance_m)} />
        <Stat label="Time" value={stopwatch(session.duration_s)} />
        <Stat label="Top speed" value={kmh(session.top_speed_cms)} />
        <Stat label="Sprints" value={String(session.sprint_count)} />
      </dl>

      {session.half_split_s ? (
        <section aria-labelledby="halves-title" className="mt-10">
          <h2 id="halves-title" className={sectionTitle}>
            Halves
          </h2>
          <dl className="mt-3 grid max-w-[560px] grid-cols-2 gap-3">
            <Stat label="First half" value={stopwatch(session.half_split_s)} />
            <Stat
              label="Second half"
              value={stopwatch(session.duration_s - session.half_split_s)}
            />
          </dl>
        </section>
      ) : null}

      <section aria-labelledby="heatmap-title" className="mt-10">
        <h2 id="heatmap-title" className={sectionTitle}>
          Where you played
        </h2>
        <div
          className={`mt-4 grid gap-6 ${session.heatmap_second_half ? "md:grid-cols-2" : "max-w-[720px]"}`}
        >
          <Heatmap cells={session.heatmap} label="Whole session" />
          {session.heatmap_second_half ? (
            <Heatmap cells={session.heatmap_second_half} label="Second half" />
          ) : null}
        </div>
      </section>

      <section
        aria-label="Delete session"
        className="mt-10 border-t border-line pt-6"
      >
        <DeleteSession id={session.id} />
      </section>
    </article>
  );
}
