"use client";

import { Flag, Play, Square } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { errorBox, focus, primaryButton, secondaryButton } from "../../ui";
import { km, kmh, kindLabel, stopwatch } from "../format";
import type { SessionSummary } from "../tracking/metrics";
import { type LiveStats, startTracking, type Tracker } from "../tracking/track";

type Kind = keyof typeof kindLabel;
type Phase = "setup" | "live" | "review" | "saving";

const idle: LiveStats = {
  status: "waiting",
  elapsedS: 0,
  distanceM: 0,
  speedKmh: 0,
  halfTimeMarked: false,
};

function Big({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[14px] font-semibold text-night-muted">{label}</dt>
      <dd className="mt-1 text-[32px] font-semibold leading-none tabular-nums md:text-[40px]">
        {value}
      </dd>
    </div>
  );
}

export function SessionTracker() {
  const router = useRouter();
  const tracker = useRef<Tracker | null>(null);
  const [phase, setPhase] = useState<Phase>("setup");
  const [kind, setKind] = useState<Kind>("training");
  const [live, setLive] = useState<LiveStats>(idle);
  const [summary, setSummary] = useState<SessionSummary | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [desktop, setDesktop] = useState(false);
  const [noGps, setNoGps] = useState(false);
  const [discarding, setDiscarding] = useState(false);

  useEffect(() => {
    setDesktop(window.matchMedia("(pointer: fine)").matches);
    setNoGps(!("geolocation" in navigator));
    return () => {
      tracker.current?.stop();
    };
  }, []);

  // Leaving mid-session loses it; the browser asks first.
  useEffect(() => {
    if (phase === "setup") return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [phase]);

  // Permission refused: stop at once; nothing was recorded.
  useEffect(() => {
    if (live.status === "denied" || live.status === "unavailable") {
      tracker.current?.stop();
      tracker.current = null;
      setPhase("setup");
    }
  }, [live.status]);

  function start() {
    setError(null);
    setSummary(null);
    setLive(idle);
    tracker.current = startTracking(setLive);
    setPhase("live");
  }

  function finish() {
    const result = tracker.current?.stop() ?? null;
    tracker.current = null;
    setSummary(result);
    setPhase("review");
  }

  function discard() {
    setDiscarding(false);
    setSummary(null);
    setNote("");
    setLive(idle);
    setPhase("setup");
  }

  async function save() {
    if (!summary) return;
    setPhase("saving");
    setError(null);
    try {
      const response = await fetch("/api/player/sessions", {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...summary,
          kind,
          note: note.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(String(response.status));
      const saved = (await response.json()) as { id: string };
      setPhase("setup");
      router.push(`/player/sessions/${saved.id}`);
      router.refresh();
    } catch {
      setError("Couldn't save. Your session is still here, so try again.");
      setPhase("review");
    }
  }

  if (phase === "setup") {
    return (
      <div className="mt-6 max-w-[680px] space-y-6">
        {live.status === "denied" ? (
          <p role="alert" className={errorBox}>
            Location access is off for Shoulder. Allow location for this site in
            your browser or phone settings, then start again.
          </p>
        ) : null}
        {noGps || live.status === "unavailable" ? (
          <p role="alert" className={errorBox}>
            This browser can&apos;t share its location, so it can&apos;t record
            a session.
          </p>
        ) : null}
        {desktop ? (
          <p className="rounded-xl border border-line bg-surface p-4 text-[16px] leading-6 text-ink-2">
            Recording needs a phone with GPS, outdoors. Open Shoulder on your
            phone at training; a computer can&apos;t measure your running.
          </p>
        ) : null}
        <fieldset>
          <legend className="text-[16px] font-semibold">
            What are you recording?
          </legend>
          <div className="mt-3 grid max-w-[360px] grid-cols-2 gap-2">
            {(Object.keys(kindLabel) as Kind[]).map((value) => (
              <label
                key={value}
                className={`flex min-h-11 cursor-pointer items-center justify-center rounded-lg border text-[16px] font-semibold has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus ${
                  kind === value
                    ? "border-action bg-action-soft text-ink"
                    : "border-control-border bg-surface text-ink-2"
                }`}
              >
                <input
                  type="radio"
                  name="kind"
                  value={value}
                  checked={kind === value}
                  onChange={() => setKind(value)}
                  className="sr-only"
                />
                {kindLabel[value]}
              </label>
            ))}
          </div>
        </fieldset>
        <p className="text-[16px] leading-6 text-ink-2">
          Keep this screen open and your phone in a pocket or armband. Your
          exact location never leaves your phone.
        </p>
        <button
          type="button"
          onClick={start}
          disabled={noGps}
          className={`${primaryButton} w-full min-[480px]:w-auto`}
        >
          <Play size={20} strokeWidth={2} aria-hidden="true" />
          Start
        </button>
      </div>
    );
  }

  if (phase === "live") {
    const status =
      live.status === "waiting"
        ? "Finding GPS signal…"
        : live.status === "poor"
          ? "GPS signal is weak. Stay outdoors, away from tall buildings."
          : `Recording ${kindLabel[kind].toLowerCase()}`;
    return (
      <div className="mt-6 max-w-[680px]">
        <section
          aria-label="Live session"
          className="rounded-[14px] border border-night-line bg-night px-5 py-6 text-on-night md:px-8 md:py-8"
        >
          <p
            role="status"
            className={`text-[14px] font-semibold ${live.status === "poor" ? "text-action-on-night" : "text-night-muted"}`}
          >
            {status}
          </p>
          <p className="mt-3 text-[64px] font-semibold leading-none tabular-nums min-[375px]:text-[76px] md:text-[96px]">
            {stopwatch(live.elapsedS)}
          </p>
          <dl className="mt-6 grid grid-cols-2 gap-4">
            <Big label="Distance" value={km(Math.round(live.distanceM))} />
            <Big
              label="Speed now"
              value={kmh(Math.round(live.speedKmh / 0.036))}
            />
          </dl>
        </section>
        <div className="mt-5 grid grid-cols-2 gap-3">
          <button
            type="button"
            onClick={() => tracker.current?.markHalfTime()}
            disabled={live.halfTimeMarked}
            className={`${secondaryButton} min-h-14`}
          >
            <Flag size={20} strokeWidth={2} aria-hidden="true" />
            {live.halfTimeMarked ? "Half-time marked" : "Half-time"}
          </button>
          <button
            type="button"
            onClick={finish}
            className={`${primaryButton} min-h-14`}
          >
            <Square size={18} strokeWidth={2} aria-hidden="true" />
            Finish
          </button>
        </div>
      </div>
    );
  }

  const tooShort = !summary || summary.duration_s < 60;
  return (
    <div className="mt-6 max-w-[680px] space-y-6">
      {tooShort ? (
        <>
          <p className="text-[16px] leading-6 text-ink-2">
            Sessions shorter than a minute aren&apos;t saved.
          </p>
          <button type="button" onClick={discard} className={primaryButton}>
            Start again
          </button>
        </>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {(
              [
                ["Distance", km(summary.distance_m)],
                ["Time", stopwatch(summary.duration_s)],
                ["Top speed", kmh(summary.top_speed_cms)],
                ["Sprints", String(summary.sprint_count)],
              ] as const
            ).map(([label, value]) => (
              <div
                key={label}
                className="rounded-xl border border-line bg-surface p-4"
              >
                <dt className="text-[14px] font-semibold text-ink-2">
                  {label}
                </dt>
                <dd className="mt-1 text-[24px] font-semibold tabular-nums">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          {summary.gps_quality === "poor" ? (
            <p className="text-[16px] leading-6 text-ink-2">
              The GPS signal was weak, so these numbers may be off.
            </p>
          ) : null}
          <div>
            <label htmlFor="session-note" className="text-[16px] font-semibold">
              Note (optional)
            </label>
            <textarea
              id="session-note"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={280}
              rows={3}
              aria-describedby="session-note-help"
              className={`mt-2 block w-full rounded-lg border border-control-border bg-surface p-3 text-[16px] leading-6 ${focus}`}
            />
            <p
              id="session-note-help"
              className="mt-2 text-[14px] leading-5 text-muted"
            >
              Your coach can see your saved sessions and notes.
            </p>
          </div>
          {error ? (
            <p role="alert" className={errorBox}>
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void save()}
              disabled={phase === "saving"}
              className={primaryButton}
            >
              {phase === "saving" ? "Saving…" : "Save session"}
            </button>
            <button
              type="button"
              onClick={discarding ? discard : () => setDiscarding(true)}
              disabled={phase === "saving"}
              className={secondaryButton}
            >
              {discarding ? "Tap again to discard" : "Discard"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
