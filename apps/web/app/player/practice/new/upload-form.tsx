"use client";

import { Camera, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { formatBytes } from "../../../../lib/upload";
import { chip } from "../../ui";
import { clock, focus, primaryButton, secondaryButton } from "../format";
import type { PracticeUploadStart } from "../types";

const MAX_BYTES = 500 * 1024 * 1024;
const MAX_MS = 10 * 60 * 1000;
const TYPES: Record<string, string> = {
  mp4: "video/mp4",
  m4v: "video/mp4",
  mov: "video/quicktime",
  webm: "video/webm",
};
const ALLOWED = new Set(Object.values(TYPES));

type Phase = "idle" | "uploading" | "finishing" | "done";
type Picked = { file: File; type: string; durationMs: number | null };

/** Browsers disagree on video MIME types; the extension is the fallback. */
function contentType(file: File): string | null {
  if (ALLOWED.has(file.type)) return file.type;
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return TYPES[extension] ?? null;
}

function readDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const video = document.createElement("video");
    const url = URL.createObjectURL(file);
    const finish = (value: number | null) => {
      URL.revokeObjectURL(url);
      window.clearTimeout(timer);
      resolve(value);
    };
    // Some phone codecs never load in desktop browsers; size still gates it.
    const timer = window.setTimeout(() => finish(null), 4000);
    video.preload = "metadata";
    video.onloadedmetadata = () =>
      finish(
        Number.isFinite(video.duration)
          ? Math.max(1, Math.round(video.duration * 1000))
          : null,
      );
    video.onerror = () => finish(null);
    video.src = url;
  });
}

function put(
  url: string,
  file: File,
  type: string,
  onProgress: (loaded: number) => void,
  xhrRef: { current: XMLHttpRequest | null },
): Promise<void> {
  // XHR, not fetch: fetch cannot report upload progress.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;
    xhr.open("PUT", url);
    xhr.setRequestHeader("Content-Type", type);
    xhr.upload.onprogress = (event) => onProgress(event.loaded);
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve()
        : reject(new Error("put-failed"));
    xhr.onerror = () => reject(new Error("put-failed"));
    xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
    xhr.send(file);
  });
}

function discard(id: string | null) {
  if (!id) return;
  void fetch(`/api/player/practice/${id}`, { method: "DELETE" }).catch(
    () => undefined,
  );
}

const SUGGESTIONS = ["Scanning", "First touch", "Passing", "Half-turn"];

export function UploadForm({ initialTitle = "" }: { initialTitle?: string }) {
  const router = useRouter();
  const [picked, setPicked] = useState<Picked | null>(null);
  const [title, setTitle] = useState(initialTitle);
  const [phase, setPhase] = useState<Phase>("idle");
  const [loaded, setLoaded] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);
  const pendingId = useRef<string | null>(null);
  const busy = phase === "uploading" || phase === "finishing";

  // Leaving mid-upload stops the transfer and drops the unfinished row.
  useEffect(
    () => () => {
      xhrRef.current?.abort();
      discard(pendingId.current);
    },
    [],
  );

  async function choose(file: File | undefined) {
    setError(null);
    setPicked(null);
    if (!file) return;
    const type = contentType(file);
    if (!type) {
      setError("Choose an MP4, MOV, or WebM video.");
      return;
    }
    if (file.size < 1 || file.size > MAX_BYTES) {
      setError(
        "This video is over 500 MB. Film a shorter clip, then try again.",
      );
      return;
    }
    const durationMs = await readDuration(file);
    if (durationMs !== null && durationMs > MAX_MS) {
      setError(
        "This video is longer than 10 minutes. Trim it, then try again.",
      );
      return;
    }
    setPicked({ file, type, durationMs });
  }

  async function upload() {
    if (!picked || busy) return;
    discard(pendingId.current);
    pendingId.current = null;
    setError(null);
    setLoaded(0);
    setPhase("uploading");
    try {
      const start = await fetch("/api/player/practice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim() || null,
          content_type: picked.type,
          size_bytes: picked.file.size,
        }),
        cache: "no-store",
      });
      if (!start.ok) {
        throw new Error(start.status === 422 ? "rejected" : "start-failed");
      }
      const ticket = (await start.json()) as PracticeUploadStart;
      pendingId.current = ticket.id;
      await put(ticket.upload_url, picked.file, picked.type, setLoaded, xhrRef);
      setPhase("finishing");
      const complete = await fetch(
        `/api/player/practice/${ticket.id}/complete`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ duration_ms: picked.durationMs }),
          cache: "no-store",
        },
      );
      if (!complete.ok) throw new Error("complete-failed");
      pendingId.current = null;
      setPhase("done");
      router.push(`/player/practice/${ticket.id}`);
    } catch (reason) {
      setPhase("idle");
      if (reason instanceof DOMException && reason.name === "AbortError") {
        setError("Upload cancelled. Nothing was saved.");
      } else if (reason instanceof Error && reason.message === "rejected") {
        setError(
          "Shoulder can't take this video. Use MP4, MOV, or WebM under 500 MB and 10 minutes.",
        );
      } else {
        setError(
          "The upload stopped. Check your connection, then try again. Your video is still on your phone.",
        );
      }
    } finally {
      xhrRef.current = null;
    }
  }

  function cancel() {
    xhrRef.current?.abort();
    discard(pendingId.current);
    pendingId.current = null;
  }

  const percent = picked ? Math.round((loaded / picked.file.size) * 100) : 0;
  // A label is the visible control; the file input inside stays focusable.
  const pick =
    "relative inline-flex min-h-12 w-full cursor-pointer items-center justify-center gap-2 rounded-lg px-4 text-[16px] font-semibold transition-[background-color,transform] duration-150 ease-out active:scale-[0.98] has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-45 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus";

  return (
    <form
      className="mt-8 space-y-8"
      onSubmit={(event) => {
        event.preventDefault();
        void upload();
      }}
    >
      <div className="space-y-2">
        <label
          htmlFor="practice-title"
          className="block text-[16px] font-semibold"
        >
          Title <span className="font-normal text-muted">(optional)</span>
        </label>
        <input
          id="practice-title"
          type="text"
          value={title}
          maxLength={80}
          disabled={busy}
          autoComplete="off"
          onChange={(event) => setTitle(event.target.value)}
          aria-describedby="practice-title-help"
          className={`block min-h-11 w-full rounded-lg border border-control-border bg-surface px-3 text-[16px] transition-colors duration-150 hover:border-ink-2 ${focus}`}
        />
        <p
          id="practice-title-help"
          className="text-[14px] leading-5 text-muted"
        >
          What you worked on. Tap one to fill it in.
        </p>
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              disabled={busy}
              onClick={() => setTitle(suggestion)}
              aria-pressed={title === suggestion}
              className={`${chip} min-h-11 px-4 text-[15px] transition-colors duration-150 hover:bg-surface-subtle aria-pressed:border-signal aria-pressed:bg-signal-soft aria-pressed:text-ink ${focus}`}
            >
              {suggestion}
            </button>
          ))}
        </div>
      </div>

      <fieldset disabled={busy} className="space-y-3">
        <legend className="text-[16px] font-semibold">Video</legend>
        <div className="rounded-xl border border-dashed border-control-border p-4 md:p-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className={`${pick} bg-ink text-paper hover:bg-ink-2`}>
              <Camera size={20} strokeWidth={2} aria-hidden="true" />
              Record now
              <input
                type="file"
                accept="video/*"
                capture="environment"
                className="sr-only"
                onChange={(event) => void choose(event.target.files?.[0])}
              />
            </label>
            <label
              className={`${pick} border border-control-border bg-surface hover:bg-surface-subtle`}
            >
              <Upload size={20} strokeWidth={2} aria-hidden="true" />
              Choose a video
              <input
                type="file"
                accept="video/*"
                className="sr-only"
                onChange={(event) => void choose(event.target.files?.[0])}
              />
            </label>
          </div>
          <p className="mt-3 text-[14px] leading-5 text-muted">
            MP4, MOV, or WebM. Up to 500 MB and 10 minutes.
          </p>
          {picked ? (
            <p className="mt-3 rounded-lg bg-surface-subtle px-4 py-3 text-[15px] leading-6">
              <span className="block truncate font-semibold">
                {picked.file.name}
              </span>
              <span className="text-muted tabular-nums">
                {formatBytes(picked.file.size)}
                {picked.durationMs ? `, ${clock(picked.durationMs)}` : ""}
              </span>
            </p>
          ) : null}
        </div>
      </fieldset>

      {busy ? (
        <div className="space-y-2" aria-live="polite">
          <div
            role="progressbar"
            aria-label="Upload progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            className="h-2 overflow-hidden rounded-full bg-surface-subtle"
          >
            <div
              className="h-full origin-left rounded-full bg-action transition-transform duration-200 ease-out"
              style={{ transform: `scaleX(${percent / 100})` }}
            />
          </div>
          <p className="text-[15px] leading-6 text-ink-2 tabular-nums">
            {phase === "finishing"
              ? "Checking the upload…"
              : `Uploading ${formatBytes(loaded)} of ${formatBytes(picked?.file.size ?? 0)}. Keep this page open.`}
          </p>
        </div>
      ) : null}

      {error ? (
        <p
          role="alert"
          className="rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
        >
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <button
          type="submit"
          disabled={!picked || busy || phase === "done"}
          className={`${primaryButton} flex-1 sm:flex-none`}
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
        {phase === "uploading" ? (
          <button type="button" onClick={cancel} className={secondaryButton}>
            Cancel upload
          </button>
        ) : null}
      </div>
    </form>
  );
}
