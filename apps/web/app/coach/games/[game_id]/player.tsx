"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Observation, PlaybackUrl, Timeline } from "../../../../lib/api";
import {
  isTextEntryTarget,
  reviewShortcut,
  validClipBounds,
} from "../../../../lib/marking";
import {
  formatClock,
  type SpriteLayout,
  spriteLayout,
  tileOffset,
} from "../../../../lib/timeline";
import { focus, metadata, panel, secondary } from "../../ui";

/**
 * The coach playback wrapper.
 *
 * ADR 0001: one progressive 720p MP4 played by the browser's own element over
 * HTTP Range. There is no streaming library here on purpose.
 *
 * The signed URL lasts fifteen minutes and the review session lasts longer, so
 * this refreshes it before expiry and restores the exact playhead afterwards.
 * A coach must never lose their place because a signature aged out.
 */

/** Refresh with a margin, so a seek never races the expiry. */
const REFRESH_MARGIN_SECONDS = 120;

async function readJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, cache: "no-store" });
  if (!response.ok) throw new Error(String(response.status));
  return (await response.json()) as T;
}

export function CoachPlayer({
  videoId,
  label,
  playerId,
  initialObservations = [],
}: {
  videoId: string;
  label: string;
  playerId?: string;
  initialObservations?: Observation[];
}) {
  const video = useRef<HTMLVideoElement>(null);
  const requestedTimeSeconds = useRef(0);
  const seekingToSeconds = useRef<number | null>(null);
  const savingClip = useRef(false);
  const [playback, setPlayback] = useState<PlaybackUrl | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [message, setMessage] = useState("");
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [inMs, setInMs] = useState<number | null>(null);
  const [observations, setObservations] =
    useState<Observation[]>(initialObservations);
  const [pendingClip, setPendingClip] = useState<{
    startMs: number;
    endMs: number;
  } | null>(null);
  const [saveState, setSaveState] = useState("Ready");
  const [markingMessage, setMarkingMessage] = useState("");

  const load = useCallback(async (): Promise<void> => {
    const [next, line] = await Promise.all([
      readJson<PlaybackUrl>(`/api/videos/${videoId}/playback-url`, {
        method: "POST",
      }),
      // The sheet URLs carry the same fifteen-minute expiry as the playback
      // URL. Re-signing one without the other would leave a working video with
      // a scrubber whose thumbnails had quietly started 403ing.
      readJson<Timeline>(`/api/videos/${videoId}/timeline`).catch(() => null),
    ]);
    if (line) setTimeline(line);
    setPlayback((previous) => {
      // Preserve the playhead across a refresh: assigning a new src resets it.
      const element = video.current;
      if (element && previous) {
        const at = element.currentTime;
        const wasPlaying = !element.paused;
        queueMicrotask(() => {
          if (!video.current) return;
          requestedTimeSeconds.current = at;
          seekingToSeconds.current = at;
          video.current.currentTime = at;
          if (wasPlaying) void video.current.play().catch(() => undefined);
        });
      }
      return next;
    });
  }, [videoId]);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        await load();
      } catch {
        if (alive)
          setMessage("Shoulder could not open this video. Reload the page.");
      }
    })();
    return () => {
      alive = false;
    };
  }, [load]);

  // Re-sign before the URL ages out, for as long as the screen is open.
  useEffect(() => {
    if (!playback) return;
    const seconds = Math.max(60, playback.expires_in - REFRESH_MARGIN_SECONDS);
    const timer = window.setTimeout(() => {
      void load().catch(() =>
        setMessage("Playback expired. Reload the page to continue."),
      );
    }, seconds * 1000);
    return () => window.clearTimeout(timer);
  }, [playback, load]);

  const durationMs = playback?.duration_ms ?? 0;
  const layout: SpriteLayout | null =
    durationMs > 0 ? spriteLayout(durationMs) : null;

  const seekBy = useCallback((deltaSeconds: number) => {
    const element = video.current;
    if (!element) return;
    const next = Math.max(
      0,
      Math.min(
        element.duration || 0,
        requestedTimeSeconds.current + deltaSeconds,
      ),
    );
    requestedTimeSeconds.current = next;
    seekingToSeconds.current = next;
    element.currentTime = next;
    setCurrentMs(next * 1000);
  }, []);

  const toggle = useCallback(() => {
    const element = video.current;
    if (!element) return;
    if (element.paused) void element.play().catch(() => undefined);
    else element.pause();
  }, []);

  const markIn = useCallback(() => {
    if (!video.current || !playerId || savingClip.current) return;
    const at = Math.round(video.current.currentTime * 1000);
    requestedTimeSeconds.current = at / 1000;
    setInMs(at);
    setSaveState("Ready");
    setMarkingMessage(`In point ${formatClock(at)}`);
  }, [playerId]);

  const markOut = useCallback(async () => {
    if (savingClip.current) return;
    if (!video.current || !playerId || inMs === null) {
      setSaveState("Needs attention");
      setMarkingMessage("Set an in point first.");
      return;
    }
    const outMs = Math.round(video.current.currentTime * 1000);
    if (!validClipBounds(inMs, outMs, durationMs)) {
      setSaveState("Needs attention");
      setMarkingMessage("Choose an out point after the in point.");
      return;
    }
    savingClip.current = true;
    setSaveState("Saving");
    setPendingClip({ startMs: inMs, endMs: outMs });
    try {
      const saved = await readJson<Observation>(
        `/api/videos/${videoId}/observations`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            player_id: playerId,
            t_start_ms: inMs,
            t_end_ms: outMs,
          }),
        },
      );
      setObservations((current) => [...current, saved]);
      setPendingClip(null);
      setInMs(null);
      setSaveState("Saved");
      setMarkingMessage("");
    } catch {
      setPendingClip(null);
      setSaveState("Needs attention");
      setMarkingMessage("Clip was not saved. Try again.");
    } finally {
      savingClip.current = false;
    }
  }, [durationMs, inMs, playerId, videoId]);

  // `docs/05-ui.md` keyboard map. Text fields keep their own keys.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const action = reviewShortcut(
        event.key,
        event.shiftKey,
        isTextEntryTarget(target),
      );
      if (!action) return;
      event.preventDefault();
      switch (action.type) {
        case "toggle-playback":
          toggle();
          break;
        case "seek":
          seekBy(action.seconds);
          break;
        case "mark-in":
          markIn();
          break;
        case "mark-out":
          void markOut();
          break;
        case "focus-video":
          video.current?.focus();
          break;
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [markIn, markOut, seekBy, toggle]);

  const preview =
    layout && hover !== null && timeline ? tileOffset(hover, layout) : null;
  const previewSheet =
    preview && timeline
      ? timeline.sheets.find((sheet) => sheet.sheet === preview.sheet)
      : undefined;

  return (
    <section className={`${panel} p-5`} aria-labelledby="player-heading">
      <h2
        id="player-heading"
        className="text-[17px] font-semibold leading-[1.35]"
      >
        Match video
      </h2>
      <p className={`${metadata} mt-1`}>{label}</p>

      {message ? (
        <p role="alert" className="mt-4 text-[15px] leading-[1.5]">
          {message}
        </p>
      ) : null}

      {playback ? (
        <>
          {/* A fixed 16:9 box, so the frame never shifts the page as it loads. */}
          <div className="mt-4 aspect-video w-full bg-ink">
            <video
              ref={video}
              tabIndex={0}
              src={playback.url}
              preload="metadata"
              playsInline
              controls={false}
              className="size-full"
              onTimeUpdate={(event) => {
                if (seekingToSeconds.current === null)
                  requestedTimeSeconds.current =
                    event.currentTarget.currentTime;
                setCurrentMs(event.currentTarget.currentTime * 1000);
              }}
              onSeeked={(event) => {
                const desired = seekingToSeconds.current;
                if (
                  desired !== null &&
                  Math.abs(event.currentTarget.currentTime - desired) > 0.05
                ) {
                  // WebKit can finish an older seek after a newer keyboard
                  // seek. Re-apply the latest requested position once.
                  event.currentTarget.currentTime = desired;
                  return;
                }
                seekingToSeconds.current = null;
                requestedTimeSeconds.current = event.currentTarget.currentTime;
                setCurrentMs(event.currentTarget.currentTime * 1000);
              }}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
            >
              <track kind="captions" />
            </video>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={toggle}
              className={secondary}
              aria-label={playing ? "Pause" : "Play"}
            >
              {playing ? "Pause" : "Play"}
            </button>
            <button
              type="button"
              onClick={() => seekBy(-10)}
              className={secondary}
              aria-label="Back ten seconds"
            >
              −10s
            </button>
            <button
              type="button"
              onClick={() => seekBy(10)}
              className={secondary}
              aria-label="Forward ten seconds"
            >
              +10s
            </button>
            <p className={`${metadata} tabular-nums`} aria-live="off">
              {formatClock(currentMs)} / {formatClock(durationMs)}
            </p>
            {playerId ? (
              <>
                <button type="button" onClick={markIn} className={secondary}>
                  Set clip in (I)
                </button>
                <button
                  type="button"
                  onClick={() => void markOut()}
                  className={secondary}
                >
                  Set clip out (O)
                </button>
                <p role="status" aria-live="polite" className={metadata}>
                  {saveState}
                </p>
              </>
            ) : null}
          </div>

          <div className="relative mt-3">
            {playerId ? (
              <div aria-hidden="true" className="absolute inset-x-0 top-0 h-1">
                {observations.map((observation) => (
                  <span
                    key={observation.id}
                    className="absolute h-1 min-w-px bg-ink"
                    style={{
                      left: `${(observation.t_start_ms / durationMs) * 100}%`,
                      width: `${((observation.t_end_ms - observation.t_start_ms) / durationMs) * 100}%`,
                    }}
                  />
                ))}
                {inMs !== null ? (
                  <span
                    className="absolute h-2 w-0.5 bg-ink"
                    style={{ left: `${(inMs / durationMs) * 100}%` }}
                  />
                ) : null}
              </div>
            ) : null}
            <label htmlFor="scrubber" className="sr-only">
              Seek through the match
            </label>
            <input
              id="scrubber"
              type="range"
              min={0}
              max={Math.max(0, Math.round(durationMs))}
              step={100}
              value={Math.round(currentMs)}
              aria-valuetext={formatClock(currentMs)}
              onChange={(event) => {
                const at = Number(event.target.value);
                requestedTimeSeconds.current = at / 1000;
                seekingToSeconds.current = at / 1000;
                setCurrentMs(at);
                if (video.current) video.current.currentTime = at / 1000;
              }}
              onMouseMove={(event) => {
                const box = event.currentTarget.getBoundingClientRect();
                const ratio = (event.clientX - box.left) / box.width;
                setHover(Math.max(0, Math.min(1, ratio)) * durationMs);
              }}
              onMouseLeave={() => setHover(null)}
              className={`w-full ${focus}`}
            />
          </div>

          {previewSheet && preview && timeline ? (
            <div
              aria-hidden="true"
              className="mt-2 border border-line"
              style={{
                width: timeline.tile_width,
                height: timeline.tile_height,
                backgroundImage: `url(${previewSheet.url})`,
                backgroundPosition: `${preview.x}px ${preview.y}px`,
              }}
            />
          ) : null}

          <p className={`${metadata} mt-2`}>
            Space plays and pauses. J and L jump ten seconds. Arrow keys step
            one second, or ten with Shift.
            {playerId ? " I sets the clip in; O saves the clip out." : ""}
          </p>

          {playerId ? (
            <section className="mt-5 border-t border-line pt-4">
              <h3 className="text-[15px] font-semibold">Marked clips</h3>
              {markingMessage ? (
                <p className={`${metadata} mt-2`}>{markingMessage}</p>
              ) : null}
              {observations.length || pendingClip ? (
                <ul aria-label="Marked clips" className="mt-2 space-y-2">
                  {observations.map((observation) => (
                    <li
                      key={observation.id}
                      className={`${metadata} rounded-lg border border-line px-3 py-2 tabular-nums`}
                    >
                      {formatClock(observation.t_start_ms)}–
                      {formatClock(observation.t_end_ms)} · Manual
                    </li>
                  ))}
                  {pendingClip ? (
                    <li
                      className={`${metadata} rounded-lg border border-line px-3 py-2 tabular-nums`}
                    >
                      {formatClock(pendingClip.startMs)}–
                      {formatClock(pendingClip.endMs)} · Manual · Saving
                    </li>
                  ) : null}
                </ul>
              ) : (
                <p className={`${metadata} mt-2`}>
                  No clips marked for this player yet.
                </p>
              )}
            </section>
          ) : null}
        </>
      ) : message ? null : (
        <p className={`${metadata} mt-4`}>Opening the match video…</p>
      )}
    </section>
  );
}
