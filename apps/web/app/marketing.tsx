"use client";

/*
 * Public homepage (ADR 0025, refreshed 2026-10-03).
 * THESIS: "Check your shoulder" as the page's motion: the visitor scans across
 * one pitch, from a whole match to the single clip a player receives. Refuses
 * the stacked feature-card landing.
 * OWN-WORLD: warm paper, ink, one signal lime that means "look here";
 * Archivo condensed caps for display, Inter Tight for reading, Geist Mono only
 * for match time. Pitch lines, timecodes and in/out brackets are the ornament.
 * STORY: a coach turns film into a few moments; the player receives only their
 * clip in the coach's words; both sides then work through the week.
 * FIRST VIEWPORT: headline left at display scale, a live formation and photo
 * iris right, "Open Shoulder" under the headline.
 * FORM: horizontal scan (own structural list, position 5; seed 27bce56a).
 */

import { ArrowRight, ArrowUpRight, Menu, Pause, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import {
  type CSSProperties,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { ShoulderMark, ShoulderWordmark } from "../components/brand";
import pitch from "../public/marketing-pitch.jpg";
import "./marketing.css";

const STEPS = ["Watch", "Mark", "Say why", "Share"] as const;

// Inlined at build time; the same switch as lib/marketplace.
const PILOT = process.env.NEXT_PUBLIC_MARKETPLACE_ENABLED === "on";

const SENTENCE =
  "You checked your shoulder before the ball arrived. That look gave you time to turn.";

const DRILLS = [
  "Scanning",
  "First touch",
  "Half-turn",
  "Passing",
  "Ball mastery",
  "1v1",
  "Both feet",
  "Defending",
];

function PitchLines({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`mk-pitch ${className}`}
      viewBox="0 0 760 500"
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid meet"
    >
      <rect x="38" y="38" width="684" height="424" pathLength={1} />
      <path d="M380 38v424" pathLength={1} />
      <path d="M38 146h115v208H38M722 146H607v208h115" pathLength={1} />
      <path d="M38 191h45v118H38M722 191h-45v118h45" pathLength={1} />
      <circle cx="380" cy="250" r="66" pathLength={1} />
      <path
        d="M153 182a76 76 0 0 1 0 136M607 182a76 76 0 0 0 0 136"
        pathLength={1}
      />
    </svg>
  );
}

/** Eleven shapes, one pass, one run into space. Decoration only. */
function Formation() {
  return (
    <svg
      className="mk-formation"
      viewBox="0 0 760 500"
      fill="none"
      aria-hidden="true"
    >
      <path className="mk-space" d="M394 217 568 114 490 317Z" />
      <path
        className="mk-route mk-route-one"
        d="M207 254 Q316 214 394 217"
        pathLength={1}
      />
      <path
        className="mk-route mk-route-two"
        d="M394 217 Q496 171 568 114"
        pathLength={1}
      />
      <path className="mk-run" d="M490 317 Q526 224 568 114" pathLength={1} />
      <g className="mk-players">
        {[
          [207, 122],
          [207, 380],
          [310, 148],
          [312, 351],
          [576, 386],
          [650, 250],
        ].map(([cx, cy], i) => (
          <circle
            key={`${cx}-${cy}`}
            cx={cx}
            cy={cy}
            r="7"
            style={{ "--i": i } as CSSProperties}
          />
        ))}
        <circle
          cx="207"
          cy="254"
          r="9"
          className="mk-key"
          style={{ "--i": 7 } as CSSProperties}
        />
        <circle
          cx="394"
          cy="217"
          r="9"
          className="mk-key"
          style={{ "--i": 8 } as CSSProperties}
        />
        <circle
          cx="568"
          cy="114"
          r="9"
          className="mk-key mk-receiver"
          style={{ "--i": 9 } as CSSProperties}
        />
      </g>
      <circle className="mk-ball" r="5" />
      <text x="582" y="100" className="mk-num">
        17
      </text>
      <text x="374" y="197" className="mk-num">
        08
      </text>
    </svg>
  );
}

/** Ticking match clock for the hero label; frozen under reduced motion. */
function MatchClock() {
  const [seconds, setSeconds] = useState(73 * 60 + 38);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  const m = Math.floor(seconds / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return (
    <span className="mk-clock">
      {m}:{s}
    </span>
  );
}

function CtaLink({
  className = "",
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link className={`mk-button ${className}`} href="/auth/sign-in">
      <span>{children}</span>
      <ArrowUpRight aria-hidden="true" size={18} strokeWidth={2} />
    </Link>
  );
}

export function MarketingPage() {
  const rootRef = useRef<HTMLDivElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const heroRef = useRef<HTMLElement>(null);
  const scanRef = useRef<HTMLElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [step, setStep] = useState(0);
  const menuOpenRef = useRef(false);
  menuOpenRef.current = menuOpen;

  // Scroll: nav state and reading progress, hero iris, and the pinned scan.
  useEffect(() => {
    const root = rootRef.current;
    const nav = navRef.current;
    const hero = heroRef.current;
    const scan = scanRef.current;
    if (!root || !nav || !hero || !scan) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    const pinned = window.matchMedia("(min-width: 900px)");
    let frame = 0;
    let lastY = window.scrollY;

    const update = () => {
      frame = 0;
      const y = window.scrollY;
      const max = Math.max(
        1,
        document.documentElement.scrollHeight - innerHeight,
      );
      root.style.setProperty("--mk-read", (y / max).toFixed(4));
      nav.dataset.scrolled = y > 24 ? "true" : "false";
      // Hide on the way down, return on the way up.
      if (Math.abs(y - lastY) > 6) {
        nav.dataset.hidden =
          y > lastY && y > 400 && !menuOpenRef.current ? "true" : "false";
        lastY = y;
      }
      if (still.matches) return;

      const heroP = Math.min(
        1,
        Math.max(0, y / Math.max(1, hero.offsetHeight)),
      );
      hero.style.setProperty("--mk-hero", heroP.toFixed(3));

      if (pinned.matches) {
        const rect = scan.getBoundingClientRect();
        const run = Math.max(1, scan.offsetHeight - innerHeight);
        const p = Math.min(1, Math.max(0, -rect.top / run));
        scan.style.setProperty("--mk-scan", p.toFixed(4));
        setStep(
          Math.min(
            STEPS.length - 1,
            Math.floor(p * STEPS.length * 0.999 + 0.12),
          ),
        );
      }
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  // Reveals: content is visible by default and only waits once JS is here.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const targets = root.querySelectorAll<HTMLElement>("[data-reveal]");
    if (
      !("IntersectionObserver" in window) ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      for (const t of targets) t.dataset.in = "";
      return;
    }
    // Whatever is already on screen stays put; only what is below the fold
    // waits to rise in.
    for (const t of targets) {
      const box = t.getBoundingClientRect();
      if (box.top < innerHeight && box.bottom > 0 && box.left < innerWidth)
        t.dataset.in = "";
    }
    root.classList.add("mk-ready");
    // A masked element has no visible area, so it can never "intersect".
    // Watch its unmasked parent and release everything waiting inside it.
    const unmasked = (t: HTMLElement) =>
      t.matches(".mk-frame, .mk-final, .mk-promises")
        ? t
        : (t.parentElement ?? t);
    const waiting = new Map<Element, HTMLElement[]>();
    for (const t of targets) {
      if ("in" in t.dataset) continue;
      const key = unmasked(t);
      waiting.set(key, [...(waiting.get(key) ?? []), t]);
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          for (const t of waiting.get(entry.target) ?? []) t.dataset.in = "";
          observer.unobserve(entry.target);
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" },
    );
    for (const key of waiting.keys()) observer.observe(key);
    return () => observer.disconnect();
  }, []);

  // Escape closes the phone menu.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) =>
      e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  const words = SENTENCE.split(" ");

  return (
    <div className="marketing" id="top" ref={rootRef}>
      <a className="mk-skip" href="#main">
        Skip to content
      </a>

      <div className="mk-intro" aria-hidden="true">
        <ShoulderMark className="mk-intro-mark" />
      </div>

      <header
        className="mk-nav"
        ref={navRef}
        data-open={menuOpen ? "true" : "false"}
      >
        <Link href="#top" className="mk-logo" aria-label="Shoulder home">
          <ShoulderWordmark />
        </Link>
        <nav className="mk-desktop-nav" aria-label="Main navigation">
          <a href="#approach">How it works</a>
          <a href="#product">Product</a>
          <a href="#about">Privacy</a>
        </nav>
        <div className="mk-nav-actions">
          <Link href="/auth/sign-in" className="mk-sign-in">
            Sign in
          </Link>
          <details
            className="mk-mobile-menu"
            open={menuOpen}
            onToggle={(e) => setMenuOpen(e.currentTarget.open)}
          >
            <summary aria-label={menuOpen ? "Close menu" : "Open menu"}>
              {menuOpen ? (
                <X aria-hidden="true" size={20} />
              ) : (
                <Menu aria-hidden="true" size={20} />
              )}
            </summary>
            <nav aria-label="Mobile navigation">
              {[
                ["#approach", "How it works"],
                ["#product", "Product"],
                ["#about", "Privacy"],
                ["/auth/sign-in", "Sign in"],
              ].map(([href, label], i) => (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setMenuOpen(false)}
                  style={{ "--i": i } as CSSProperties}
                >
                  {label}
                  <ArrowRight aria-hidden="true" size={18} />
                </Link>
              ))}
            </nav>
          </details>
        </div>
        <span className="mk-read" aria-hidden="true" />
      </header>

      <main id="main">
        {/* ---------------------------------------------------------- Hero */}
        <section
          className="mk-hero"
          ref={heroRef}
          aria-labelledby="mk-hero-title"
        >
          <div className="mk-hero-copy">
            <h1 id="mk-hero-title">
              <span className="mk-line">
                <span>SEE THE GAME</span>
              </span>{" "}
              <span className="mk-line">
                <span>TAKE SHAPE.</span>
              </span>
            </h1>
            <div className="mk-hero-bottom">
              <p>
                Turn match film into a few moments worth another look. Chosen by
                a coach. Made for the player.
              </p>
              <CtaLink>Open Shoulder</CtaLink>
            </div>
          </div>

          <div className="mk-hero-visual" aria-hidden="true">
            <div className="mk-iris">
              <div className="mk-iris-inner">
                <Image
                  src={pitch}
                  alt=""
                  fill
                  priority
                  placeholder="blur"
                  sizes="(max-width: 900px) 100vw, 60vw"
                />
              </div>
            </div>
            <PitchLines />
            <Formation />
            <div className="mk-tag mk-tag-top">
              <span className="mk-live" /> Match film <MatchClock />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------- The scan */}
        <section
          className="mk-scan"
          id="approach"
          ref={scanRef}
          aria-label="How Shoulder works, from match film to one clip"
          data-step={step}
        >
          <div className="mk-scan-stick">
            <div className="mk-scan-track">
              {/* 1 · Watch */}
              <article className="mk-frame mk-frame-watch" data-reveal>
                <div className="mk-frame-copy">
                  <h2>
                    A whole match.
                    <br />
                    <span>A few moments worth returning to.</span>
                  </h2>
                  <p>
                    The game moves quickly. Development takes another look.
                    Shoulder gives a coach room to find a moment and say what
                    they saw.
                  </p>
                </div>
                <div className="mk-ruler-wrap" aria-hidden="true">
                  <div className="mk-thumbs">
                    {["12:04", "31:50", "58:12", "73:38"].map((t, i) => (
                      <figure
                        key={t}
                        style={
                          {
                            "--i": i,
                            "--x": `${[13, 35, 65, 82][i]}%`,
                            "--y": `${[34, 64, 30, 66][i]}%`,
                          } as CSSProperties
                        }
                      >
                        <Image src={pitch} alt="" fill sizes="220px" />
                        <figcaption>{t}</figcaption>
                      </figure>
                    ))}
                  </div>
                  <div className="mk-ruler">
                    <div className="mk-ticks" />
                    {[13, 35, 65, 82].map((left, i) => (
                      <i
                        key={left}
                        style={{ left: `${left}%`, "--i": i } as CSSProperties}
                      />
                    ))}
                    <b className="mk-playhead" />
                  </div>
                  <div className="mk-ruler-labels">
                    <span>00:00</span>
                    <span>45:00</span>
                    <span>90:00</span>
                  </div>
                </div>
              </article>

              {/* 2 · Mark */}
              <article className="mk-frame mk-frame-mark" data-reveal>
                <div className="mk-frame-copy">
                  <h2>
                    Look closer.
                    <br />
                    <span>Mark where it starts and ends.</span>
                  </h2>
                  <p>
                    Find the sequence, set its in and out points, and keep the
                    rest of the match where it belongs: with the coach.
                  </p>
                </div>
                <div className="mk-viewer" aria-hidden="true">
                  <div className="mk-viewer-film">
                    <Image
                      src={pitch}
                      alt=""
                      fill
                      sizes="(max-width: 900px) 100vw, 50vw"
                    />
                    <span className="mk-bracket mk-bracket-l" />
                    <span className="mk-bracket mk-bracket-r" />
                    <span className="mk-viewer-time">73:42</span>
                  </div>
                  <div className="mk-viewer-bar">
                    <span>IN 73:38</span>
                    <div>
                      <i />
                    </div>
                    <span>OUT 73:48</span>
                  </div>
                </div>
              </article>

              {/* 3 · Say why */}
              <article className="mk-frame mk-frame-say" data-reveal>
                <div className="mk-frame-copy">
                  <h2>
                    The film shows the play.
                    <br />
                    <span>The coach gives it meaning.</span>
                  </h2>
                  <p>
                    Shoulder does not grade a player. The coach chooses the
                    moment, writes one sentence in their own words, and decides
                    what to share.
                  </p>
                </div>
                <div className="mk-judgment" aria-hidden="true">
                  <div className="mk-judgment-head">
                    <span>73:38 – 73:48</span>
                    <span>Goal: check your shoulder</span>
                  </div>
                  <div className="mk-verdicts">
                    <span className="mk-verdict mk-verdict-on">
                      You did this.
                    </span>
                    <span className="mk-verdict">Chance to do this.</span>
                  </div>
                  <p className="mk-sentence">
                    {words.map((w, i) => (
                      <span
                        key={`w${String(i).padStart(2, "0")}${w}`}
                        style={{ "--w": i } as CSSProperties}
                      >
                        {w}{" "}
                      </span>
                    ))}
                    <i className="mk-caret" />
                  </p>
                  <div className="mk-judgment-foot">
                    <span>Written by the coach</span>
                    <span className="mk-publish">Publish</span>
                  </div>
                </div>
              </article>

              {/* 4 · Share */}
              <article className="mk-frame mk-frame-share" data-reveal>
                <div className="mk-frame-copy">
                  <h2>
                    Only their clip.
                    <br />
                    <span>Only their coach&apos;s words.</span>
                  </h2>
                  <p>
                    Three to six short clips per game, tied to one development
                    goal. Players watch on their phone and never receive the
                    full match.
                  </p>
                </div>
                <div className="mk-phone" aria-hidden="true">
                  <div className="mk-phone-screen">
                    <div className="mk-phone-top">
                      <ShoulderMark width={18} height={18} />
                      <span>Clip 2 of 4</span>
                    </div>
                    <div className="mk-phone-clip">
                      <Image src={pitch} alt="" fill sizes="260px" />
                      <span className="mk-phone-pause">
                        <Pause size={16} />
                      </span>
                      <div className="mk-phone-progress">
                        <i />
                      </div>
                    </div>
                    <span className="mk-phone-verdict">You did this.</span>
                    <p>{SENTENCE}</p>
                    <div className="mk-phone-reflect">
                      What did you notice? <small>Optional</small>
                    </div>
                  </div>
                </div>
              </article>
            </div>

            <ol className="mk-steps" aria-hidden="true">
              {STEPS.map((s, i) => (
                <li key={s} data-on={step >= i ? "" : undefined}>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ------------------------------------------ Shoulder to shoulder */}
        <section
          className="mk-both"
          id="product"
          aria-labelledby="mk-both-title"
        >
          <div className="mk-both-head">
            <h2 id="mk-both-title">Shoulder to shoulder.</h2>
            <p>
              The coach stands beside the player, not above them. One workspace
              for the coach&apos;s week, one private home for the player.
            </p>
          </div>

          <div className="mk-both-grid">
            <article className="mk-side mk-side-coach" data-reveal>
              <h3>
                For the coach. <span>From the match into the week.</span>
              </h3>
              <ol className="mk-week">
                {[
                  ["Set a development goal", "One active focus per player"],
                  [
                    "Choose the match moments",
                    "Three to six clips, one sentence each",
                  ],
                  [
                    "Plan the next week",
                    "One to eight library drills for a player or team",
                  ],
                  [
                    "Read what comes back",
                    "Optional reflections and player sessions",
                  ],
                ].map(([title, sub], i) => (
                  <li key={title} style={{ "--i": i } as CSSProperties}>
                    <strong>{title}</strong>
                    <small>{sub}</small>
                  </li>
                ))}
              </ol>
              <div className="mk-plan">
                <div className="mk-plan-head">
                  <span>Coach plan</span>
                  <span>This week</span>
                </div>
                <p>Check your shoulder before you receive.</p>
                {[
                  ["Scanning", "Look before the pass"],
                  ["First touch", "Open body, first touch"],
                  ["Half-turn", "Receive and turn"],
                ].map(([focus, title]) => (
                  <div className="mk-plan-item" key={focus}>
                    <span>{focus}</span>
                    <strong>{title}</strong>
                  </div>
                ))}
              </div>
            </article>

            <article className="mk-side mk-side-player" data-reveal>
              <h3>
                For the player. <span>A goal to follow. Room to grow.</span>
              </h3>
              <div className="mk-home">
                <div className="mk-home-goal">
                  <small>Your active goal</small>
                  <strong>Check your shoulder before you receive.</strong>
                  <span>One focus, chosen with your coach.</span>
                </div>
                <div className="mk-home-grid">
                  {[
                    ["Latest coach clips", "Moments from the match"],
                    ["Your notes", "What did you notice?"],
                    ["Try this today", "Scan, then receive"],
                    ["From your coach", "A plan for the week"],
                  ].map(([k, v], i) => (
                    <div key={k} style={{ "--i": i } as CSSProperties}>
                      <small>{k}</small>
                      <strong>{v}</strong>
                    </div>
                  ))}
                </div>
              </div>
              <p className="mk-side-note">
                A record of moments, not a rating. Clips sit in a Progress
                timeline organized by goal; reflection is always optional.
              </p>
            </article>
          </div>
          <p className="mk-fineprint">
            Product illustrations with licensed match photography. No player
            account, private footage, or personal data shown.
          </p>
        </section>

        {/* ------------------------------------------- Between matches */}
        <section className="mk-train" aria-labelledby="mk-train-title">
          <div className="mk-train-head">
            <h2 id="mk-train-title">
              Between matches, <span>the work keeps going.</span>
            </h2>
            <p>
              Train away from match day without turning practice into a score.
              The tools stay close to the coach&apos;s goal while the player
              decides what to film, explore, and track.
            </p>
          </div>
          <div className="mk-bento">
            <article className="mk-tile mk-tile-film" data-reveal>
              <div className="mk-tile-art" aria-hidden="true">
                <Image
                  src={pitch}
                  alt=""
                  fill
                  sizes="(max-width: 900px) 100vw, 40vw"
                />
                <span className="mk-rec">
                  <i /> Rec
                </span>
              </div>
              <h3>Your own practice film.</h3>
              <p>
                Record or upload a drill video. It belongs to the player, stays
                private from the coach, and is deleted after 90 days.
              </p>
            </article>

            <article className="mk-tile mk-tile-pose" data-reveal>
              <div className="mk-tile-art" aria-hidden="true">
                <svg viewBox="0 0 320 190" fill="none" aria-hidden="true">
                  <path
                    className="mk-pose-ground"
                    d="M0 162h320M236 162l28-40h56M60 162l18-24"
                  />
                  <path
                    className="mk-pose-swing"
                    d="M178 150c14 4 26 -2 34 -16"
                    pathLength={1}
                  />
                  <path
                    className="mk-pose-bones"
                    pathLength={1}
                    d="M160 53l5 44M148 59l24-2M158 98l14-2M148 59l-22 8-18-7M172 57l18 13 9 16M158 98l-8 28 2 30 11 2M172 96l18 22 22 12"
                  />
                  <circle className="mk-pose-head" cx="158" cy="42" r="9" />
                  <g className="mk-pose-joints">
                    {[
                      [160, 53],
                      [148, 59],
                      [172, 57],
                      [126, 67],
                      [190, 70],
                      [158, 98],
                      [172, 96],
                      [150, 126],
                      [190, 118],
                      [152, 156],
                      [108, 60],
                      [199, 86],
                      [163, 158],
                      [212, 130],
                    ].map(([cx, cy], i) => (
                      <circle
                        key={`${cx}-${cy}`}
                        cx={cx}
                        cy={cy}
                        r="3.4"
                        style={{ "--i": i } as CSSProperties}
                      />
                    ))}
                  </g>
                  <circle className="mk-pose-ball" cx="224" cy="137" r="6.5" />
                  <text x="12" y="22">
                    On-device pose
                  </text>
                </svg>
              </div>
              <h3>See the movement.</h3>
              <p>
                Browser-based pose analysis draws a skeleton over practice video
                on the phone. Body points stay on the device; only summary
                angles are shared when training ideas are requested.
              </p>
            </article>

            <article className="mk-tile mk-tile-drills" data-reveal>
              <div className="mk-tile-art mk-marquee" aria-hidden="true">
                {[0, 1].map((row) => (
                  <div key={row} className="mk-marquee-row" data-row={row}>
                    {["a", "b"].flatMap((copy) =>
                      DRILLS.map((d) => <span key={copy + d}>{d}</span>),
                    )}
                  </div>
                ))}
              </div>
              <h3>Find the next repetition.</h3>
              <p>
                Explore 12 coach-written drills by focus. Up to three software
                training ideas can be suggested for a goal, labelled “AI
                suggestion”. The coach&apos;s notes always come from the coach.
              </p>
            </article>

            <article className="mk-tile mk-tile-sessions" data-reveal>
              <div className="mk-tile-art" aria-hidden="true">
                <PitchLines className="mk-pitch-dark" />
                <svg
                  className="mk-heat"
                  viewBox="0 0 760 500"
                  aria-hidden="true"
                >
                  <path
                    className="mk-heat-path"
                    pathLength={1}
                    d="M150 380 C240 300 300 360 360 270 S520 160 600 220 S640 340 520 360 S300 420 260 300"
                  />
                  {[
                    [360, 270, 70],
                    [520, 200, 54],
                    [250, 330, 46],
                    [560, 340, 40],
                  ].map(([cx, cy, r], i) => (
                    <circle
                      key={`${cx}-${cy}`}
                      cx={cx}
                      cy={cy}
                      r={r}
                      style={{ "--i": i } as CSSProperties}
                    />
                  ))}
                </svg>
              </div>
              <h3>Remember where you played.</h3>
              <p>
                Record a session on the phone: distance, top speed, sprints, a
                position heatmap, half-time split, and 12-week history. Raw GPS
                location stays on the device.
              </p>
            </article>
          </div>
        </section>

        {/* Pilot: only while the marketplace flag is on (lib/marketplace). */}
        {PILOT ? (
          <section className="mk-pilot" aria-labelledby="mk-pilot-title">
            <div className="mk-pilot-copy" data-reveal>
              <h2 id="mk-pilot-title">Another way to train together.</h2>
              <p className="mk-pilot-chip">
                Adults-only pilot · 18+ · Stripe test mode
              </p>
              <p>
                Adults who confirm their birth year can browse verified coaches
                and book a one-to-one session at a public venue. Under-18s
                cannot browse or book. Four demo coaches are listed and no real
                charge or payout occurs yet.
              </p>
            </div>
            <ol className="mk-pilot-steps" data-reveal>
              <li>
                <strong>Find</strong>
                <span>
                  Coaches whose background-check document has been reviewed by
                  the Shoulder team.
                </span>
              </li>
              <li>
                <strong>Book</strong>
                <span>
                  A public-venue slot. Cancel 24 hours or more ahead for a
                  refund; report a concern when needed.
                </span>
              </li>
              <li>
                <strong>Coach</strong>
                <span>
                  Set up a profile and time slots, submit checks for approval,
                  and connect Stripe payouts.
                </span>
              </li>
            </ol>
          </section>
        ) : null}

        {/* ------------------------------------------------ Privacy */}
        <section
          className="mk-privacy"
          id="about"
          aria-labelledby="mk-privacy-title"
        >
          <h2 id="mk-privacy-title">
            Their game.
            <br />
            Their space.
          </h2>
          <ul className="mk-promises" data-reveal>
            {[
              "Players see only their own published clips. Never the full match.",
              "Practice video belongs to the player and is deleted after 90 days.",
              "Reflections are optional. Only their author can edit or delete them.",
            ].map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>

        {/* ------------------------------------------------ Close */}
        <section
          className="mk-final"
          aria-labelledby="mk-final-title"
          data-reveal
        >
          <PitchLines className="mk-final-pitch" />
          <div className="mk-final-inner">
            <h2 id="mk-final-title">
              The next play starts <br />
              with a closer look.
            </h2>
            <CtaLink className="mk-button-signal">Open Shoulder</CtaLink>
          </div>
          <span className="mk-final-time" aria-hidden="true">
            90+4
          </span>
        </section>
      </main>

      <footer className="mk-footer">
        <ShoulderWordmark />
        <p>Coach-led soccer development. Private by design.</p>
        <a href="#top">Back to top</a>
        <span>© {new Date().getFullYear()} Shoulder</span>
      </footer>
    </div>
  );
}
