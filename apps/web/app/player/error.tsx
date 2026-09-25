"use client";

import { errorBox, pageTitle, primaryButton } from "./ui";

export default function PlayerError({ reset }: { reset: () => void }) {
  return (
    <section aria-labelledby="player-error-title" className="max-w-[680px]">
      <h1 id="player-error-title" className={pageTitle}>
        Your clips
      </h1>
      <p role="alert" className={`${errorBox} mt-6`}>
        Your clips could not be loaded. Nothing changed.
      </p>
      <button type="button" onClick={reset} className={`${primaryButton} mt-4`}>
        Try again
      </button>
    </section>
  );
}
