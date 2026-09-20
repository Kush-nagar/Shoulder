"use client";

export default function PlayerError({ reset }: { reset: () => void }) {
  return (
    <section aria-labelledby="player-error-title">
      <h1
        id="player-error-title"
        className="text-[26px] font-semibold leading-[1.15]"
      >
        Your clips
      </h1>
      <p
        role="alert"
        className="mt-6 rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
      >
        Your clips could not be loaded. Nothing changed.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-4 min-h-11 rounded-lg bg-action px-4 text-[16px] font-semibold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        Try again
      </button>
    </section>
  );
}
