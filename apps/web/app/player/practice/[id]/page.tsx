import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { uuid } from "../../../../lib/bff";
import { requirePlayerSession } from "../../session";
import { backLink, pageTitle } from "../../ui";
import { practiceDate, practiceTitle } from "../format";
import { fetchPracticeFeedback, fetchPracticeVideo } from "../server";
import { PracticeDetail } from "./practice-detail";

export default async function PracticeVideoPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const id = uuid((await params).id);
  if (!id) notFound();
  const { token } = await requirePlayerSession(`/player/practice/${id}`);
  const [video, feedback] = await Promise.all([
    fetchPracticeVideo(token, id),
    fetchPracticeFeedback(token, id),
  ]);
  // Another player's id and a missing id look the same, by design.
  if (video.status === 404 || video.status === 403) notFound();
  if (!video.data || video.data.status === "deleted") {
    if (video.data) notFound();
    throw new Error("practice-video-unavailable");
  }

  return (
    <article aria-labelledby="practice-title">
      <Link href="/player/practice" className={backLink}>
        <ArrowLeft size={20} strokeWidth={2} aria-hidden="true" />
        Practice
      </Link>
      <h1 id="practice-title" className={`${pageTitle} mt-3`}>
        {practiceTitle(video.data.title)}
      </h1>
      <p className="mt-2 text-[13px] text-muted tabular-nums">
        Uploaded {practiceDate(video.data.created_at)}
        {video.data.expires_at
          ? `, removed on ${practiceDate(video.data.expires_at)}`
          : ""}
      </p>
      <PracticeDetail
        video={video.data}
        initialFeedback={feedback.data ?? []}
        feedbackLoaded={feedback.data !== null}
      />
    </article>
  );
}
