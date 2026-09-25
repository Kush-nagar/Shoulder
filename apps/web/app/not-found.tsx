import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { ShoulderMark } from "../components/brand";

/** One surface for absent and for hidden-by-authorization. It names neither. */
export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[560px] flex-col justify-center px-5 py-16">
      <ShoulderMark className="size-10 text-ink" aria-hidden="true" />
      <h1 className="mt-8 font-display text-[34px] leading-[1.05]">
        Not found
      </h1>
      <p className="mt-3 text-[16px] leading-6 text-ink-2">
        This page is not available, or it is not yours to open. Nothing was
        changed.
      </p>
      <Link
        href="/"
        className="mt-8 inline-flex min-h-11 w-fit items-center gap-2 rounded-lg text-[16px] font-semibold text-action underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      >
        <ArrowLeft size={18} strokeWidth={2} aria-hidden="true" />
        Back to Shoulder
      </Link>
    </main>
  );
}
