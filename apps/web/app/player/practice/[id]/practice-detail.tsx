"use client";

import { Check, ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { chip, errorBox, sectionTitle, textLink } from "../../ui";
import { focus, practiceDate, primaryButton, secondaryButton } from "../format";
import type {
  AiCoachFeedback,
  PracticeFeatures,
  PracticeVideoDetail,
} from "../types";

// Loaded on demand so MediaPipe stays out of the page bundle.
async function loadAnalyzer() {
  return (await import("../pose/analyze")).analyzePractice;
}

type Analysis =
  | { state: "idle" }
  | { state: "running"; fraction: number }
  | { state: "done"; features: PracticeFeatures }
  | { state: "failed" };

function feedbackError(status: number) {
  if (status === 429)
    return "You've asked for ideas 10 times today. Try again tomorrow.";
  if (status === 422)
    return "The movement summary couldn't be used. Analyze the video again.";
  return "Training ideas didn't load. Try again.";
}

/** Numbered steps only when the text splits cleanly into sentences. */
function steps(how: string) {
  // Model text is either "1. Do this. 2. Then that." or plain sentences.
  const numbered = how
    .split(/(?:^|\s)\d+[.)]\s+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const parts =
    numbered.length >= 2
      ? numbered
      : how
          .split(/(?<=[.!?])\s+(?=[A-Z])/)
          .map((part) => part.trim())
          .filter(Boolean);
  return parts.length >= 2 && parts.length <= 8 ? parts : null;
}

function FeedbackCard({ feedback }: { feedback: AiCoachFeedback }) {
  const [more, setMore] = useState(false);
  const long = feedback.body.length > 160;
  return (
    <article
      aria-label="AI suggestion"
      className="rounded-xl border border-line bg-surface p-4 md:p-5"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={chip}>AI suggestion</span>
        <span className="text-[13px] text-muted tabular-nums">
          Suggested {practiceDate(feedback.created_at)}
        </span>
      </div>
      <p className="mt-3 text-[13px] leading-[1.4] text-muted">
        Suggestions from software, based on how you moved. Your coach&apos;s
        notes come from your coach.
      </p>
      <p
        className={`mt-3 whitespace-pre-line text-[16px] leading-6 ${more ? "" : "line-clamp-2"}`}
      >
        {feedback.body}
      </p>
      {long ? (
        <button
          type="button"
          onClick={() => setMore((value) => !value)}
          aria-expanded={more}
          className={textLink}
        >
          {more ? "Show less" : "Read more"}
        </button>
      ) : null}
      {feedback.drills.length ? (
        <ul className="mt-3 divide-y divide-line border-t border-line">
          {feedback.drills.map((drill, index) => {
            const list = steps(drill.how);
            return (
              <li key={drill.title}>
                <details className="group" open={index === 0}>
                  <summary
                    className={`flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 rounded-lg py-2 [&::-webkit-details-marker]:hidden ${focus}`}
                  >
                    <h3 className="text-[17px] font-semibold leading-[1.35]">
                      {drill.title}
                    </h3>
                    <ChevronDown
                      size={20}
                      strokeWidth={2}
                      aria-hidden="true"
                      className="shrink-0 text-muted transition-transform duration-150 group-open:rotate-180"
                    />
                  </summary>
                  <div className="pb-4">
                    <p className="text-[14px] font-semibold text-ink-2">
                      Why it helps
                    </p>
                    <p className="mt-0.5 text-[16px] leading-6 text-ink-2">
                      {drill.why}
                    </p>
                    <p className="mt-3 text-[14px] font-semibold text-ink-2">
                      How to do it
                    </p>
                    {list ? (
                      <ol className="mt-1 list-decimal space-y-1 pl-5 text-[16px] leading-6 text-ink-2 marker:text-muted">
                        {list.map((step) => (
                          <li key={step}>{step}</li>
                        ))}
                      </ol>
                    ) : (
                      <p className="mt-0.5 text-[16px] leading-6 text-ink-2">
                        {drill.how}
                      </p>
                    )}
                    <Link
                      href={`/player/practice/new?title=${encodeURIComponent(drill.title)}`}
                      className={`${textLink} mt-1`}
                    >
                      Film this drill
                      <ChevronRight
                        size={18}
                        strokeWidth={2}
                        aria-hidden="true"
                      />
                    </Link>
                  </div>
                </details>
              </li>
            );
          })}
        </ul>
      ) : null}
    </article>
  );
}

function round(value: number, digits = 0) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/** The literal summary sent for ideas, in plain words. Never compared. */
function WhatWasSent({ features }: { features: PracticeFeatures }) {
  const rows: [string, string][] = [
    ["Video length", `${round(features.duration_ms / 1000, 1)} seconds`],
    ["Frames looked at", `${features.frames_analyzed}`],
    ["Head turns seen", `${features.head_turns}`],
    ["Head turns per minute", `${round(features.head_turns_per_min, 1)}`],
    [
      "Knee bend, middle of the video",
      `${round(features.knee_flexion_deg.p50)} degrees`,
    ],
    [
      "Hip bend, middle of the video",
      `${round(features.hip_flexion_deg.p50)} degrees`,
    ],
    [
      "Body lean, middle of the video",
      `${round(features.trunk_lean_deg.p50)} degrees`,
    ],
    [
      "Feet apart, compared with hip width",
      `${round(features.stance_width_ratio.p50, 1)} times`,
    ],
  ];
  return (
    <details className="group rounded-xl border border-line">
      <summary
        className={`flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 text-[16px] font-semibold [&::-webkit-details-marker]:hidden ${focus}`}
      >
        What was sent
        <ChevronDown
          size={20}
          strokeWidth={2}
          aria-hidden="true"
          className="shrink-0 text-muted transition-transform duration-150 group-open:rotate-180"
        />
      </summary>
      <div className="border-t border-line px-4 pt-3 pb-4">
        <p className="text-[14px] leading-5 text-muted">
          Measurements from this video only. They are not a grade.
        </p>
        <dl className="mt-3 space-y-2 text-[15px] leading-6">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4">
              <dt className="text-ink-2">{label}</dt>
              <dd className="shrink-0 font-medium tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </details>
  );
}

export function PracticeDetail({
  video,
  initialFeedback,
  feedbackLoaded,
}: {
  video: PracticeVideoDetail;
  initialFeedback: AiCoachFeedback[];
  feedbackLoaded: boolean;
}) {
  const router = useRouter();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [ratio, setRatio] = useState(16 / 9);
  const [playError, setPlayError] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis>({ state: "idle" });
  const [feedback, setFeedback] = useState(
    [...initialFeedback].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    ),
  );
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [lines, setLines] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  // The inline confirmation takes focus when it opens, on the safe choice.
  useEffect(() => {
    if (confirmDelete) keepRef.current?.focus();
  }, [confirmDelete]);
  const playable = video.status === "ready" && video.playback_url && !playError;
  const running = analysis.state === "running";

  async function analyze() {
    const element = videoRef.current;
    if (!element || running) return;
    setAskError(null);
    setAnalysis({ state: "running", fraction: 0 });
    try {
      const analyzePractice = await loadAnalyzer();
      const features = await analyzePractice(
        element,
        canvasRef.current,
        (fraction) =>
          setAnalysis({
            state: "running",
            fraction: Math.min(1, Math.max(0, fraction)),
          }),
      );
      setAnalysis({ state: "done", features });
    } catch {
      setAnalysis({ state: "failed" });
    }
  }

  async function ask() {
    if (analysis.state !== "done" || asking) return;
    setAsking(true);
    setAskError(null);
    try {
      const response = await fetch(
        `/api/player/practice/${video.id}/ai-feedback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(analysis.features),
          cache: "no-store",
        },
      );
      if (!response.ok) {
        setAskError(feedbackError(response.status));
        return;
      }
      const created = (await response.json()) as AiCoachFeedback;
      setFeedback((current) => [created, ...current]);
    } catch {
      setAskError(feedbackError(503));
    } finally {
      setAsking(false);
    }
  }

  async function remove() {
    setDeleting(true);
    setDeleteError(null);
    try {
      const response = await fetch(`/api/player/practice/${video.id}`, {
        method: "DELETE",
        cache: "no-store",
      });
      if (!response.ok && response.status !== 404) throw new Error("delete");
      router.replace("/player/practice");
      router.refresh();
    } catch {
      setDeleteError("Could not delete. Your video is unchanged. Try again.");
      setDeleting(false);
    }
  }

  const [latest, ...earlier] = feedback;
  const analysed = analysis.state !== "idle";

  return (
    <div className="mt-6 grid gap-10 lg:grid-cols-12 lg:gap-8">
      <div className="min-w-0 space-y-8 lg:col-span-7">
        <section aria-label="Video">
          <div
            className="relative mx-auto overflow-hidden rounded-[14px] bg-night"
            style={{
              aspectRatio: ratio,
              width: `min(100%, calc(70dvh * ${ratio}))`,
            }}
          >
            {playable ? (
              <>
                {/* biome-ignore lint/a11y/useMediaCaption: the player's own practice video has no speech track to caption. */}
                <video
                  ref={videoRef}
                  src={video.playback_url ?? undefined}
                  // Pose analysis reads frames, which needs a CORS-clean video.
                  crossOrigin="anonymous"
                  controls={!running}
                  playsInline
                  preload="metadata"
                  aria-label="Your practice video"
                  className="size-full object-contain"
                  onLoadedMetadata={(event) => {
                    const { videoWidth, videoHeight } = event.currentTarget;
                    if (videoWidth && videoHeight)
                      setRatio(videoWidth / videoHeight);
                  }}
                  onError={() => setPlayError(true)}
                />
                <canvas
                  ref={canvasRef}
                  className={`pointer-events-none absolute inset-0 size-full ${lines ? "" : "invisible"}`}
                />
              </>
            ) : (
              <div
                role="status"
                className="flex size-full items-center justify-center px-6 text-center text-[16px] leading-6 text-on-night"
              >
                {video.status === "uploading"
                  ? "This upload didn't finish. Delete it and upload the video again."
                  : "This video couldn't play. Check your connection and reload."}
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-3">
            {playError ? (
              <button
                type="button"
                onClick={() => {
                  setPlayError(false);
                  router.refresh();
                }}
                className={`${secondaryButton} mt-3`}
              >
                Reload video
              </button>
            ) : null}
            {playable && analysed ? (
              <button
                type="button"
                aria-pressed={lines}
                onClick={() => setLines((value) => !value)}
                className={`${secondaryButton} mt-3`}
              >
                {lines ? (
                  <Check size={18} strokeWidth={2} aria-hidden="true" />
                ) : null}
                Show body lines
              </button>
            ) : null}
          </div>
        </section>

        {playable ? (
          <section
            aria-labelledby="movement-title"
            className="space-y-4 border-t border-line pt-6"
          >
            <h2 id="movement-title" className={sectionTitle}>
              Your movement
            </h2>
            <p className="max-w-[56ch] text-[16px] leading-6 text-ink-2">
              Shoulder finds your body position on this device. The video never
              leaves it for this step.
            </p>

            {analysis.state === "running" ? (
              <div aria-live="polite" className="space-y-2">
                <div
                  role="progressbar"
                  aria-label="Movement analysis"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(analysis.fraction * 100)}
                  className="h-1.5 overflow-hidden rounded-full bg-surface-subtle"
                >
                  <div
                    className="h-full origin-left rounded-full bg-action transition-transform duration-200 ease-out"
                    style={{ transform: `scaleX(${analysis.fraction})` }}
                  />
                </div>
                <p className="text-[15px] text-ink-2">
                  Finding your body position on this device. Keep this page
                  open.
                </p>
              </div>
            ) : null}

            {analysis.state === "failed" ? (
              <p role="alert" className={errorBox}>
                Couldn&apos;t find a clear view of you. Try a video where your
                whole body is in frame.
              </p>
            ) : null}

            {analysis.state === "done" ? (
              <p role="status" className="flex gap-2 text-[16px] leading-6">
                <Check
                  size={20}
                  strokeWidth={2}
                  aria-hidden="true"
                  className="mt-0.5 shrink-0"
                />
                Done. Only a short summary of your body angles is sent when you
                ask for training ideas.
              </p>
            ) : null}

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void analyze()}
                disabled={running}
                className={
                  analysis.state === "done" ? secondaryButton : primaryButton
                }
              >
                {running
                  ? "Analyzing…"
                  : analysis.state === "idle"
                    ? "Analyze my movement"
                    : "Analyze again"}
              </button>
              {analysis.state === "done" ? (
                <button
                  type="button"
                  onClick={() => void ask()}
                  disabled={asking}
                  className={primaryButton}
                >
                  {asking ? "Getting ideas…" : "Get training ideas"}
                </button>
              ) : null}
            </div>
            {askError ? (
              <p role="alert" className={errorBox}>
                {askError}
              </p>
            ) : null}
            {analysis.state === "done" ? (
              <WhatWasSent features={analysis.features} />
            ) : null}
          </section>
        ) : null}
      </div>

      <section
        aria-labelledby="ideas-title"
        aria-busy={asking}
        className="min-w-0 lg:sticky lg:top-6 lg:col-span-5 lg:self-start"
      >
        <h2 id="ideas-title" className={sectionTitle}>
          Training ideas
        </h2>
        {!feedbackLoaded ? (
          <p role="alert" className="mt-3 text-[16px] leading-6 text-error">
            Earlier training ideas didn&apos;t load. Try again.
          </p>
        ) : null}
        {asking ? (
          <div
            aria-hidden="true"
            className="mt-4 h-72 rounded-xl bg-surface-subtle"
          />
        ) : null}
        {latest ? (
          <div className="mt-4">
            <FeedbackCard feedback={latest} />
          </div>
        ) : feedbackLoaded && !asking ? (
          <p className="mt-3 max-w-[52ch] text-[16px] leading-6 text-ink-2">
            None yet. Analyze your movement, then ask for training ideas.
          </p>
        ) : null}
        {earlier.length ? (
          <details className="group mt-4">
            <summary
              className={`flex min-h-11 cursor-pointer list-none items-center gap-1.5 rounded-lg text-[16px] font-semibold [&::-webkit-details-marker]:hidden ${focus}`}
            >
              <ChevronRight
                size={18}
                strokeWidth={2}
                aria-hidden="true"
                className="transition-transform duration-150 group-open:rotate-90"
              />
              Earlier ideas ({earlier.length})
            </summary>
            <div className="mt-3 space-y-4">
              {earlier.map((item) => (
                <FeedbackCard key={item.id} feedback={item} />
              ))}
            </div>
          </details>
        ) : null}
      </section>

      <section
        aria-label="Delete video"
        className="border-t border-line pt-6 lg:col-span-12"
      >
        {confirmDelete ? (
          <div
            role="alertdialog"
            aria-labelledby="delete-practice-title"
            aria-describedby="delete-practice-body"
            className="max-w-[560px] rounded-xl border border-error bg-error-soft p-4 md:p-5"
          >
            <h2
              id="delete-practice-title"
              className="text-[17px] font-semibold text-ink"
            >
              Delete this video?
            </h2>
            <p
              id="delete-practice-body"
              className="mt-1 text-[16px] leading-6 text-ink"
            >
              It&apos;s removed now, with its training ideas, and can&apos;t be
              recovered.
            </p>
            {deleteError ? (
              <p role="alert" className="mt-2 text-[16px] text-error">
                {deleteError}
              </p>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void remove()}
                disabled={deleting}
                className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-error px-4 text-[16px] font-semibold text-paper transition-transform duration-150 active:scale-[0.98] disabled:opacity-45 ${focus}`}
              >
                <Trash2 size={18} strokeWidth={2} aria-hidden="true" />
                {deleting ? "Deleting…" : "Delete video"}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                disabled={deleting}
                className={secondaryButton}
                ref={keepRef}
              >
                Keep video
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className={`-ml-1 inline-flex min-h-11 items-center gap-2 rounded-lg px-1 text-[16px] font-semibold text-error underline-offset-4 hover:underline ${focus}`}
          >
            <Trash2 size={18} strokeWidth={2} aria-hidden="true" />
            Delete this video
          </button>
        )}
      </section>
    </div>
  );
}
