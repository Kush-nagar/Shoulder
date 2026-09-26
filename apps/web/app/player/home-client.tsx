"use client";

import { Footprints, ListChecks, Play, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { focus, textLink } from "./ui";

const GUIDE_KEY = "sh.guide.hidden";

const steps = [
  {
    title: "Watch your coach's clips",
    body: "After a game your coach picks a few moments for your goal and writes one line on each.",
    href: "/player/progress",
    link: "See your clips",
    Icon: Play,
  },
  {
    title: "Film your own practice",
    body: "Record a drill on your phone. Only you can see it, and it is removed after 90 days.",
    href: "/player/practice/new",
    link: "Film practice",
    Icon: Footprints,
  },
  {
    title: "Pick a drill",
    body: "Short drills written by coaches, with the ones for your goal first.",
    href: "/player/drills",
    link: "Browse drills",
    Icon: ListChecks,
  },
] as const;

/** First-run guide. Hidden once dismissed; always shown if storage fails. */
export function HowItWorks({ className = "" }: { className?: string }) {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    try {
      setHidden(window.localStorage.getItem(GUIDE_KEY) === "1");
    } catch {
      setHidden(false);
    }
  }, []);
  if (hidden) return null;
  return (
    <section
      id="how-it-works"
      aria-labelledby="how-title"
      className={`scroll-mt-20 rounded-xl border border-line bg-surface p-4 md:p-6 ${className}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4">
        <h2
          id="how-title"
          className="text-[20px] font-semibold leading-[1.25] md:text-[22px]"
        >
          How Shoulder works
        </h2>
        <button
          type="button"
          onClick={() => {
            setHidden(true);
            try {
              window.localStorage.setItem(GUIDE_KEY, "1");
            } catch {
              // Nothing to remember; the guide simply shows next time.
            }
          }}
          className={`-mt-2 -mr-2 inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-lg px-2 text-[15px] font-medium text-ink-2 hover:bg-surface-subtle hover:text-ink ${focus}`}
        >
          <X size={18} strokeWidth={2} aria-hidden="true" />
          Hide this guide
        </button>
      </div>
      <ol className="mt-4 grid gap-5 md:grid-cols-3 md:gap-6">
        {steps.map(({ title, body, href, link, Icon }) => (
          <li key={title} className="border-t border-line pt-4">
            <Icon
              size={22}
              strokeWidth={2}
              aria-hidden="true"
              className="text-muted"
            />
            <h3 className="mt-3 text-[17px] font-semibold leading-[1.35]">
              {title}
            </h3>
            <p className="mt-1 text-[16px] leading-6 text-ink-2">{body}</p>
            <Link href={href} className={`${textLink} mt-1`}>
              {link}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * First frame of a practice video as its poster. The signed URL is
 * short-lived and object-specific; any failure falls back to the text tile.
 */
export function PracticePoster({
  url,
  title,
}: {
  url: string | null;
  title: string;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="relative block aspect-video overflow-hidden rounded-lg bg-night">
      {url && !failed ? (
        <video
          src={`${url}#t=0.5`}
          preload="metadata"
          muted
          playsInline
          tabIndex={-1}
          aria-hidden="true"
          onError={() => setFailed(true)}
          className="size-full object-cover"
        />
      ) : (
        <span
          aria-hidden="true"
          className="flex size-full items-end p-3 font-display text-[18px] leading-[1.05] text-on-night"
        >
          <span className="line-clamp-2">{title}</span>
        </span>
      )}
      <span
        aria-hidden="true"
        className="absolute right-2 bottom-2 flex size-8 items-center justify-center rounded-full bg-night/80 text-on-night"
      >
        <Play size={14} strokeWidth={2} fill="currentColor" />
      </span>
    </span>
  );
}
