"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { focus, practiceDate, primaryButton, secondaryButton } from "../format";
import type {
  AiCoachFeedback,
  PracticeFeatures,
  PracticeVideoDetail,
} from "../types";

// W2 owns ../pose/analyze.ts. The specifier is a template so this file
// typechecks before that module lands; swap to a static
// `import("../pose/analyze")` once it does.
type Analyze = (
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement | null,
  onProgress?: (fraction: number) => void,
) => Promise<PracticeFeatures>;

async function loadAnalyzer(): Promise<Analyze> {
  const name = "analyze";
  const loaded = (await import(`../pose/${name}`)) as {
    analyzePractice: Analyze;
  };
  return loaded.analyzePractice;
}

type Analysis =
  | { state: "idle" }
  | { state: "running"; fraction: number }
  | { state: "done"; features: PracticeFeatures }
  | { state: "failed" };

const AI_LABEL = "AI suggestion — your coach's notes come from your coach";

function feedbackError(status: number) {
  if (status === 429)
    return "You've asked for training ideas a lot today. Try again tomorrow.";
  if (status === 422)
    return "The movement summary couldn't be used. Analyze the video again.";
  return "Training ideas aren't available right now. Try again in a moment.";
}

function FeedbackCard({ feedback }: { feedback: AiCoachFeedback }) {
  return (
    <article
      aria-label="AI suggestion"
      className="rounded-[14px] border border-line bg-surface p-5"
    >
      <p className="text-[13px] font-semibold leading-[1.4] text-muted">
        {AI_LABEL}
      </p>
      <p className="mt-3 whitespace-pre-line text-[16px] leading-6">
        {feedback.body}
      </p>
      {feedback.drills.length ? (
        <ol className="mt-5 space-y-5 border-t border-line pt-5">
          {feedback.drills.map((drill) => (
            <li key={drill.title}>
              <h3 className="text-[17px] font-semibold leading-[1.35]">
                {drill.title}
              </h3>
              <dl className="mt-2 space-y-2 text-[16px] leading-6">
                <div>
                  <dt className="text-[14px] font-semibold text-ink-2">
                    Why it helps
                  </dt>
                  <dd className="text-ink-2">{drill.why}</dd>
                </div>
                <div>
                  <dt className="text-[14px] font-semibold text-ink-2">
                    How to do it
                  </dt>
                  <dd className="text-ink-2">{drill.how}</dd>
                </div>
              </dl>
            </li>
          ))}
        </ol>
      ) : null}
      <p className="mt-5 text-[13px] text-muted tabular-nums">
        Suggested {practiceDate(feedback.created_at)}
      </p>
    </article>
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
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  // The inline confirmation takes focus when it opens, on the safe choice.
  useEffect(() => {
    if (confirmDelete) keepRef.current?.focus();
  }, [confirmDelete]);
  const playable = video.status === "ready" && video.url && !playError;
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

  return (
    <div className="mt-6 space-y-10">
      <section aria-label="Video">
        <div
          className="relative mx-auto overflow-hidden rounded-[14px] bg-ink"
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
                src={video.url ?? undefined}
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
                className="pointer-events-none absolute inset-0 size-full"
              />
            </>
          ) : (
            <div
              role="status"
              className="flex size-full items-center justify-center px-6 text-center text-[16px] leading-6 text-paper"
            >
              {video.status === "uploading"
                ? "This upload didn't finish. Delete it and upload the video again."
                : "This video couldn't play. Check your connection and reload."}
            </div>
          )}
        </div>
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
      </section>

      {playable ? (
        <section aria-labelledby="movement-title" className="space-y-4">
          <h2
            id="movement-title"
            className="text-[21px] font-semibold leading-[1.25]"
          >
            Your movement
          </h2>
          <p className="max-w-[52ch] text-[16px] leading-6 text-ink-2">
            Shoulder draws your body position on this phone. The video never
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
                className="h-2 overflow-hidden rounded-full bg-surface-subtle"
              >
                <div
                  className="h-full origin-left rounded-full bg-action transition-transform duration-200 ease-out"
                  style={{ transform: `scaleX(${analysis.fraction})` }}
                />
              </div>
              <p className="text-[15px] text-ink-2">
                Watching your movement. Keep this page open.
              </p>
            </div>
          ) : null}

          {analysis.state === "failed" ? (
            <p
              role="alert"
              className="rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
            >
              Shoulder couldn't follow your movement in this video. Try one
              filmed from the side with your whole body in view.
            </p>
          ) : null}

          {analysis.state === "done" ? (
            <p role="status" className="text-[16px] leading-6">
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
            <p
              role="alert"
              className="rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
            >
              {askError}
            </p>
          ) : null}
        </section>
      ) : null}

      <section aria-labelledby="ideas-title" aria-busy={asking}>
        <h2
          id="ideas-title"
          className="text-[21px] font-semibold leading-[1.25]"
        >
          Training ideas
        </h2>
        {!feedbackLoaded ? (
          <p role="alert" className="mt-3 text-[16px] leading-6 text-error">
            Earlier training ideas could not be loaded.
          </p>
        ) : null}
        {asking ? (
          <div
            aria-hidden="true"
            className="mt-4 h-48 rounded-[14px] bg-surface-subtle"
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
          <details className="group mt-6">
            <summary
              className={`flex min-h-11 cursor-pointer list-none items-center rounded-lg text-[16px] font-semibold underline underline-offset-4 [&::-webkit-details-marker]:hidden ${focus}`}
            >
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

      <section aria-label="Delete video" className="border-t border-line pt-6">
        {confirmDelete ? (
          <div
            role="alertdialog"
            aria-labelledby="delete-practice-title"
            aria-describedby="delete-practice-body"
            className="rounded-xl border border-error bg-error-soft p-4"
          >
            <h2
              id="delete-practice-title"
              className="text-[17px] font-semibold text-ink"
            >
              Delete this video?
            </h2>
            <p
              id="delete-practice-body"
              className="mt-2 text-[16px] leading-6 text-ink"
            >
              The video and its training ideas are removed for good.
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
                className={`inline-flex min-h-11 items-center justify-center rounded-lg bg-error px-4 text-[16px] font-semibold text-white disabled:opacity-45 ${focus}`}
              >
                {deleting ? "Deleting…" : "Delete video"}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                disabled={deleting}
                className={`${secondaryButton} bg-surface`}
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
            className={`inline-flex min-h-11 items-center rounded-lg px-1 text-[16px] font-semibold text-error underline-offset-4 hover:underline ${focus}`}
          >
            Delete this video
          </button>
        )}
      </section>
    </div>
  );
}
