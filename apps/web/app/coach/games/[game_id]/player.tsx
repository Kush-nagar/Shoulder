"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  Judgment,
  Observation,
  PlaybackUrl,
  Timeline,
} from "../../../../lib/api";
import {
  isTextEntryTarget,
  reviewShortcut,
  validClipBounds,
} from "../../../../lib/marking";
import {
  contentMatches,
  type DraftScope,
  draftStorageKey,
  type ReviewDraft,
  restoreDrafts,
  type SyncedDraft,
  serializeDrafts,
} from "../../../../lib/review-drafts";
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

type ClientReply<T> = {
  status: number;
  data: T | null;
  current: T | null;
};

async function clientRequest<T>(
  url: string,
  init?: RequestInit,
): Promise<ClientReply<T>> {
  try {
    const response = await fetch(url, { ...init, cache: "no-store" });
    const body = (await response.json().catch(() => null)) as
      | T
      | { current?: T }
      | null;
    if (response.ok) {
      return { status: response.status, data: body as T, current: null };
    }
    return {
      status: response.status,
      data: null,
      current:
        body && typeof body === "object" && "current" in body
          ? ((body as { current?: T }).current ?? null)
          : null,
    };
  } catch {
    return { status: 0, data: null, current: null };
  }
}

function snapshot(judgment: Judgment): SyncedDraft {
  return {
    clipStartMs: judgment.clip_start_ms,
    clipEndMs: judgment.clip_end_ms,
    verdict: judgment.verdict,
    commentText: judgment.comment_text ?? "",
    version: judgment.version,
  };
}

export function CoachPlayer({
  videoId,
  label,
  coachId,
  playerId,
  goalId = null,
  initialObservations = [],
  initialJudgmentId,
}: {
  videoId: string;
  label: string;
  /** The signed-in coach. Drafts are stored per coach, never per browser. */
  coachId: string;
  playerId?: string;
  goalId?: string | null;
  initialObservations?: Observation[];
  initialJudgmentId?: string;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const requestedTimeSeconds = useRef(0);
  const seekingToSeconds = useRef<number | null>(null);
  const savingClip = useRef(false);
  const draftsRef = useRef<ReviewDraft[]>([]);
  const syncing = useRef(new Set<string>());
  const syncTimers = useRef(new Map<string, number>());
  const sendDraftRef = useRef<(localId: string) => Promise<void>>(
    async () => {},
  );
  const [playback, setPlayback] = useState<PlaybackUrl | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [message, setMessage] = useState("");
  const [currentMs, setCurrentMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [inMs, setInMs] = useState<number | null>(null);
  const [activeDraftId, setActiveDraftId] = useState<string | null>(null);
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState("Ready");
  const [markingMessage, setMarkingMessage] = useState("");
  const [drafts, setDrafts] = useState<ReviewDraft[]>([]);
  const [draftsReady, setDraftsReady] = useState(false);

  const scope: DraftScope | null = useMemo(
    () => (playerId ? { coachId, videoId, playerId, goalId } : null),
    [coachId, goalId, playerId, videoId],
  );

  const commitDrafts = useCallback(
    (change: (current: ReviewDraft[]) => ReviewDraft[]) => {
      const next = change(draftsRef.current);
      draftsRef.current = next;
      setDrafts(next);
      if (scope) {
        window.localStorage.setItem(
          draftStorageKey(scope),
          serializeDrafts(scope, next),
        );
      }
      return next;
    },
    [scope],
  );

  const scheduleSync = useCallback((localId: string, delay = 250) => {
    const previous = syncTimers.current.get(localId);
    if (previous !== undefined) window.clearTimeout(previous);
    const timer = window.setTimeout(() => {
      syncTimers.current.delete(localId);
      void sendDraftRef.current(localId);
    }, delay);
    syncTimers.current.set(localId, timer);
  }, []);

  const replaceDraft = useCallback(
    (localId: string, change: (draft: ReviewDraft) => ReviewDraft) =>
      commitDrafts((current) =>
        current.map((draft) =>
          draft.localId === localId ? change(draft) : draft,
        ),
      ),
    [commitDrafts],
  );

  const sendDraft = useCallback(
    async (localId: string): Promise<void> => {
      if (!scope || syncing.current.has(localId)) return;
      let draft = draftsRef.current.find((item) => item.localId === localId);
      if (
        !draft ||
        draft.clipEndMs === null ||
        draft.saveState === "conflict"
      ) {
        return;
      }
      if (!navigator.onLine) {
        replaceDraft(localId, (item) => ({ ...item, saveState: "offline" }));
        return;
      }
      syncing.current.add(localId);
      replaceDraft(localId, (item) => ({ ...item, saveState: "saving" }));
      try {
        if (!draft.observationId) {
          const observation = await clientRequest<Observation>(
            `/api/videos/${videoId}/observations`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                client_id: draft.localId,
                player_id: scope.playerId,
                t_start_ms: draft.clipStartMs,
                t_end_ms: draft.clipEndMs,
              }),
            },
          );
          if (!observation.data) {
            const retryable =
              observation.status === 0 || observation.status >= 500;
            replaceDraft(localId, (item) => ({
              ...item,
              saveState: retryable ? "offline" : "attention",
            }));
            if (retryable) scheduleSync(localId, 1_000);
            return;
          }
          replaceDraft(localId, (item) => ({
            ...item,
            observationId: observation.data?.id ?? item.observationId,
          }));
          draft = draftsRef.current.find((item) => item.localId === localId);
        }

        if (!draft?.observationId || !draft.verdict || !scope.goalId) {
          replaceDraft(localId, (item) => ({ ...item, saveState: "saved" }));
          return;
        }
        if (contentMatches(draft, draft.synced)) {
          replaceDraft(localId, (item) => ({ ...item, saveState: "saved" }));
          return;
        }

        const body = JSON.stringify({
          ...(draft.judgmentId ? {} : { goal_id: scope.goalId }),
          verdict: draft.verdict,
          comment_text: draft.commentText.trim() || null,
          clip_start_ms: draft.clipStartMs,
          clip_end_ms: draft.clipEndMs,
        });
        const result = await clientRequest<Judgment>(
          draft.judgmentId
            ? `/api/judgments/${draft.judgmentId}`
            : `/api/observations/${draft.observationId}/judgment`,
          {
            method: draft.judgmentId ? "PATCH" : "POST",
            headers: {
              "Content-Type": "application/json",
              ...(draft.judgmentId
                ? { "If-Match": String(draft.version) }
                : {}),
            },
            body,
          },
        );
        if (result.status === 409 && result.current) {
          const server = result.current as Judgment;
          const serverSnapshot = snapshot(server);
          if (contentMatches(draft, serverSnapshot)) {
            replaceDraft(localId, (item) => ({
              ...item,
              observationId: server.observation_id,
              judgmentId: server.id,
              version: server.version,
              synced: serverSnapshot,
              conflict: null,
              saveState: "saved",
            }));
            return;
          }
          replaceDraft(localId, (item) => ({
            ...item,
            saveState: "conflict",
            conflict: serverSnapshot,
          }));
          return;
        }
        if (result.status === 409 && !draft.judgmentId) {
          const existing = await clientRequest<Judgment | null>(
            `/api/observations/${draft.observationId}/judgment?goal_id=${goalId}`,
          );
          if (existing.data) {
            const server = existing.data;
            const serverSnapshot = snapshot(server);
            replaceDraft(localId, (item) => ({
              ...item,
              judgmentId: server.id,
              version: server.version,
              synced: serverSnapshot,
              saveState: contentMatches(item, serverSnapshot)
                ? "saved"
                : "pending",
            }));
            const latest = draftsRef.current.find(
              (item) => item.localId === localId,
            );
            if (latest && !contentMatches(latest, latest.synced)) {
              scheduleSync(localId, 0);
            }
            return;
          }
        }
        if (!result.data) {
          const retryable = result.status === 0 || result.status >= 500;
          replaceDraft(localId, (item) => ({
            ...item,
            saveState: retryable ? "offline" : "attention",
          }));
          if (retryable) scheduleSync(localId, 1_000);
          return;
        }
        const saved = result.data;
        replaceDraft(localId, (item) => {
          const synced = snapshot(saved);
          const stillMatches = contentMatches(item, synced);
          return {
            ...item,
            observationId: saved.observation_id,
            judgmentId: saved.id,
            version: saved.version,
            synced,
            conflict: null,
            saveState: stillMatches ? "saved" : "pending",
          };
        });
        const latest = draftsRef.current.find(
          (item) => item.localId === localId,
        );
        if (latest && !contentMatches(latest, latest.synced)) {
          scheduleSync(localId, 0);
        }
      } finally {
        syncing.current.delete(localId);
      }
    },
    [goalId, replaceDraft, scheduleSync, scope, videoId],
  );
  sendDraftRef.current = sendDraft;

  useEffect(() => {
    if (!scope) return;
    let alive = true;
    const restored = restoreDrafts(
      window.localStorage.getItem(draftStorageKey(scope)),
      scope,
    );
    const claimed = new Set(
      restored.flatMap((draft) =>
        draft.observationId ? [draft.observationId] : [draft.localId],
      ),
    );
    const merged = [
      ...restored,
      ...initialObservations
        .filter((observation) => !claimed.has(observation.id))
        .map(
          (observation, index): ReviewDraft => ({
            localId: observation.id,
            observationId: observation.id,
            judgmentId: null,
            position: restored.length + index,
            clipStartMs: observation.t_start_ms,
            clipEndMs: observation.t_end_ms,
            verdict: null,
            commentText: "",
            version: null,
            synced: null,
            saveState: "saved",
            conflict: null,
          }),
        ),
    ].map((draft) => {
      const recovered = initialObservations.find(
        (observation) => observation.id === draft.localId,
      );
      return recovered && !draft.observationId
        ? { ...draft, observationId: recovered.id }
        : draft;
    });
    commitDrafts(() => merged);
    const incomplete = merged.find((draft) => draft.clipEndMs === null);
    if (incomplete) {
      setInMs(incomplete.clipStartMs);
      setActiveDraftId(incomplete.localId);
    }

    void Promise.all(
      merged
        .filter((draft) => draft.observationId)
        .map(async (draft) => ({
          localId: draft.localId,
          result: await clientRequest<Judgment | null>(
            `/api/observations/${draft.observationId}/judgment?goal_id=${goalId}`,
          ),
        })),
    ).then((loaded) => {
      if (!alive) return;
      for (const { localId, result } of loaded) {
        if (!result.data) continue;
        const server = result.data;
        const serverSnapshot = snapshot(server);
        let retry = false;
        replaceDraft(localId, (draft) => {
          const locallyChanged =
            draft.synced !== null && !contentMatches(draft, draft.synced);
          if (contentMatches(draft, serverSnapshot)) {
            return {
              ...draft,
              judgmentId: server.id,
              version: server.version,
              synced: serverSnapshot,
              saveState: "saved",
              conflict: null,
            };
          }
          if (
            locallyChanged &&
            draft.version !== null &&
            server.version > draft.version
          ) {
            return {
              ...draft,
              judgmentId: server.id,
              saveState: "conflict",
              conflict: serverSnapshot,
            };
          }
          if (locallyChanged || (draft.verdict !== null && !draft.judgmentId)) {
            retry = true;
            return {
              ...draft,
              judgmentId: server.id,
              version: server.version,
              synced: serverSnapshot,
              saveState: "pending",
            };
          }
          return {
            ...draft,
            judgmentId: server.id,
            version: server.version,
            clipStartMs: server.clip_start_ms,
            clipEndMs: server.clip_end_ms,
            verdict: server.verdict,
            commentText: server.comment_text ?? "",
            synced: serverSnapshot,
            saveState: "saved",
            conflict: null,
          };
        });
        if (retry) scheduleSync(localId, 0);
      }
      setDraftsReady(true);
      const requested = draftsRef.current.find(
        (draft) => draft.judgmentId === initialJudgmentId,
      );
      if (requested) {
        setSelectedDraftId(requested.localId);
        setCurrentMs(requested.clipStartMs);
        requestedTimeSeconds.current = requested.clipStartMs / 1000;
        seekingToSeconds.current = requested.clipStartMs / 1000;
        if (video.current) {
          video.current.currentTime = requested.clipStartMs / 1000;
        }
      }
      for (const draft of draftsRef.current) {
        if (["pending", "offline"].includes(draft.saveState)) {
          scheduleSync(draft.localId, 0);
        }
      }
    });
    return () => {
      alive = false;
    };
  }, [
    commitDrafts,
    goalId,
    initialJudgmentId,
    initialObservations,
    replaceDraft,
    scheduleSync,
    scope,
  ]);

  useEffect(() => {
    const retry = () => {
      for (const draft of draftsRef.current) {
        if (["pending", "offline", "attention"].includes(draft.saveState)) {
          scheduleSync(draft.localId, 0);
        }
      }
    };
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [scheduleSync]);

  useEffect(() => {
    const hasUnsaved = () =>
      draftsRef.current.some((draft) =>
        ["pending", "saving", "offline", "attention", "conflict"].includes(
          draft.saveState,
        ),
      );
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsaved()) return;
      event.preventDefault();
    };
    const followLink = (event: MouseEvent) => {
      if (!hasUnsaved()) return;
      const target = event.target as Element | null;
      if (!target?.closest("a[href]")) return;
      if (!window.confirm("Draft changes are still saving. Leave this page?")) {
        event.preventDefault();
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", followLink);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", followLink);
      for (const timer of syncTimers.current.values())
        window.clearTimeout(timer);
      syncTimers.current.clear();
    };
  }, []);

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

  const editDraft = useCallback(
    (
      localId: string,
      change: Partial<Pick<ReviewDraft, "verdict" | "commentText">>,
    ) => {
      const current = draftsRef.current.find(
        (draft) => draft.localId === localId,
      );
      if (!current || current.saveState === "conflict") return;
      replaceDraft(localId, (draft) => ({
        ...draft,
        ...change,
        saveState: "pending",
      }));
      scheduleSync(localId);
    },
    [replaceDraft, scheduleSync],
  );

  const markIn = useCallback(() => {
    if (!video.current || !playerId || savingClip.current) return;
    const at = Math.round(video.current.currentTime * 1000);
    const localId = crypto.randomUUID();
    requestedTimeSeconds.current = at / 1000;
    setInMs(at);
    setActiveDraftId(localId);
    setSelectedDraftId(localId);
    commitDrafts((current) => [
      ...current,
      {
        localId,
        observationId: null,
        judgmentId: null,
        position: current.length,
        clipStartMs: at,
        clipEndMs: null,
        verdict: null,
        commentText: "",
        version: null,
        synced: null,
        saveState: "saved",
        conflict: null,
      },
    ]);
    setSaveState("Saved");
    setMarkingMessage(`In point ${formatClock(at)}`);
  }, [commitDrafts, playerId]);

  const markOut = useCallback(() => {
    if (savingClip.current) return;
    if (!video.current || !playerId || inMs === null || !activeDraftId) {
      setSaveState("Needs attention");
      setMarkingMessage("Set an in point first.");
      return;
    }
    // Keyboard seeks update this value synchronously. WebKit may not commit
    // video.currentTime before the next key arrives, so reading the element
    // here can collapse a rapid I, ArrowRight, O sequence to a zero-length
    // clip even though the requested playhead moved.
    const outMs = Math.round(requestedTimeSeconds.current * 1000);
    if (!validClipBounds(inMs, outMs, durationMs)) {
      setSaveState("Needs attention");
      setMarkingMessage("Choose an out point after the in point.");
      return;
    }
    replaceDraft(activeDraftId, (draft) => ({
      ...draft,
      clipEndMs: outMs,
      saveState: "pending",
    }));
    scheduleSync(activeDraftId, 0);
    setInMs(null);
    setActiveDraftId(null);
    setSelectedDraftId(activeDraftId);
    setSaveState("Saving");
    setMarkingMessage("");
  }, [activeDraftId, durationMs, inMs, playerId, replaceDraft, scheduleSync]);

  useEffect(() => {
    if (!draftsReady) return;
    const states = drafts.map((draft) => draft.saveState);
    if (states.some((state) => state === "conflict" || state === "attention")) {
      setSaveState("Needs attention");
    } else if (states.includes("offline")) {
      setSaveState("Offline — saved on this device");
    } else if (
      states.some((state) => state === "pending" || state === "saving")
    ) {
      setSaveState("Saving");
    } else if (drafts.length) {
      setSaveState("Saved");
    }
  }, [drafts, draftsReady]);

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
        case "select-verdict": {
          const localId =
            selectedDraftId ?? draftsRef.current.at(-1)?.localId ?? null;
          if (localId) editDraft(localId, { verdict: action.verdict });
          break;
        }
        case "focus-comment": {
          const localId =
            selectedDraftId ?? draftsRef.current.at(-1)?.localId ?? null;
          if (localId) {
            document
              .querySelector<HTMLTextAreaElement>(
                `textarea[data-comment-for="${localId}"]`,
              )
              ?.focus();
          }
          break;
        }
        case "save-draft": {
          const localId =
            selectedDraftId ?? draftsRef.current.at(-1)?.localId ?? null;
          if (localId) scheduleSync(localId, 0);
          break;
        }
        case "focus-video":
          video.current?.focus();
          break;
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    editDraft,
    markIn,
    markOut,
    scheduleSync,
    seekBy,
    selectedDraftId,
    toggle,
  ]);

  const preview =
    layout && hover !== null && timeline ? tileOffset(hover, layout) : null;
  const previewSheet =
    preview && timeline
      ? timeline.sheets.find((sheet) => sheet.sheet === preview.sheet)
      : undefined;

  const keepLocalDraft = (localId: string) => {
    const draft = draftsRef.current.find((item) => item.localId === localId);
    if (!draft?.conflict) return;
    replaceDraft(localId, (item) => ({
      ...item,
      version: draft.conflict?.version ?? item.version,
      synced: draft.conflict,
      conflict: null,
      saveState: "pending",
    }));
    scheduleSync(localId, 0);
  };

  const acceptServerDraft = (localId: string) => {
    replaceDraft(localId, (draft) => {
      if (!draft.conflict) return draft;
      return {
        ...draft,
        clipStartMs: draft.conflict.clipStartMs,
        clipEndMs: draft.conflict.clipEndMs,
        verdict: draft.conflict.verdict,
        commentText: draft.conflict.commentText,
        version: draft.conflict.version,
        synced: draft.conflict,
        conflict: null,
        saveState: "saved",
      };
    });
  };

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
                {drafts.map((draft) => (
                  <span
                    key={draft.localId}
                    className="absolute h-1 min-w-px bg-ink"
                    style={{
                      left: `${(draft.clipStartMs / durationMs) * 100}%`,
                      width: `${(((draft.clipEndMs ?? draft.clipStartMs) - draft.clipStartMs) / durationMs) * 100}%`,
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
              {drafts.length ? (
                <ul aria-label="Marked clips" className="mt-2 space-y-2">
                  {drafts.map((draft, index) => (
                    <li
                      key={draft.localId}
                      className="rounded-lg border border-line px-3 py-3"
                      onFocusCapture={() => setSelectedDraftId(draft.localId)}
                    >
                      <p className={`${metadata} tabular-nums`}>
                        Clip {index + 1} · {formatClock(draft.clipStartMs)}–
                        {draft.clipEndMs === null
                          ? "Set out point"
                          : formatClock(draft.clipEndMs)}{" "}
                        · Manual
                      </p>
                      {draft.clipEndMs !== null ? (
                        <div className="mt-3 space-y-3">
                          <fieldset>
                            <legend className="text-[15px] font-medium">
                              Verdict for clip {index + 1}
                            </legend>
                            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2">
                              {(
                                [
                                  ["applied", "You did this"],
                                  ["opportunity", "Chance to do this"],
                                  ["not_relevant", "Not relevant"],
                                ] as const
                              ).map(([value, text]) => (
                                <label
                                  key={value}
                                  className="flex items-center gap-2"
                                >
                                  <input
                                    type="radio"
                                    name={`verdict-${draft.localId}`}
                                    value={value}
                                    checked={draft.verdict === value}
                                    onChange={() =>
                                      editDraft(draft.localId, {
                                        verdict: value,
                                      })
                                    }
                                    disabled={draft.saveState === "conflict"}
                                  />
                                  <span>{text}</span>
                                </label>
                              ))}
                            </div>
                            <p className={`${metadata} mt-1`}>
                              Not relevant is kept for the coach and excluded
                              from publishing.
                            </p>
                          </fieldset>
                          <label className="block text-[15px] font-medium">
                            Coach comment for clip {index + 1}
                            <textarea
                              data-comment-for={draft.localId}
                              value={draft.commentText}
                              maxLength={400}
                              rows={2}
                              disabled={draft.saveState === "conflict"}
                              onChange={(event) =>
                                editDraft(draft.localId, {
                                  commentText: event.currentTarget.value,
                                })
                              }
                              className={`mt-1 block w-full rounded-lg border border-line bg-paper px-3 py-2 ${focus}`}
                            />
                          </label>
                          <p className={metadata} aria-live="polite">
                            {draft.saveState === "offline"
                              ? "Offline — saved on this device"
                              : draft.saveState === "attention"
                                ? "Needs attention"
                                : draft.saveState === "pending" ||
                                    draft.saveState === "saving"
                                  ? "Saving"
                                  : draft.saveState === "conflict"
                                    ? "Needs attention"
                                    : "Saved"}
                          </p>
                          {draft.conflict ? (
                            <div
                              role="alert"
                              className="rounded-lg border border-line p-3"
                            >
                              <p className="text-[15px] font-semibold">
                                This clip changed in another session.
                              </p>
                              <p className={`${metadata} mt-1`}>
                                Your draft: {draft.commentText || "No comment"}
                              </p>
                              <p className={`${metadata} mt-1`}>
                                Server version:{" "}
                                {draft.conflict.commentText || "No comment"}
                              </p>
                              <div className="mt-3 flex flex-wrap gap-2">
                                <button
                                  type="button"
                                  className={secondary}
                                  onClick={() => keepLocalDraft(draft.localId)}
                                >
                                  Keep my draft
                                </button>
                                <button
                                  type="button"
                                  className={secondary}
                                  onClick={() =>
                                    acceptServerDraft(draft.localId)
                                  }
                                >
                                  Use server version
                                </button>
                              </div>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </li>
                  ))}
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
