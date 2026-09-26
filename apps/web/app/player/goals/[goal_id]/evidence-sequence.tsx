"use client";

import { ArrowLeft, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ClipUrl,
  EvidenceItem,
  EvidenceSet,
  PlayerReflection,
} from "../../../../lib/api";
import { ReflectionEditor } from "../../reflection-editor";
import { backLink } from "../../ui";

type SignedClip = ClipUrl & { judgmentId: string };

const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const button = `inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-lg border border-control-border px-4 text-[16px] font-semibold transition-[background-color,transform] duration-150 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 disabled:active:scale-100 ${focus}`;

function sharedDate(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}

async function signClip(item: EvidenceItem, signal: AbortSignal) {
  const response = await fetch(
    `/api/player/judgments/${item.judgment_id}/clip-url`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_published_revision_id: item.published_revision_id,
      }),
      cache: "no-store",
      signal,
    },
  );
  if (response.status === 409) return { changed: true as const };
  if (!response.ok) throw new Error("clip-unavailable");
  const data = (await response.json()) as ClipUrl;
  if (data.published_revision_id !== item.published_revision_id) {
    return { changed: true as const };
  }
  return { changed: false as const, data };
}

export function EvidenceSequence({
  goalId,
  goalTitle,
  playerId,
  initialEvidence,
  initialReflections,
  reflectionsLoaded,
  initialPublicationId,
  initialJudgmentId,
}: {
  goalId: string;
  goalTitle: string;
  playerId: string;
  initialEvidence: EvidenceSet[];
  initialReflections: PlayerReflection[];
  reflectionsLoaded: boolean;
  initialPublicationId?: string;
  initialJudgmentId?: string;
}) {
  const initialSet =
    initialEvidence.find(
      (set) => set.publication_id === initialPublicationId,
    ) ?? initialEvidence[0];
  const [evidence, setEvidence] = useState(initialEvidence);
  const [reflections, setReflections] = useState(initialReflections);
  const [reflectionDataAvailable, setReflectionDataAvailable] =
    useState(reflectionsLoaded);
  const [publicationId, setPublicationId] = useState(
    initialSet?.publication_id,
  );
  const [clipIndex, setClipIndex] = useState(() => {
    const requested = initialSet?.items.findIndex(
      (item) => item.judgment_id === initialJudgmentId,
    );
    return requested !== undefined && requested >= 0 ? requested : 0;
  });
  const [signed, setSigned] = useState<SignedClip | null>(null);
  const [nextSigned, setNextSigned] = useState<SignedClip | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [online, setOnline] = useState(true);
  const videoRef = useRef<HTMLVideoElement>(null);
  const resumeRef = useRef<{ time: number; playing: boolean } | null>(null);

  const selectedSet = useMemo(
    () =>
      evidence.find((set) => set.publication_id === publicationId) ??
      evidence[0],
    [evidence, publicationId],
  );
  const item = selectedSet?.items[clipIndex];
  const nextItem = selectedSet?.items[clipIndex + 1];
  const reflection = item
    ? (reflections.find((value) => value.judgment_id === item.judgment_id) ??
      null)
    : null;

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  useEffect(() => {
    if (!selectedSet) return;
    if (clipIndex >= selectedSet.items.length) setClipIndex(0);
  }, [clipIndex, selectedSet]);

  const refreshWholeSet = useCallback(async () => {
    setSigned(null);
    setNextSigned(null);
    setLoading(true);
    setError(null);
    try {
      const [response, reflectionResponse] = await Promise.all([
        fetch(`/api/player/goals/${goalId}/evidence`, { cache: "no-store" }),
        fetch("/api/player/reflections", { cache: "no-store" }).catch(
          () => null,
        ),
      ]);
      if (!response.ok) throw new Error("evidence-unavailable");
      const replacement = (await response.json()) as EvidenceSet[];
      const nextSet =
        replacement.find((set) => set.publication_id === publicationId) ??
        replacement[0];
      setEvidence(replacement);
      setPublicationId(nextSet?.publication_id);
      setClipIndex((current) =>
        nextSet ? Math.min(current, nextSet.items.length - 1) : 0,
      );
      if (reflectionResponse?.ok) {
        setReflections((await reflectionResponse.json()) as PlayerReflection[]);
        setReflectionDataAvailable(true);
      } else {
        setReflectionDataAvailable(false);
      }
    } catch {
      setError(
        "Your clips changed, but the new set could not be loaded. Try again.",
      );
    } finally {
      setLoading(false);
    }
  }, [goalId, publicationId]);

  useEffect(() => {
    setSigned(null);
    setNextSigned(null);
    setError(null);
    if (!item) return;
    const controller = new AbortController();
    setLoading(true);
    signClip(item, controller.signal)
      .then(async (result) => {
        if (result.changed) {
          await refreshWholeSet();
          return;
        }
        setSigned({ ...result.data, judgmentId: item.judgment_id });
      })
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(
            "This clip needs a connection. Try again when you’re online.",
          );
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [item, refreshWholeSet]);

  // Only next clip gets speculative work, and its element requests metadata.
  useEffect(() => {
    setNextSigned(null);
    if (!nextItem || !signed) return;
    const controller = new AbortController();
    signClip(nextItem, controller.signal)
      .then(async (result) => {
        if (result.changed) {
          await refreshWholeSet();
          return;
        }
        setNextSigned({ ...result.data, judgmentId: nextItem.judgment_id });
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [nextItem, refreshWholeSet, signed]);

  // Refresh before five-minute expiry and restore playhead/play state.
  useEffect(() => {
    if (
      !signed ||
      !item ||
      signed.published_revision_id !== item.published_revision_id
    )
      return;
    const controller = new AbortController();
    const timer = window.setTimeout(
      () => {
        const video = videoRef.current;
        resumeRef.current = video
          ? { time: video.currentTime, playing: !video.paused }
          : null;
        signClip(item, controller.signal)
          .then(async (result) => {
            if (result.changed) {
              await refreshWholeSet();
              return;
            }
            setSigned({ ...result.data, judgmentId: item.judgment_id });
          })
          .catch(() =>
            setError(
              "This clip needs a connection. Reload when you’re online.",
            ),
          );
      },
      Math.max(30, signed.expires_in - 60) * 1000,
    );
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [item, refreshWholeSet, signed]);

  function restorePlayback() {
    const resume = resumeRef.current;
    const video = videoRef.current;
    if (!resume || !video) return;
    video.currentTime = Math.min(resume.time, video.duration || resume.time);
    if (resume.playing) void video.play().catch(() => undefined);
    resumeRef.current = null;
  }

  function handlePlaybackError() {
    const video = videoRef.current;
    resumeRef.current = video
      ? { time: video.currentTime, playing: !video.paused }
      : null;
    setSigned(null);
    setError("This clip couldn’t play. Check your connection and try again.");
  }

  if (!selectedSet || !item) {
    return (
      <section aria-labelledby="goal-title">
        <Link href="/player" className={backLink}>
          <ArrowLeft size={20} strokeWidth={2} aria-hidden="true" />
          Home
        </Link>
        <h1
          id="goal-title"
          className="mt-4 font-display text-[28px] leading-[1.05] md:text-[34px]"
        >
          {goalTitle}
        </h1>
        <p className="mt-4 text-[16px] leading-6">
          These clips are no longer available.
        </p>
      </section>
    );
  }

  const usableSigned =
    signed?.judgmentId === item.judgment_id &&
    signed.published_revision_id === item.published_revision_id
      ? signed
      : null;
  const usableNext =
    nextItem &&
    nextSigned?.judgmentId === nextItem.judgment_id &&
    nextSigned.published_revision_id === nextItem.published_revision_id
      ? nextSigned
      : null;

  const reflectionBlock = reflectionDataAvailable ? (
    <ReflectionEditor
      key={item.judgment_id}
      playerId={playerId}
      judgmentId={item.judgment_id}
      initialReflection={reflection}
      evidenceAvailable
      onSkip={() => {
        if (clipIndex < selectedSet.items.length - 1) {
          setClipIndex((current) => current + 1);
        } else {
          window.location.assign("/player");
        }
      }}
      onChange={(changed) =>
        setReflections((current) => [
          ...current.filter((value) => value.judgment_id !== item.judgment_id),
          ...(changed ? [changed] : []),
        ])
      }
    />
  ) : (
    <section
      aria-label="Your reflection"
      className="mt-6 rounded-xl border border-line bg-surface p-4"
    >
      <p role="alert" className="text-[14px] leading-5 text-muted">
        Your reflection could not be loaded. You can still watch this clip.
      </p>
    </section>
  );

  return (
    <article aria-labelledby="goal-title" aria-busy={loading}>
      <Link href="/player" className={backLink}>
        <ArrowLeft size={20} strokeWidth={2} aria-hidden="true" />
        Home
      </Link>
      <header className="mt-3">
        <p className="text-[14px] font-semibold text-muted">
          What you’re working on
        </p>
        <h1
          id="goal-title"
          className="mt-1 font-display text-[28px] leading-[1.05] text-balance md:text-[34px]"
        >
          {goalTitle}
        </h1>
      </header>

      {evidence.length > 1 ? (
        <nav aria-label="Games" className="mt-5">
          <ul className="flex flex-wrap gap-2">
            {evidence.map((set) => {
              const current = set.publication_id === selectedSet.publication_id;
              return (
                <li key={set.publication_id}>
                  <button
                    type="button"
                    aria-pressed={current}
                    onClick={() => {
                      setPublicationId(set.publication_id);
                      setClipIndex(0);
                    }}
                    className={`inline-flex min-h-11 items-center rounded-full border px-4 text-[15px] font-semibold transition-colors duration-150 ${focus} ${
                      current
                        ? "border-signal bg-signal-soft text-ink"
                        : "border-control-border text-ink-2 hover:bg-surface-subtle"
                    }`}
                  >
                    {set.game_label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      ) : null}

      <section
        aria-labelledby="clip-title"
        className="mt-6 grid gap-6 lg:grid-cols-12 lg:grid-rows-[auto_1fr] lg:gap-x-8 lg:gap-y-2"
      >
        <div className="min-w-0 lg:col-span-5 lg:col-start-8 lg:row-start-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-[13px] text-muted tabular-nums">
            <span>
              {selectedSet.game_label}, shared{" "}
              {sharedDate(selectedSet.published_at)}
            </span>
            <span aria-live="polite" className="font-semibold text-ink-2">
              Clip {clipIndex + 1} of {selectedSet.items.length}
            </span>
          </div>
          <p className="mt-4 flex items-center gap-2 text-[15px] font-semibold leading-[1.35] text-action">
            <span
              aria-hidden="true"
              className={`inline-block size-3 rounded-full border-2 border-action ${
                item.verdict === "applied" ? "bg-action" : ""
              }`}
            />
            {item.verdict_copy}
          </p>
          <h2
            id="clip-title"
            className="mt-2 text-[20px] font-semibold leading-[1.3] md:text-[22px]"
          >
            {item.comment}
          </h2>
          <p className="mt-2 text-[14px] text-muted">
            {item.coach_display_name}
          </p>
        </div>

        <div className="min-w-0 lg:col-span-7 lg:col-start-1 lg:row-span-2 lg:row-start-1">
          <div className="relative aspect-video overflow-hidden rounded-[14px] bg-night">
            {usableSigned ? (
              // biome-ignore lint/a11y/useMediaCaption: show a verified caption track when one exists; never fabricate one.
              <video
                ref={videoRef}
                key={usableSigned.url}
                src={usableSigned.url}
                aria-label={`Clip ${clipIndex + 1} of ${selectedSet.items.length}`}
                className="size-full bg-night object-contain"
                controls
                playsInline
                preload="metadata"
                onLoadedMetadata={restorePlayback}
                onError={handlePlaybackError}
              />
            ) : (
              <div
                className="flex size-full items-center justify-center px-5 text-center text-[16px] text-on-night"
                role="status"
              >
                {loading ? "Loading clip…" : "Clip unavailable."}
              </div>
            )}
          </div>

          {!online ? (
            <p role="status" className="mt-3 text-[16px] leading-6 text-ink-2">
              You’re offline. This clip needs a connection.
            </p>
          ) : null}
          {error ? (
            <div
              role="alert"
              className="mt-3 rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
            >
              <p>{error}</p>
              <button
                type="button"
                onClick={() => void refreshWholeSet()}
                className={`mt-2 min-h-11 font-semibold underline underline-offset-4 ${focus}`}
              >
                Try again
              </button>
            </div>
          ) : null}

          <nav aria-label="Clip navigation" className="mt-4 flex gap-3">
            <button
              type="button"
              className={`${button} flex-1`}
              disabled={clipIndex === 0}
              onClick={() => setClipIndex((current) => current - 1)}
            >
              <ChevronLeft size={20} strokeWidth={2} aria-hidden="true" />
              Previous
            </button>
            <button
              type="button"
              className={`${button} flex-1 border-action bg-action text-on-action hover:bg-action-hover`}
              disabled={clipIndex === selectedSet.items.length - 1}
              onClick={() => setClipIndex((current) => current + 1)}
            >
              Next
              <ChevronRight size={20} strokeWidth={2} aria-hidden="true" />
            </button>
          </nav>

          {selectedSet.items.length > 1 ? (
            <ol
              aria-label="Clips in this game"
              className="mt-3 flex flex-wrap gap-1"
            >
              {selectedSet.items.map((clip, index) => (
                <li key={clip.judgment_id}>
                  <button
                    type="button"
                    aria-current={index === clipIndex ? "true" : undefined}
                    aria-label={`Clip ${index + 1}, ${clip.verdict_copy}`}
                    onClick={() => setClipIndex(index)}
                    className={`flex size-11 flex-col items-center justify-center gap-1 rounded-lg text-[13px] font-semibold tabular-nums transition-colors duration-150 ${focus} ${
                      index === clipIndex
                        ? "bg-surface-subtle text-ink"
                        : "text-muted hover:bg-surface-subtle"
                    }`}
                  >
                    {index + 1}
                    <span
                      aria-hidden="true"
                      className={`size-2 rounded-full border-[1.5px] border-action ${
                        clip.verdict === "applied" ? "bg-action" : ""
                      }`}
                    />
                  </button>
                </li>
              ))}
            </ol>
          ) : null}
        </div>

        <div className="min-w-0 lg:col-span-5 lg:col-start-8 lg:row-start-2">
          {reflectionBlock}
        </div>

        {usableNext ? (
          <video
            src={usableNext.url}
            preload="metadata"
            muted
            tabIndex={-1}
            aria-hidden="true"
            className="pointer-events-none absolute size-px opacity-0"
          />
        ) : null}
      </section>
    </article>
  );
}
