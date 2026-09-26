"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { ShoulderWordmark } from "../components/brand";
import "./marketing.css";

function PitchLines({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 760 500"
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid meet"
    >
      <rect x="38" y="38" width="684" height="424" stroke="currentColor" />
      <path
        d="M380 38v424M38 146h115v208H38m684-208H607v208h115M38 191h45v118H38m684-118h-45v118h45"
        stroke="currentColor"
      />
      <circle cx="380" cy="250" r="66" stroke="currentColor" />
      <circle cx="380" cy="250" r="3" fill="currentColor" />
      <path
        d="M153 182a76 76 0 0 1 0 136m454-136a76 76 0 0 0 0 136"
        stroke="currentColor"
      />
    </svg>
  );
}

function Formation() {
  return (
    <svg
      className="mk-formation"
      viewBox="0 0 760 500"
      fill="none"
      aria-hidden="true"
    >
      <path className="mk-route mk-route-one" d="M207 254 Q316 214 394 217" />
      <path className="mk-route mk-route-two" d="M394 217 Q496 171 568 114" />
      <path className="mk-run" d="M490 317 Q526 224 568 114" />
      <path className="mk-space" d="M394 217 568 114 490 317Z" />
      <g className="mk-players">
        <circle cx="112" cy="250" r="7" />
        <circle cx="207" cy="122" r="7" />
        <circle cx="207" cy="254" r="9" className="mk-active-player" />
        <circle cx="207" cy="380" r="7" />
        <circle cx="310" cy="148" r="7" />
        <circle cx="394" cy="217" r="9" className="mk-second-player" />
        <circle cx="312" cy="351" r="7" />
        <circle cx="490" cy="317" r="7" className="mk-runner" />
        <circle cx="570" cy="114" r="9" className="mk-receiver" />
        <circle cx="576" cy="386" r="7" />
        <circle cx="650" cy="250" r="7" />
      </g>
      <circle className="mk-ball" cx="224" cy="242" r="4" />
      <path className="mk-ball-tail" d="M233 239h18" />
      <text x="580" y="100" className="mk-field-number">
        17
      </text>
      <text x="374" y="198" className="mk-field-number">
        08
      </text>
    </svg>
  );
}

function Arrow() {
  return (
    <span aria-hidden="true" className="mk-arrow">
      ↗
    </span>
  );
}

export function MarketingPage() {
  const heroRef = useRef<HTMLElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLDetailsElement>(null);
  const closeMenu = () => {
    if (menuRef.current) menuRef.current.open = false;
  };

  useEffect(() => {
    const hero = heroRef.current;
    const nav = navRef.current;
    if (!hero || !nav) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let frame = 0;
    const update = () => {
      frame = 0;
      if (window.innerWidth > 760) {
        const distance = Math.max(1, hero.offsetHeight - window.innerHeight);
        const progress = Math.min(
          1,
          Math.max(0, -hero.getBoundingClientRect().top / distance),
        );
        hero.style.setProperty("--mk-progress", progress.toFixed(3));
        hero.style.setProperty(
          "--mk-aperture",
          `${(21 + progress * 87).toFixed(1)}%`,
        );
      } else {
        hero.style.removeProperty("--mk-progress");
        hero.style.removeProperty("--mk-aperture");
      }
      nav.dataset.scrolled = window.scrollY > 24 ? "true" : "false";
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

  return (
    <div className="marketing" id="top">
      <a className="mk-skip" href="#main">
        Skip to content
      </a>
      <header className="mk-nav" ref={navRef}>
        <Link href="#top" className="mk-logo" aria-label="Shoulder home">
          <ShoulderWordmark />
        </Link>
        <nav className="mk-desktop-nav" aria-label="Main navigation">
          <a href="#approach">The approach</a>
          <a href="#product">Product</a>
          <a href="#about">About</a>
        </nav>
        <div className="mk-nav-actions">
          <Link href="/auth/sign-in" className="mk-sign-in">
            Sign in <Arrow />
          </Link>
          <details className="mk-mobile-menu" ref={menuRef}>
            <summary>
              Menu <span aria-hidden="true">+</span>
            </summary>
            <nav aria-label="Mobile navigation">
              <Link href="#approach" onClick={closeMenu}>
                The approach
              </Link>
              <Link href="#product" onClick={closeMenu}>
                Product
              </Link>
              <Link href="#about" onClick={closeMenu}>
                About
              </Link>
              <Link href="/auth/sign-in" onClick={closeMenu}>
                Sign in
              </Link>
            </nav>
          </details>
        </div>
      </header>

      <main id="main">
        <section
          className="mk-hero"
          ref={heroRef}
          aria-labelledby="mk-hero-title"
        >
          <div className="mk-hero-sticky">
            <div className="mk-hero-copy">
              <p className="mk-eyebrow">
                <span className="mk-signal-dot" /> Soccer, seen clearly{" "}
                <span className="mk-index">01 / 05</span>
              </p>
              <h1 id="mk-hero-title">
                SEE THE GAME <br />
                <em>TAKE SHAPE.</em>
              </h1>
              <div className="mk-hero-bottom">
                <p>
                  Turn match film into moments worth another look. Chosen by a
                  coach. Made for the player.
                </p>
                <Link className="mk-button" href="/auth/sign-in">
                  Open Shoulder <Arrow />
                </Link>
              </div>
            </div>
            <div className="mk-hero-visual" aria-hidden="true">
              <div className="mk-photo-aperture">
                <Image
                  src="/marketing-pitch.jpg"
                  alt=""
                  fill
                  priority
                  sizes="(max-width: 760px) 100vw, 62vw"
                />
              </div>
              <PitchLines className="mk-hero-pitch" />
              <Formation />
              <div className="mk-art-label mk-art-label-top">
                MATCH FILM / 73:42
              </div>
              <div className="mk-art-label mk-art-label-bottom">
                <span>THE SPACE BETWEEN</span>
                <span>17 / RUN INTO SPACE</span>
              </div>
              <div className="mk-hero-corner">S</div>
            </div>
            <div className="mk-hero-scroll" aria-hidden="true">
              <span>Scroll to follow the play</span>
              <span className="mk-scroll-line" />
            </div>
          </div>
        </section>

        <section
          className="mk-scale mk-section"
          aria-labelledby="mk-scale-title"
          id="approach"
        >
          <div className="mk-section-top">
            <span>01 / THE MATCH</span>
            <span>EVERY MINUTE HOLDS CONTEXT</span>
          </div>
          <div className="mk-scale-grid">
            <p className="mk-scale-number" aria-hidden="true">
              90<span>MIN</span>
            </p>
            <h2 id="mk-scale-title">
              A WHOLE MATCH.
              <br />
              <em>A FEW MOMENTS</em>
              <br />
              WORTH RETURNING TO.
            </h2>
            <p className="mk-scale-note">
              The game moves quickly. Development takes another look. Shoulder
              gives a coach the space to find a moment and say what they saw.
            </p>
          </div>
          <div className="mk-timeline" aria-hidden="true">
            <span>00:00</span>
            <div>
              <i />
              <i />
              <i />
              <i />
            </div>
            <span>90:00</span>
          </div>
        </section>

        <section
          className="mk-process mk-section"
          aria-labelledby="mk-process-title"
        >
          <div className="mk-section-top">
            <span>02 / FROM FILM TO MOMENT</span>
            <span>ONE CONTINUOUS PLAY</span>
          </div>
          <div className="mk-process-head">
            <h2 id="mk-process-title">
              LOOK CLOSER.
              <br />
              <em>THEN SAY WHY.</em>
            </h2>
            <p>
              Find the sequence. Mark its beginning and end. Add a coach&apos;s
              judgment. Publish only the clip a player needs.
            </p>
          </div>
          <div className="mk-film-strip">
            <div className="mk-film-photo">
              <Image
                src="/marketing-pitch.jpg"
                alt="Aerial view of a soccer match under lights"
                fill
                sizes="(max-width: 760px) 100vw, 72vw"
              />
              <div className="mk-film-crosshair" aria-hidden="true">
                <span>IN 73:38</span>
                <span>OUT 73:48</span>
              </div>
            </div>
            <div className="mk-film-side" aria-hidden="true">
              <span>FRAME / 024</span>
              <span className="mk-film-time">73:42</span>
              <span>
                OPEN SPACE
                <br />
                AHEAD OF THE BALL
              </span>
              <div className="mk-film-mini-line" />
            </div>
          </div>
          <div className="mk-process-steps">
            <span>
              <b>01</b> Watch the match
            </span>
            <span>
              <b>02</b> Mark the moment
            </span>
            <span>
              <b>03</b> Add your words
            </span>
            <span>
              <b>04</b> Share the clip
            </span>
          </div>
        </section>

        <section className="mk-editorial" aria-labelledby="mk-editorial-title">
          <div className="mk-editorial-image">
            <Image
              src="/marketing-pitch.jpg"
              alt="Floodlit soccer pitch seen from above during play"
              fill
              sizes="100vw"
            />
            <span className="mk-image-caption">
              A VIEW OF THE WHOLE PITCH / NIGHT MATCH
            </span>
          </div>
          <div className="mk-editorial-copy">
            <p className="mk-kicker">THE GAME IS IN THE SPACE</p>
            <h2 id="mk-editorial-title">
              A RUN.
              <br />A PASS.
              <br />
              <em>A POSSIBILITY.</em>
            </h2>
            <p>
              What matters may happen away from the ball. A second look gives
              that movement room to speak.
            </p>
          </div>
        </section>

        <section
          className="mk-dark mk-section"
          aria-labelledby="mk-dark-title"
          id="about"
        >
          <div className="mk-section-top">
            <span>03 / HUMAN JUDGMENT</span>
            <span>THE COACH MAKES THE CALL</span>
          </div>
          <div className="mk-dark-grid">
            <h2 id="mk-dark-title">
              THE FILM
              <br />
              SHOWS THE PLAY.
              <br />
              <em>
                THE COACH
                <br />
                GIVES IT MEANING.
              </em>
            </h2>
            <div className="mk-dark-aside">
              <div className="mk-bracket" aria-hidden="true">
                [&nbsp;&nbsp;&nbsp;]
              </div>
              <p>
                Shoulder does not grade a player. The coach chooses the moment,
                writes the note, and decides what to share.
              </p>
              <div className="mk-verdicts">
                <span>You did this.</span>
                <span>Chance to do this.</span>
              </div>
            </div>
          </div>
        </section>

        <section
          className="mk-product mk-section"
          aria-labelledby="mk-product-title"
          id="product"
        >
          <div className="mk-section-top">
            <span>04 / THE WORKSPACE</span>
            <span>BUILT AROUND THE MATCH</span>
          </div>
          <div className="mk-product-head">
            <h2 id="mk-product-title">
              ONE MATCH.
              <br />
              <em>ONE CLEAR NEXT STEP.</em>
            </h2>
            <p>
              Coach review stays close to the footage. Players receive only
              their own short, published clips.
            </p>
          </div>
          <div className="mk-workspace">
            <div className="mk-workspace-top">
              <span className="mk-workspace-brand">
                SHOULDER / COACH REVIEW
              </span>
              <span>
                MARK MOMENT&nbsp; · &nbsp;ADD NOTE&nbsp; · &nbsp;PUBLISH
              </span>
            </div>
            <div className="mk-workspace-body">
              <div className="mk-workspace-film">
                <Image
                  src="/marketing-pitch.jpg"
                  alt="Overhead soccer match illustrating the coach playback area"
                  fill
                  sizes="(max-width: 760px) 100vw, 65vw"
                />
                <span className="mk-workspace-play" aria-hidden="true">
                  ▶
                </span>
                <div className="mk-workspace-time">
                  73:42 <span> / MATCH FILM</span>
                </div>
              </div>
              <div className="mk-workspace-panel">
                <span className="mk-panel-label">SELECTED MOMENT</span>
                <strong>73:38 — 73:48</strong>
                <div className="mk-panel-rule" />
                <span className="mk-panel-label">COACH JUDGMENT</span>
                <p>You did this.</p>
                <div className="mk-panel-rule" />
                <span className="mk-panel-label">COACH&apos;S NOTE</span>
                <div className="mk-note-lines" aria-hidden="true">
                  <i />
                  <i />
                  <i />
                </div>
                <span className="mk-panel-foot">
                  Only coach-authored words reach the player.
                </span>
              </div>
            </div>
            <div className="mk-workspace-track">
              <span>00:00</span>
              <div>
                <i />
                <i />
                <i />
              </div>
              <span>90:00</span>
            </div>
          </div>
          <p className="mk-preview-note">
            Workflow illustration with licensed match photography. No private
            player footage or data shown.
          </p>
          <div className="mk-product-outro">
            <span>THREE TO SIX MOMENTS</span>
            <p>
              A private sequence of clips, grouped by game and tied to one
              development goal. The player can watch and reflect when ready.
            </p>
          </div>
        </section>

        <section
          className="mk-player mk-section"
          aria-labelledby="mk-player-title"
        >
          <div className="mk-section-top">
            <span>05 / THE PLAYER&apos;S SPACE</span>
            <span>THE WORK CONTINUES BETWEEN GAMES</span>
          </div>
          <div className="mk-expansion-head">
            <h2 id="mk-player-title">
              A GOAL TO FOLLOW.
              <br />
              <em>ROOM TO GROW.</em>
            </h2>
            <p>
              Shoulder brings the coach&apos;s moments and the player&apos;s own
              practice into one private home. Each player has one active
              development goal and sees only their own published clips.
            </p>
          </div>
          <div className="mk-player-layout">
            <div className="mk-player-screen">
              <div className="mk-screen-top">
                <strong>shoulder</strong>
                <span>PLAYER / HOME</span>
              </div>
              <div className="mk-screen-goal">
                <span>YOUR ACTIVE GOAL</span>
                <strong>Check your shoulder before you receive.</strong>
                <small>One focus, chosen with your coach.</small>
              </div>
              <div className="mk-screen-grid">
                <div className="mk-screen-tile mk-screen-tile-signal">
                  <span>TRY THIS TODAY</span>
                  <strong>Scan, then receive</strong>
                  <small>A coach-written drill for your goal</small>
                </div>
                <div className="mk-screen-tile">
                  <span>LATEST COACH CLIPS</span>
                  <strong>Moments from the match</strong>
                  <small>Watch the clips your coach published</small>
                </div>
                <div className="mk-screen-tile">
                  <span>YOUR NOTES</span>
                  <strong>What did you notice?</strong>
                  <small>Reflection is always optional</small>
                </div>
                <div className="mk-screen-tile">
                  <span>THIS WEEK</span>
                  <strong>Your training, in view</strong>
                  <small>Sessions and recent practice</small>
                </div>
                <div className="mk-screen-tile mk-screen-tile-wide">
                  <span>FROM YOUR COACH</span>
                  <strong>A plan for the week</strong>
                  <small>Library drills picked for you or your team</small>
                </div>
              </div>
              <div className="mk-screen-foot">
                HOME &nbsp; / &nbsp; PROGRESS &nbsp; / &nbsp; PRACTICE &nbsp; /
                &nbsp; DRILLS
              </div>
            </div>
            <div className="mk-player-aside">
              <span className="mk-detail-index">01 / FOLLOW THE GOAL</span>
              <h3>A record of moments, not a rating.</h3>
              <p>
                Three to six short clips from a game sit in a Progress timeline
                organized by goal. A player can watch on their phone, add an
                optional reflection, and return to earlier moments over time.
              </p>
              <div className="mk-player-aside-rule" />
              <span className="mk-detail-index">02 / MAKE IT YOURS</span>
              <p>
                The home dashboard also brings together recent practice with
                thumbnails, training ideas, a weekly session summary, coach
                plans, and a short guide to how Shoulder works.
              </p>
            </div>
          </div>
          <p className="mk-preview-note">
            Product illustration. No player account, private footage, or
            personal training data shown.
          </p>
        </section>

        <section
          className="mk-training mk-section"
          aria-labelledby="mk-training-title"
        >
          <div className="mk-section-top">
            <span>06 / BETWEEN MATCHES</span>
            <span>TRAIN ON YOUR OWN TERMS</span>
          </div>
          <div className="mk-expansion-head">
            <h2 id="mk-training-title">
              FILM IT.
              <br />
              <em>FEEL THE DIFFERENCE.</em>
            </h2>
            <p>
              A player can train away from match day without turning practice
              into a score. The tools stay close to the coach&apos;s goal while
              the player decides what to film, explore, and track.
            </p>
          </div>
          <div className="mk-training-grid">
            <article className="mk-training-card mk-training-card-film">
              <span className="mk-detail-index">01 / PRACTICE</span>
              <div className="mk-practice-frame" aria-hidden="true">
                <PitchLines />
                <span>REC &nbsp; ●</span>
              </div>
              <h3>Your own practice film.</h3>
              <p>
                Record or upload a drill video. It belongs to the player, stays
                private from the coach, and is deleted after 90 days.
              </p>
            </article>
            <article className="mk-training-card mk-training-card-pose">
              <span className="mk-detail-index">02 / MOVEMENT</span>
              <div className="mk-pose-graphic" aria-hidden="true">
                <svg
                  viewBox="95 0 310 190"
                  fill="none"
                  preserveAspectRatio="xMidYMid meet"
                  aria-hidden="true"
                >
                  <title>Illustrative on-device pose view</title>
                  <path
                    className="mk-pose-guide"
                    d="M105 38V16h22m244 0h22v22M105 152v22h22m244 0h22v-22M95 95h35m240 0h35"
                  />
                  <path
                    className="mk-pose-shadow"
                    d="M247 43v12m-53 9 53-9 55 8m-108 1-32 27-28-22m168-6 27 28 32-15M247 55v52m-36 4 36-4 37 3m-73 1-23 36-31 26m127-63 32 35 38 28"
                  />
                  <path
                    className="mk-pose-bones"
                    d="M247 43v12m-53 9 53-9 55 8m-108 1-32 27-28-22m168-6 27 28 32-15M247 55v52m-36 4 36-4 37 3m-73 1-23 36-31 26m127-63 32 35 38 28"
                  />
                  <circle className="mk-pose-head" cx="247" cy="25" r="11" />
                  <g className="mk-pose-joints">
                    <circle cx="194" cy="64" r="4.5" />
                    <circle cx="302" cy="63" r="4.5" />
                    <circle cx="162" cy="91" r="4.5" />
                    <circle cx="329" cy="91" r="4.5" />
                    <circle cx="211" cy="111" r="4.5" />
                    <circle cx="284" cy="110" r="4.5" />
                    <circle cx="188" cy="147" r="4.5" />
                    <circle cx="316" cy="145" r="4.5" />
                  </g>
                  <g className="mk-pose-endpoints">
                    <circle cx="134" cy="69" r="4" />
                    <circle cx="361" cy="76" r="4" />
                    <circle cx="157" cy="173" r="4" />
                    <circle cx="354" cy="173" r="4" />
                  </g>
                </svg>
                <span>ON-DEVICE VIEW</span>
                <span className="mk-pose-frame-label">POSE / LOCAL</span>
              </div>
              <h3>See the movement.</h3>
              <p>
                Browser-based pose analysis draws a skeleton over practice video
                on the phone. Body points stay on the device; only summary
                angles are shared when training ideas are requested.
              </p>
            </article>
            <article className="mk-training-card mk-training-card-drills">
              <span className="mk-detail-index">03 / DRILLS &amp; IDEAS</span>
              <div className="mk-drill-graphic" aria-hidden="true">
                <span>SCANNING</span>
                <span>FIRST TOUCH</span>
                <span>HALF-TURN</span>
                <span>PASSING</span>
                <span>BALL MASTERY</span>
                <span>1V1</span>
                <span>BOTH FEET</span>
                <span>DEFENDING</span>
              </div>
              <h3>Find the next repetition.</h3>
              <p>
                Explore 12 coach-written drills by focus. Up to three software
                training ideas can be suggested for a goal, with a limit of 10
                requests a day. They are labelled “AI suggestion”; the
                coach&apos;s notes always come from the coach.
              </p>
            </article>
            <article className="mk-training-card mk-training-card-sessions">
              <span className="mk-detail-index">04 / SESSIONS</span>
              <div className="mk-session-graphic" aria-hidden="true">
                <PitchLines />
                <i />
                <i />
                <i />
                <i />
                <i />
                <span>TRAINING / MATCH</span>
              </div>
              <h3>Remember where you played.</h3>
              <p>
                Record a training session or match on the phone. View distance,
                top speed, sprints, a position heatmap, half-time split, and
                12-week history. Raw GPS location stays on the device.
              </p>
            </article>
          </div>
        </section>

        <section
          className="mk-coach-week mk-section"
          aria-labelledby="mk-coach-week-title"
        >
          <div className="mk-section-top">
            <span>07 / FOR THE COACH</span>
            <span>THE WHOLE WEEK, ONE WORKSPACE</span>
          </div>
          <div className="mk-expansion-head">
            <h2 id="mk-coach-week-title">
              FROM THE MATCH.
              <br />
              <em>INTO THE WEEK.</em>
            </h2>
            <p>
              The coach keeps the human thread: a “This week” dashboard, roster,
              match upload, clip marking and publishing, plus a view of player
              reflections and sessions.
            </p>
          </div>
          <div className="mk-coach-week-grid">
            <div className="mk-coach-week-list">
              <div>
                <span>01</span>
                <strong>Set a development goal</strong>
                <small>One active focus per player</small>
              </div>
              <div>
                <span>02</span>
                <strong>Choose the match moments</strong>
                <small>Three to six clips, one sentence each</small>
              </div>
              <div>
                <span>03</span>
                <strong>Plan the next week</strong>
                <small>One to eight library drills for a player or team</small>
              </div>
              <div>
                <span>04</span>
                <strong>Read what comes back</strong>
                <small>Optional reflections and player sessions</small>
              </div>
            </div>
            <div className="mk-plan-card">
              <div>
                <span>SHOULDER / COACH PLAN</span>
                <span>THIS WEEK</span>
              </div>
              <p>
                CHECK YOUR SHOULDER
                <br />
                BEFORE YOU RECEIVE.
              </p>
              <div className="mk-plan-item">
                <span>01 / SCANNING</span>
                <strong>Look before the pass</strong>
              </div>
              <div className="mk-plan-item">
                <span>02 / FIRST TOUCH</span>
                <strong>Open body, first touch</strong>
              </div>
              <div className="mk-plan-item">
                <span>03 / HALF-TURN</span>
                <strong>Receive and turn</strong>
              </div>
              <small>A coach chooses the drills and writes the plan.</small>
            </div>
          </div>
        </section>

        <section
          className="mk-marketplace mk-section"
          aria-labelledby="mk-marketplace-title"
        >
          <div className="mk-section-top">
            <span>08 / ADULTS-ONLY PILOT</span>
            <span>STRIPE TEST MODE / NO REAL MONEY MOVES</span>
          </div>
          <div className="mk-marketplace-layout">
            <div>
              <p className="mk-marketplace-tag">
                LIVE PILOT &nbsp; ● &nbsp; 18+
              </p>
              <h2 id="mk-marketplace-title">
                ANOTHER WAY
                <br />
                <em>TO TRAIN TOGETHER.</em>
              </h2>
              <p className="mk-marketplace-intro">
                Adults who confirm their birth year can browse verified coaches
                and book a one-to-one session at a public venue. Under-18s
                cannot browse or book in this pilot.
              </p>
              <p className="mk-marketplace-test">
                Four demo coaches are listed. Payments use Stripe test mode, so
                no real charge or payout occurs yet.
              </p>
            </div>
            <div className="mk-marketplace-panel">
              <div>
                <span>01 / FIND</span>
                <p>
                  Browse coaches whose background-check document has been
                  reviewed by the Shoulder team.
                </p>
              </div>
              <div>
                <span>02 / BOOK</span>
                <p>
                  Choose a public-venue slot. Cancel 24 hours or more ahead for
                  a refund; report a concern when needed.
                </p>
              </div>
              <div>
                <span>03 / COACH</span>
                <p>
                  Coaches set up profiles and time slots, submit checks for
                  admin approval, and connect Stripe payouts.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section
          className="mk-privacy mk-section"
          aria-labelledby="mk-privacy-title"
        >
          <div className="mk-section-top">
            <span>09 / THE PLAYER&apos;S CONTROL</span>
            <span>PRIVATE BY DESIGN</span>
          </div>
          <h2 id="mk-privacy-title">
            THEIR GAME.
            <br />
            <em>THEIR SPACE.</em>
          </h2>
          <div className="mk-privacy-grid">
            <p>
              Players see only their own published match clips. Practice video
              belongs to the player. Reflections are optional and only their
              author can edit or delete them.
            </p>
            <p>
              The Profile keeps account controls, System / Light / Dark theme, a
              clear “how your data is used” guide, and sign out within reach.
            </p>
          </div>
        </section>

        <section className="mk-final" aria-label="Get started with Shoulder">
          <PitchLines className="mk-final-pitch" />
          <div className="mk-final-inner">
            <p className="mk-kicker">THE NEXT PLAY STARTS WITH A CLOSER LOOK</p>
            <h2 id="mk-final-title">
              SEE THE GAME <br />
              <em>TAKE SHAPE.</em>
            </h2>
            <Link className="mk-button mk-button-light" href="/auth/sign-in">
              Open Shoulder <Arrow />
            </Link>
          </div>
          <span className="mk-final-time" aria-hidden="true">
            90+4
          </span>
        </section>
      </main>
      <footer className="mk-footer">
        <ShoulderWordmark />
        <p>Coach-led soccer development. Private by design.</p>
        <a href="#top">Back to top ↑</a>
        <span>© {new Date().getFullYear()} Shoulder</span>
      </footer>
    </div>
  );
}
