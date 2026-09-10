"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CONCURRENCY,
  formatBytes,
  inParallel,
  partRange,
  type ResumeHint,
  sameFile,
  storedFraction,
  validateFile,
} from "../../../lib/upload";
import { field, label, metadata, panel, primary, secondary } from "../ui";

/**
 * The resumable upload client.
 *
 * `docs/00-decisions.md` D5: closing the tab pauses an upload, it does not
 * continue it, and the copy here says exactly that. The server is authoritative
 * for what has arrived; `localStorage` holds only enough to recognise the same
 * file again, never a part list the client could act on by itself.
 *
 * Bytes go straight from this component to private object storage through
 * short-lived presigned URLs. They never pass through the BFF or FastAPI.
 */

type UploadState = {
  video_id: string;
  status: string;
  part_size_bytes: number;
  part_count: number;
  parts: { part_number: number; etag: string; size_bytes: number }[];
  missing_part_numbers: number[];
};

type Phase = "idle" | "uploading" | "complete" | "error";

const UPLOADING_NOTE =
  "Keep this tab open while the file uploads. If the connection drops, you can resume the missing parts.";
const COMPLETE_NOTE =
  "Upload complete. It is safe to close this tab while Shoulder prepares the video.";

function storageKey(gameId: string) {
  return `shoulder.upload.${gameId}`;
}

function readHint(gameId: string): ResumeHint | null {
  try {
    const raw = window.localStorage.getItem(storageKey(gameId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ResumeHint;
    return typeof parsed?.video_id === "string" ? parsed : null;
  } catch {
    // A private window or cleared storage is not an error: the coach simply
    // has to reselect the file, which they must do anyway.
    return null;
  }
}

function writeHint(gameId: string, hint: ResumeHint | null) {
  try {
    if (hint)
      window.localStorage.setItem(storageKey(gameId), JSON.stringify(hint));
    else window.localStorage.removeItem(storageKey(gameId));
  } catch {
    // Losing the hint costs a reselect, nothing more.
  }
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      type?: string;
      detail?: string;
    } | null;
    throw new UploadFailure(
      body?.detail ?? "Shoulder could not reach the upload service.",
      body?.type?.split("/").pop() ?? null,
    );
  }
  return (await response.json()) as T;
}

class UploadFailure extends Error {
  slug: string | null;
  constructor(message: string, slug: string | null) {
    super(message);
    this.slug = slug;
  }
}

export function Uploader({
  gameId,
  gameLabel,
}: {
  gameId: string;
  gameLabel: string;
}) {
  const [hint, setHint] = useState<ResumeHint | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");
  const [fileName, setFileName] = useState("");
  const [stored, setStored] = useState(0);
  const [currentPart, setCurrentPart] = useState<number | null>(null);
  const [partsDone, setPartsDone] = useState(0);
  const [partsTotal, setPartsTotal] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const running = useRef(false);

  useEffect(() => {
    setHint(readHint(gameId));
  }, [gameId]);

  // The browser cannot keep uploading once this tab is gone, so warn rather
  // than let the coach believe otherwise.
  useEffect(() => {
    if (phase !== "uploading") return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [phase]);

  const sendMissing = useCallback(async (file: File, videoId: string) => {
    let state = await json<UploadState>(`/api/videos/${videoId}/upload-state`);
    setPartsTotal(state.part_count);
    setPartsDone(state.part_count - state.missing_part_numbers.length);
    setStored(
      storedFraction(
        state.parts.map((part) => part.part_number),
        state.part_size_bytes,
        file.size,
      ),
    );

    await inParallel(
      state.missing_part_numbers,
      CONCURRENCY,
      async (number) => {
        setCurrentPart(number);
        const signed = await json<{
          parts: { part_number: number; url: string; size_bytes: number }[];
        }>(`/api/videos/${videoId}/upload-parts/sign`, {
          method: "POST",
          body: JSON.stringify({ part_numbers: [number] }),
        });
        const { start, end } = partRange(
          number,
          state.part_size_bytes,
          file.size,
        );
        const response = await fetch(signed.parts[0].url, {
          method: "PUT",
          body: file.slice(start, end),
        });
        if (!response.ok)
          throw new UploadFailure(
            "A part of the file did not reach storage. You can resume the missing parts.",
            "part-rejected",
          );
        setPartsDone((done) => done + 1);
        setStored((fraction) =>
          Math.min(1, fraction + (end - start) / file.size),
        );
      },
    );

    // Ask the server what it really holds before claiming the file is there.
    state = await json<UploadState>(`/api/videos/${videoId}/upload-state`);
    if (state.missing_part_numbers.length > 0)
      throw new UploadFailure(
        "Some parts are still missing. Choose the same file again to resume.",
        "upload-incomplete",
      );
    await json(`/api/videos/${videoId}/upload-complete`, { method: "POST" });
  }, []);

  const start = useCallback(
    async (file: File, existing: ResumeHint | null) => {
      if (running.current) return;
      running.current = true;
      setPhase("uploading");
      setMessage("");
      setFileName(file.name);
      try {
        let videoId = existing?.video_id ?? null;
        if (!videoId) {
          const session = await json<{
            video_id: string;
            part_count: number;
          }>(`/api/games/${gameId}/videos/uploads`, {
            method: "POST",
            body: JSON.stringify({
              filename: file.name,
              size_bytes: file.size,
              // Sent exactly as the browser reports it, empty included: some
              // browsers recognise no type for `.mov`, and the server resolves
              // the stored type from the validated extension anyway.
              content_type: file.type,
            }),
          });
          videoId = session.video_id;
          setPartsTotal(session.part_count);
        }
        const next: ResumeHint = {
          video_id: videoId,
          game_id: gameId,
          name: file.name,
          size: file.size,
          last_modified: file.lastModified,
        };
        writeHint(gameId, next);
        setHint(next);
        await sendMissing(file, videoId);
        writeHint(gameId, null);
        setHint(null);
        setStored(1);
        setPhase("complete");
      } catch (error) {
        setPhase("error");
        setMessage(
          error instanceof UploadFailure
            ? error.message
            : "The upload stopped. Choose the same file again to resume the missing parts.",
        );
      } finally {
        running.current = false;
        setCurrentPart(null);
      }
    },
    [gameId, sendMissing],
  );

  function choose(file: File | undefined) {
    if (!file) return;
    const problem = validateFile(file);
    if (problem) {
      setPhase("error");
      setMessage(problem);
      setFileName(file.name);
      return;
    }
    const existing = hint && sameFile(hint, file) ? hint : null;
    if (hint && !existing) {
      // A different file cannot resume the old upload: the stored parts came
      // from other bytes. Abandon that attempt explicitly instead.
      void fetch(`/api/videos/${hint.video_id}/upload-abort`, {
        method: "POST",
      }).catch(() => undefined);
      writeHint(gameId, null);
      setHint(null);
    }
    void start(file, existing);
  }

  async function abandon() {
    if (!hint) return;
    await fetch(`/api/videos/${hint.video_id}/upload-abort`, {
      method: "POST",
    }).catch(() => undefined);
    writeHint(gameId, null);
    setHint(null);
    setPhase("idle");
    setMessage("That upload was abandoned. Nothing was kept.");
  }

  const percent = Math.round(stored * 100);
  return (
    <section className={`${panel} p-5`} aria-labelledby="upload-heading">
      <h2
        id="upload-heading"
        className="text-[17px] font-semibold leading-[1.35]"
      >
        Upload the match video
      </h2>
      <p className={`${metadata} mt-1`}>{gameLabel}</p>

      {hint && phase !== "uploading" ? (
        <div className="mt-4 rounded-lg border border-line bg-paper p-4">
          <p className="text-[15px] leading-[1.5]">
            An unfinished upload is waiting for this match.
          </p>
          <p className={`${metadata} mt-1`}>
            {hint.name} · {formatBytes(hint.size)} · last changed{" "}
            {new Date(hint.last_modified).toLocaleString()}
          </p>
          <p className={`${metadata} mt-2`}>
            Choose the same file again to send only the parts that are missing.
          </p>
          <button
            type="button"
            onClick={abandon}
            className={`${secondary} mt-3`}
          >
            Abandon this upload
          </button>
        </div>
      ) : null}

      <div className="mt-4">
        <label htmlFor="match-file" className={label}>
          Match file
        </label>
        <input
          ref={input}
          id="match-file"
          name="match-file"
          type="file"
          accept="video/mp4,video/quicktime,.mp4,.m4v,.mov"
          disabled={phase === "uploading"}
          onChange={(event) => choose(event.target.files?.[0])}
          className={`${field} mt-1 py-2`}
        />
        <p className={`${metadata} mt-1`}>
          One MP4, M4V, or MOV file, up to 8 GB.
        </p>
      </div>

      {phase === "uploading" ? (
        <div className="mt-4" aria-live="polite">
          <p className="text-[15px] leading-[1.5]">
            Uploading {fileName} — {percent}% stored
            {currentPart && partsTotal
              ? `, part ${currentPart} of ${partsTotal}`
              : ""}
            .
          </p>
          <progress
            value={stored}
            max={1}
            aria-label="Overall upload progress"
            className="mt-2 h-2 w-full"
          />
          <p className={`${metadata} mt-2`}>{UPLOADING_NOTE}</p>
          <p className={`${metadata} mt-1`}>
            {partsDone} of {partsTotal} parts stored.
          </p>
        </div>
      ) : null}

      {phase === "complete" ? (
        <div className="mt-4" aria-live="polite">
          <p className="text-[15px] leading-[1.5]">{COMPLETE_NOTE}</p>
          <p className={`${metadata} mt-1`}>
            Shoulder is preparing the video. This page shows its state when you
            come back.
          </p>
          <button
            type="button"
            onClick={() => {
              setPhase("idle");
              if (input.current) input.current.value = "";
            }}
            className={`${primary} mt-3`}
          >
            Upload another match file
          </button>
        </div>
      ) : null}

      {phase === "error" ? (
        <p role="alert" className="mt-4 text-[15px] leading-[1.5]">
          {message}
        </p>
      ) : null}
    </section>
  );
}
