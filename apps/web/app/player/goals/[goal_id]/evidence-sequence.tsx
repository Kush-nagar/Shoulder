"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ClipUrl, EvidenceItem, EvidenceSet } from "../../../../lib/api";

type SignedClip = ClipUrl & { judgmentId: string };

const focus =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
const button = `inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-line-strong px-4 text-[16px] font-semibold disabled:cursor-not-allowed disabled:opacity-45 ${focus}`;

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
  initialEvidence,
  initialPublicationId,
}: {
  goalId: string;
  goalTitle: string;
  initialEvidence: EvidenceSet[];
  initialPublicationId?: string;
}) {
  const [evidence, setEvidence] = useState(initialEvidence);
  const [publicationId, setPublicationId] = useState(
    initialEvidence.some((set) => set.publication_id === initialPublicationId)
      ? initialPublicationId
      : initialEvidence[0]?.publication_id,
  );
  const [clipIndex, setClipIndex] = useState(0);
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
      const response = await fetch(`/api/player/goals/${goalId}/evidence`, {
        cache: "no-store",
      });
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

  if (!selectedSet || !item) {
    return (
      <section aria-labelledby="goal-title">
        <Link
          href="/player"
          className={`inline-flex min-h-11 items-center text-[16px] underline underline-offset-4 ${focus}`}
        >
          Back to your clips
        </Link>
        <h1
          id="goal-title"
          className="mt-6 text-[26px] font-semibold leading-[1.15]"
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

  return (
    <article aria-labelledby="goal-title" aria-busy={loading}>
      <Link
        href="/player"
        className={`inline-flex min-h-11 items-center text-[16px] underline underline-offset-4 ${focus}`}
      >
        Back to your clips
      </Link>
      <header className="mt-5 border-l-2 border-action pl-4">
        <p className="text-[14px] font-semibold leading-[1.35] text-muted">
          What you’re working on
        </p>
        <h1
          id="goal-title"
          className="mt-2 text-[26px] font-semibold leading-[1.15]"
        >
          {goalTitle}
        </h1>
      </header>

      <section aria-labelledby="clip-title" className="mt-8">
        <p className="text-[14px] font-semibold leading-[1.35] text-action">
          {item.verdict_copy}
        </p>
        <h2
          id="clip-title"
          className="mt-2 text-[21px] font-semibold leading-[1.25]"
        >
          {item.comment}
        </h2>
        <div className="relative mt-5 aspect-video overflow-hidden rounded-[14px] bg-ink">
          {usableSigned ? (
            // biome-ignore lint/a11y/useMediaCaption: show a verified caption track when one exists; never fabricate one.
            <video
              ref={videoRef}
              key={usableSigned.url}
              src={usableSigned.url}
              aria-label={`Clip ${clipIndex + 1} of ${selectedSet.items.length}`}
              className="size-full bg-ink object-contain"
              controls
              playsInline
              preload="metadata"
              onLoadedMetadata={restorePlayback}
            />
          ) : (
            <div
              className="flex size-full items-center justify-center px-5 text-center text-[16px] text-paper"
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

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[13px] text-muted">
          <span>
            {selectedSet.game_label} · Shared{" "}
            {sharedDate(selectedSet.published_at)}
          </span>
          <span aria-live="polite">
            Clip {clipIndex + 1} of {selectedSet.items.length}
          </span>
        </div>

        <nav aria-label="Clip navigation" className="mt-5 flex gap-3">
          <button
            type="button"
            className={`${button} flex-1`}
            disabled={clipIndex === 0}
            onClick={() => setClipIndex((current) => current - 1)}
          >
            Previous
          </button>
          <button
            type="button"
            className={`${button} flex-1 bg-action text-white hover:bg-action-hover`}
            disabled={clipIndex === selectedSet.items.length - 1}
            onClick={() => setClipIndex((current) => current + 1)}
          >
            Next
          </button>
        </nav>

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
