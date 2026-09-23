import Link from "next/link";
import { requirePlayerSession } from "../session";
import {
  clock,
  focus,
  practiceDate,
  practiceTitle,
  primaryButton,
} from "./format";
import { fetchPracticeVideos } from "./server";

export default async function PracticePage() {
  const { token } = await requirePlayerSession("/player/practice");
  const { data } = await fetchPracticeVideos(token);
  const videos = data?.filter((video) => video.status !== "deleted") ?? null;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-[32px] font-semibold leading-[1.08] tracking-[-0.01em]">
          Practice
        </h1>
        {videos?.length ? (
          <Link href="/player/practice/new" className={primaryButton}>
            Upload practice
          </Link>
        ) : null}
      </div>
      <p className="mt-3 max-w-[48ch] text-[16px] leading-6 text-ink-2">
        Your own videos. Only you can see them, and each one is removed 90 days
        after you upload it.
      </p>

      {videos === null ? (
        <p
          role="alert"
          className="mt-8 rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
        >
          Your practice videos could not be loaded. Try again in a moment.
        </p>
      ) : videos.length === 0 ? (
        <section
          aria-labelledby="practice-empty-title"
          className="mt-8 rounded-[14px] border border-dashed border-line-strong px-5 py-8"
        >
          <h2
            id="practice-empty-title"
            className="text-[21px] font-semibold leading-[1.25]"
          >
            No practice videos yet
          </h2>
          <ol className="mt-4 space-y-3 text-[16px] leading-6 text-ink-2">
            <li>Prop your phone up so your whole body is in the frame.</li>
            <li>Film one drill for under a minute.</li>
            <li>Upload it, then see how you moved.</li>
          </ol>
          <Link
            href="/player/practice/new"
            className={`${primaryButton} mt-6 w-full sm:w-auto`}
          >
            Upload practice
          </Link>
        </section>
      ) : (
        <ul className="mt-8 divide-y divide-line border-t border-line">
          {videos.map((video) => {
            const length = clock(video.duration_ms);
            return (
              <li key={video.id}>
                <Link
                  href={`/player/practice/${video.id}`}
                  className={`group flex min-h-16 items-center justify-between gap-4 py-4 ${focus}`}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[17px] font-semibold leading-[1.35] group-hover:underline group-hover:underline-offset-4">
                      {practiceTitle(video.title)}
                    </span>
                    <span className="mt-1 block text-[13px] text-muted tabular-nums">
                      {practiceDate(video.created_at)}
                      {length ? `, ${length}` : ""}
                    </span>
                  </span>
                  {video.status === "uploading" ? (
                    <span className="shrink-0 text-[14px] text-muted">
                      Upload not finished
                    </span>
                  ) : (
                    <span
                      aria-hidden="true"
                      className="shrink-0 text-[15px] font-semibold text-action"
                    >
                      Open
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
