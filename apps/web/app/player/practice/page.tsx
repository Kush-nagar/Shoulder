import { Footprints, Play } from "lucide-react";
import Link from "next/link";
import { requirePlayerSession } from "../session";
import { errorBox, pageTitle, sectionTitle, textLink } from "../ui";
import {
  clock,
  focus,
  monthLabel,
  practiceDate,
  practiceStatus,
  practiceTitle,
  primaryButton,
} from "./format";
import { fetchPracticeVideos } from "./server";
import type { PracticeVideo } from "./types";

function byMonth(videos: PracticeVideo[]) {
  const groups = new Map<string, PracticeVideo[]>();
  for (const video of videos) {
    const key = monthLabel(video.created_at);
    groups.set(key, [...(groups.get(key) ?? []), video]);
  }
  return [...groups];
}

export default async function PracticePage() {
  const { token } = await requirePlayerSession("/player/practice");
  const { data } = await fetchPracticeVideos(token);
  const videos =
    data
      ?.filter((video) => video.status !== "deleted")
      .sort((a, b) => b.created_at.localeCompare(a.created_at)) ?? null;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className={pageTitle}>Practice</h1>
        <Link href="/player/practice/new" className={primaryButton}>
          <Footprints size={20} strokeWidth={2} aria-hidden="true" />
          Film practice
        </Link>
      </div>
      <p className="mt-3 max-w-[56ch] text-[16px] leading-6 text-ink-2">
        Only you can see these videos. Each one is removed 90 days after upload.
      </p>

      {videos === null ? (
        <p role="alert" className={`${errorBox} mt-8`}>
          Your practice videos could not be loaded. Try again in a moment.
        </p>
      ) : videos.length === 0 ? (
        <section
          aria-labelledby="practice-empty-title"
          className="mt-8 max-w-[680px] rounded-xl border border-dashed border-control-border px-5 py-8 md:px-8"
        >
          <h2 id="practice-empty-title" className={sectionTitle}>
            No practice videos yet
          </h2>
          <p className="mt-2 text-[16px] leading-6 text-ink-2">
            Film a drill, see how you moved, and get training ideas.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2">
            <Link href="/player/practice/new" className={primaryButton}>
              <Footprints size={20} strokeWidth={2} aria-hidden="true" />
              Film practice
            </Link>
            <Link href="/player/drills" className={textLink}>
              Need an idea? Browse drills
            </Link>
          </div>
        </section>
      ) : (
        byMonth(videos).map(([month, items]) => (
          <section key={month} aria-label={month} className="mt-8 md:mt-10">
            <h2 className="text-[17px] font-semibold leading-[1.35] text-ink-2">
              {month}
            </h2>
            <ul className="mt-3 divide-y divide-line border-t border-line md:grid md:grid-cols-2 md:gap-x-4 md:gap-y-6 md:divide-y-0 md:border-t-0 lg:grid-cols-3">
              {items.map((video) => {
                const length = clock(video.duration_ms);
                return (
                  <li key={video.id}>
                    <Link
                      href={`/player/practice/${video.id}`}
                      className={`group flex items-center gap-3 rounded-lg py-3 md:block md:py-0 ${focus}`}
                    >
                      <span className="relative flex aspect-video w-24 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-night text-on-night md:w-full">
                        <span className="flex size-8 items-center justify-center rounded-full border border-night-line md:size-11">
                          <Play
                            size={14}
                            strokeWidth={2}
                            fill="currentColor"
                            aria-hidden="true"
                          />
                        </span>
                        {length ? (
                          <span className="absolute right-2 bottom-2 hidden text-[13px] text-night-muted tabular-nums md:block">
                            {length}
                          </span>
                        ) : null}
                      </span>
                      <span className="min-w-0 flex-1 md:mt-2 md:block">
                        <span className="block truncate text-[16px] font-semibold leading-[1.35] group-hover:underline group-hover:underline-offset-4 md:text-[17px]">
                          {practiceTitle(video.title)}
                        </span>
                        <span className="mt-0.5 block text-[13px] text-muted tabular-nums">
                          {practiceDate(video.created_at)}
                          {length ? (
                            <span className="md:hidden">, {length}</span>
                          ) : null}
                          {video.status === "uploading"
                            ? ", upload not finished"
                            : ""}
                        </span>
                      </span>
                      <span className="sr-only">
                        {practiceStatus(video.status)}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}
    </div>
  );
}
