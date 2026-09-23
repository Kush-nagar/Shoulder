"use client";

import { primaryButton } from "./format";

export default function PracticeError({ reset }: { reset: () => void }) {
  return (
    <section aria-labelledby="practice-error-title">
      <h1
        id="practice-error-title"
        className="text-[32px] font-semibold leading-[1.08]"
      >
        Practice
      </h1>
      <p
        role="alert"
        className="mt-6 rounded-xl bg-error-soft p-4 text-[16px] leading-6 text-error"
      >
        This page could not be loaded. Your videos are unchanged.
      </p>
      <button type="button" onClick={reset} className={`${primaryButton} mt-4`}>
        Try again
      </button>
    </section>
  );
}
