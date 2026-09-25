"use client";

import { errorBox, pageTitle, primaryButton } from "../ui";

export default function PracticeError({ reset }: { reset: () => void }) {
  return (
    <section aria-labelledby="practice-error-title" className="max-w-[680px]">
      <h1 id="practice-error-title" className={pageTitle}>
        Practice
      </h1>
      <p role="alert" className={`${errorBox} mt-6`}>
        This page could not be loaded. Your videos are unchanged.
      </p>
      <button type="button" onClick={reset} className={`${primaryButton} mt-4`}>
        Try again
      </button>
    </section>
  );
}
