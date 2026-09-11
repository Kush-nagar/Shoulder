"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { PlaybackUrl, Timeline } from "../../../../lib/api";
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
}: {
  videoId: string;
  label: string;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [playback, setPlayback] = useState<PlaybackUrl | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [message, setMessage] = useState("");
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [hover, setHover] = useState<number | null>(null);

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
    element.currentTime = Math.max(
      0,
      Math.min(element.duration || 0, element.currentTime + deltaSeconds),
    );
  }, []);

  const toggle = useCallback(() => {
    const element = video.current;
    if (!element) return;
    if (element.paused) void element.play().catch(() => undefined);
    else element.pause();
  }, []);

  // `docs/05-ui.md` keyboard map. Text fields keep their own keys.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
      )
        return;
      switch (event.key) {
        case " ":
          event.preventDefault();
          toggle();
          break;
        case "ArrowLeft":
          event.preventDefault();
          seekBy(event.shiftKey ? -10 : -1);
          break;
        case "ArrowRight":
          event.preventDefault();
          seekBy(event.shiftKey ? 10 : 1);
          break;
        case "j":
        case "J":
          event.preventDefault();
          seekBy(-10);
          break;
        case "k":
        case "K":
          event.preventDefault();
          toggle();
          break;
        case "l":
        case "L":
          event.preventDefault();
          seekBy(10);
          break;
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [seekBy, toggle]);

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
              src={playback.url}
              preload="metadata"
              playsInline
              controls={false}
              className="size-full"
              onTimeUpdate={(event) =>
                setCurrentMs(event.currentTarget.currentTime * 1000)
              }
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
          </div>

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
              setCurrentMs(at);
              if (video.current) video.current.currentTime = at / 1000;
            }}
            onMouseMove={(event) => {
              const box = event.currentTarget.getBoundingClientRect();
              const ratio = (event.clientX - box.left) / box.width;
              setHover(Math.max(0, Math.min(1, ratio)) * durationMs);
            }}
            onMouseLeave={() => setHover(null)}
            className={`mt-3 w-full ${focus}`}
          />

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
          </p>
        </>
      ) : message ? null : (
        <p className={`${metadata} mt-4`}>Opening the match video…</p>
      )}
    </section>
  );
}
