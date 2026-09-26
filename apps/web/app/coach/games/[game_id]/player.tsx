"use client";

import {
  FastForward,
  Keyboard,
  Maximize,
  Pause,
  Play,
  Rewind,
  StepBack,
  StepForward,
} from "lucide-react";
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
import { focus, metadata, secondary } from "../../ui";
import { MatchTimeline } from "./timeline";

/** Focus ring on the night stage: lime reads on the video's black. */
const nightFocus =
  "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action-on-night";

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
  const stage = useRef<HTMLDivElement>(null);
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
  const [speed, setSpeed] = useState(1);
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

  const seekTo = (atMs: number) => {
    requestedTimeSeconds.current = atMs / 1000;
    seekingToSeconds.current = atMs / 1000;
    setCurrentMs(atMs);
    if (video.current) video.current.currentTime = atMs / 1000;
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void stage.current?.requestFullscreen().catch(() => undefined);
  };

  const transport = `relative inline-flex size-9 shrink-0 items-center justify-center rounded-md text-on-night/80 transition-[background-color,color,transform] duration-140 hover:bg-on-night/10 hover:text-on-night active:scale-95 ${nightFocus}`;
  const markButton = `relative inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-night-line px-2.5 text-[13px] font-medium text-on-night transition-[background-color,border-color,transform] duration-140 hover:border-on-night/30 hover:bg-on-night/8 active:scale-[0.97] ${nightFocus}`;

  return (
    <section
      aria-labelledby="player-heading"
      className={
        playerId
          ? "grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] xl:gap-5"
          : "grid gap-3"
      }
    >
      <div className="min-w-0">
        <div className="mb-2 flex items-baseline justify-between gap-4">
          <h2
            id="player-heading"
            className="text-[13px] font-medium leading-[1.35] text-ink-2"
          >
            Match video
            <span className="sr-only">: {label}</span>
          </h2>
          <p className="hidden font-mono text-[12px] text-muted md:block">
            {formatClock(currentMs)} / {formatClock(durationMs)}
          </p>
        </div>

        {message ? (
          <p
            role="alert"
            className="mb-3 rounded-lg border border-error/30 bg-error-soft px-4 py-3 text-[14px] leading-[1.5] text-ink"
          >
            {message}
          </p>
        ) : null}

        {playback ? (
          <div
            ref={stage}
            className="overflow-hidden rounded-2xl bg-night text-on-night ring-1 ring-night-line [&:fullscreen]:flex [&:fullscreen]:flex-col [&:fullscreen]:justify-end [&:fullscreen]:rounded-none"
          >
            {/* A fixed 16:9 box, so the frame never shifts the page as it loads. */}
            <div className="aspect-video w-full bg-night [:fullscreen_&]:aspect-auto [:fullscreen_&]:flex-1">
              <video
                ref={video}
                tabIndex={0}
                src={playback.url}
                preload="metadata"
                playsInline
                controls={false}
                onClick={toggle}
                className={`size-full cursor-pointer ${nightFocus} focus-visible:-outline-offset-2`}
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
                  requestedTimeSeconds.current =
                    event.currentTarget.currentTime;
                  setCurrentMs(event.currentTarget.currentTime * 1000);
                }}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onRateChange={(event) =>
                  setSpeed(event.currentTarget.playbackRate)
                }
              >
                <track kind="captions" />
              </video>
            </div>

            <MatchTimeline
              durationMs={durationMs}
              currentMs={currentMs}
              hover={hover}
              onHover={setHover}
              onSeek={seekTo}
              markers={
                playerId
                  ? drafts.map((draft) => ({
                      id: draft.localId,
                      startMs: draft.clipStartMs,
                      endMs: draft.clipEndMs,
                      selected: draft.localId === selectedDraftId,
                    }))
                  : []
              }
              inMs={playerId ? inMs : null}
              timeline={timeline}
              preview={
                previewSheet && preview
                  ? { url: previewSheet.url, x: preview.x, y: preview.y }
                  : null
              }
            />

            <div className="flex flex-wrap items-center gap-1 border-t border-night-line px-2 py-1.5 md:px-3">
              <button
                type="button"
                onClick={() => seekBy(-10)}
                className={transport}
                aria-label="Back ten seconds"
              >
                <Rewind size={16} strokeWidth={1.75} aria-hidden="true" />
                <Tip>Back 10s · J</Tip>
              </button>
              <button
                type="button"
                onClick={() => seekBy(-1)}
                className={transport}
                aria-label="Back one second"
              >
                <StepBack size={16} strokeWidth={1.75} aria-hidden="true" />
                <Tip>Back 1s · ←</Tip>
              </button>
              <button
                type="button"
                onClick={toggle}
                className={`${transport} size-10 bg-on-night/10 text-on-night`}
                aria-label={playing ? "Pause" : "Play"}
              >
                {playing ? (
                  <Pause size={18} strokeWidth={2} aria-hidden="true" />
                ) : (
                  <Play size={18} strokeWidth={2} aria-hidden="true" />
                )}
                <Tip>{`${playing ? "Pause" : "Play"} · Space`}</Tip>
              </button>
              <button
                type="button"
                onClick={() => seekBy(1)}
                className={transport}
                aria-label="Forward one second"
              >
                <StepForward size={16} strokeWidth={1.75} aria-hidden="true" />
                <Tip>Forward 1s · →</Tip>
              </button>
              <button
                type="button"
                onClick={() => seekBy(10)}
                className={transport}
                aria-label="Forward ten seconds"
              >
                <FastForward size={16} strokeWidth={1.75} aria-hidden="true" />
                <Tip>Forward 10s · L</Tip>
              </button>
              <p
                className="ml-2 font-mono text-[13px] text-on-night tabular-nums"
                aria-live="off"
              >
                {formatClock(currentMs)}
                <span className="text-night-muted">
                  {" "}
                  / {formatClock(durationMs)}
                </span>
              </p>

              <div className="ml-auto flex items-center gap-1.5">
                {playerId ? (
                  <>
                    <button
                      type="button"
                      onClick={markIn}
                      className={markButton}
                    >
                      <kbd className="font-mono text-[11px] text-night-muted">
                        I
                      </kbd>
                      Set clip in
                    </button>
                    <button
                      type="button"
                      onClick={() => void markOut()}
                      className={`${markButton} ${inMs !== null ? "border-action-on-night/60 text-action-on-night" : ""}`}
                    >
                      <kbd className="font-mono text-[11px] text-night-muted">
                        O
                      </kbd>
                      Set clip out
                    </button>
                  </>
                ) : null}
                <label className="relative">
                  <span className="sr-only">Playback speed</span>
                  <select
                    value={speed}
                    onChange={(event) => {
                      const rate = Number(event.currentTarget.value);
                      setSpeed(rate);
                      if (video.current) video.current.playbackRate = rate;
                    }}
                    className={`h-8 cursor-pointer appearance-none rounded-md bg-transparent px-2 font-mono text-[12px] text-on-night/80 hover:bg-on-night/10 hover:text-on-night ${nightFocus}`}
                  >
                    {[0.5, 1, 1.5, 2].map((rate) => (
                      <option key={rate} value={rate} className="bg-night">
                        {rate}×
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={toggleFullscreen}
                  className={transport}
                  aria-label="Full screen"
                >
                  <Maximize size={16} strokeWidth={1.75} aria-hidden="true" />
                  <Tip>Full screen</Tip>
                </button>
              </div>
            </div>
          </div>
        ) : message ? null : (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 overflow-hidden rounded-2xl bg-night ring-1 ring-night-line">
            <span className="relative block h-px w-40 overflow-hidden bg-night-line">
              <span className="sh-scan absolute inset-y-0 left-0 w-10 bg-action-on-night/70" />
            </span>
            <p className="text-[13px] text-night-muted">
              Opening the match video…
            </p>
          </div>
        )}

        <details className="group mt-3 text-[13px] text-muted">
          <summary
            className={`inline-flex min-h-8 cursor-pointer list-none items-center gap-1.5 rounded-sm hover:text-ink [&::-webkit-details-marker]:hidden ${focus}`}
          >
            <Keyboard size={15} strokeWidth={1.75} aria-hidden="true" />
            Keyboard shortcuts
          </summary>
          <dl className="mt-2 grid max-w-xl grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-lg border border-line bg-surface p-3 sm:grid-cols-[auto_1fr_auto_1fr]">
            {[
              ["Space / K", "Play or pause"],
              ["J / L", "Back or forward 10 seconds"],
              ["← / →", "Step 1 second"],
              ["Shift ← / →", "Step 10 seconds"],
              ...(playerId
                ? [
                    ["I / O", "Set clip in / out"],
                    ["1 · 2 · 3", "Verdict for the selected clip"],
                    ["C", "Write the coach comment"],
                    ["Esc", "Back to the video"],
                  ]
                : []),
            ].map(([keys, action]) => (
              <div key={keys} className="contents">
                <dt className="font-mono text-[12px] text-ink">{keys}</dt>
                <dd className="text-ink-2">{action}</dd>
              </div>
            ))}
          </dl>
        </details>
      </div>

      {playerId && playback ? (
        <aside
          aria-labelledby="clips-heading"
          className="sh-inspector-in flex min-h-0 flex-col rounded-2xl border border-line bg-surface xl:sticky xl:top-[72px] xl:max-h-[calc(100dvh-88px)]"
        >
          <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
            <h3 id="clips-heading" className="text-[14px] font-semibold">
              Marked clips
              <span className="ml-2 font-mono text-[12px] font-normal text-muted">
                {drafts.filter((draft) => draft.clipEndMs !== null).length}
              </span>
            </h3>
            <p
              role="status"
              aria-live="polite"
              className={`text-[12px] ${
                saveState === "Needs attention"
                  ? "text-error"
                  : saveState === "Saved"
                    ? "text-ink-2"
                    : "text-warning"
              }`}
            >
              {saveState}
            </p>
          </div>
          {markingMessage ? (
            <p className="border-b border-line px-4 py-2 font-mono text-[12px] text-action">
              {markingMessage}
            </p>
          ) : null}
          {drafts.length ? (
            <ul
              aria-label="Marked clips"
              className="min-h-0 flex-1 divide-y divide-line overflow-y-auto"
            >
              {drafts.map((draft, index) => {
                const selected = draft.localId === selectedDraftId;
                return (
                  <li
                    key={draft.localId}
                    className={`relative px-4 py-3 transition-colors duration-140 ${selected ? "bg-signal-soft" : ""}`}
                    onFocusCapture={() => setSelectedDraftId(draft.localId)}
                  >
                    {selected ? (
                      <span
                        aria-hidden="true"
                        className="absolute inset-y-3 left-0 w-0.5 rounded-r-sm bg-signal"
                      />
                    ) : null}
                    <div className="flex items-center justify-between gap-3">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedDraftId(draft.localId);
                          seekTo(draft.clipStartMs);
                        }}
                        className={`-mx-1 inline-flex items-center gap-2 rounded-sm px-1 text-left ${focus}`}
                      >
                        <span className="text-[13px] font-semibold text-ink">
                          Clip {index + 1}
                        </span>
                        <span className="font-mono text-[12px] text-ink-2">
                          {formatClock(draft.clipStartMs)}–
                          {draft.clipEndMs === null
                            ? "Set out point"
                            : formatClock(draft.clipEndMs)}
                        </span>
                      </button>
                      <span className="text-[12px] text-muted">
                        Manual ·{" "}
                        <span
                          className={
                            draft.saveState === "saved"
                              ? ""
                              : draft.saveState === "conflict" ||
                                  draft.saveState === "attention"
                                ? "text-error"
                                : "text-warning"
                          }
                          aria-live="polite"
                        >
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
                        </span>
                      </span>
                    </div>
                    {draft.clipEndMs !== null ? (
                      <div className="mt-3 space-y-3">
                        <fieldset>
                          <legend className="sr-only">
                            Verdict for clip {index + 1}
                          </legend>
                          <div className="flex flex-wrap gap-1 rounded-lg bg-paper p-1">
                            {(
                              [
                                ["applied", "You did this"],
                                ["opportunity", "Chance to do this"],
                                ["not_relevant", "Not relevant"],
                              ] as const
                            ).map(([value, text]) => (
                              <label
                                key={value}
                                className="relative flex min-h-8 flex-auto cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-2 text-[12px] leading-tight text-ink-2 transition-colors duration-140 hover:text-ink has-[:checked]:bg-popover has-[:checked]:text-ink has-[:checked]:shadow-pop has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-40 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-focus"
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
                                  className="size-3.5 shrink-0 appearance-none rounded-full border border-control-border outline-none checked:border-4 checked:border-action"
                                />
                                <span className="flex-1">{text}</span>
                              </label>
                            ))}
                          </div>
                          <p className="mt-1.5 text-[12px] leading-[1.4] text-muted">
                            Not relevant is kept for the coach and excluded from
                            publishing.
                          </p>
                        </fieldset>
                        <label className="block text-[12px] font-medium text-ink-2">
                          Coach comment for clip {index + 1}
                          <textarea
                            data-comment-for={draft.localId}
                            value={draft.commentText}
                            maxLength={400}
                            rows={2}
                            placeholder="One sentence the player will read before the clip."
                            disabled={draft.saveState === "conflict"}
                            onChange={(event) =>
                              editDraft(draft.localId, {
                                commentText: event.currentTarget.value,
                              })
                            }
                            className={`mt-1 block w-full resize-y rounded-md border border-control-border bg-paper px-3 py-2 text-[14px] font-normal leading-[1.45] text-ink placeholder:text-muted hover:border-ink-2 ${focus}`}
                          />
                        </label>
                        {draft.conflict ? (
                          <div
                            role="alert"
                            className="rounded-lg border border-warning/40 bg-warning-soft p-3"
                          >
                            <p className="text-[14px] font-semibold">
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
                                onClick={() => acceptServerDraft(draft.localId)}
                              >
                                Use server version
                              </button>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="sh-pitch m-4 flex flex-1 flex-col items-center justify-center rounded-xl border border-line px-5 py-10 text-center">
              <p className="font-mono text-[12px] text-muted uppercase">
                No clips yet
              </p>
              <p className="mt-2 max-w-[30ch] text-[14px] leading-[1.5] text-ink">
                Press <kbd className="font-mono text-[12px]">I</kbd> at the
                start of a moment and{" "}
                <kbd className="font-mono text-[12px]">O</kbd> at its end.
              </p>
            </div>
          )}
        </aside>
      ) : null}
    </section>
  );
}

/** Fast, concise tooltip for an icon-only transport control. */
function Tip({ children }: { children: string }) {
  return (
    <span
      aria-hidden="true"
      className="sh-tip rounded-md bg-popover px-2 py-1 font-sans text-[12px] font-medium leading-none text-ink shadow-pop"
    >
      {children}
    </span>
  );
}
