# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Coach** (laptop, 10–25 minutes after a game): sets one development goal per player, uploads match film, marks three to six moments, writes one sentence each, publishes isolated player clips, plans weekly drills.
- **Player** (phone, 3–5 minutes after publication; ages 13–18): watches only their own published clips, may write an optional reflection, records own practice and sessions, browses drills.
- Landing audience: coaches and players/parents equally (owner, 2026-10-03).

## Product Purpose

Coach-led soccer development. A human coach turns match film into a few meaningful moments for one player's active goal. Success: the player understands one clear next step, in the coach's own words.

## Positioning

The coach makes every judgment; the software never grades, ranks, or writes player-facing text. "Check your shoulder" is the coach's phrase for looking before receiving; shoulder-to-shoulder is the relationship.

## Operating Context

Sideline phone film, post-match review on a laptop, phone viewing for players. Marketplace pilot (adults 18+, Stripe test mode, four demo coaches) is off by default behind a flag.

## Capabilities and Constraints

- Verdicts render exactly "You did this." / "Chance to do this."; `not_relevant` never reaches players.
- No scores, ratings, rankings, leaderboards, streaks, badges, nudges, or engagement pressure.
- Players never receive full-match video. Practice video is private to the player and deleted after 90 days.
- Avoid in copy: failed, weak, incorrect, performance score, insights, unlock, level up, elite, AI-powered.
- Domain words: observation, judgment, review_publication, player_reflection, development_goal, evidence_clip.

## Brand Commitments

Name "Shoulder", bracket wordmark (`components/brand.tsx`). Owner chose to keep the existing brand (ink, warm paper, signal lime `#DFFF3F`, Archivo condensed display, Inter Tight UI, Geist Mono data) and elevate it rather than replace it (2026-10-03).

## Evidence on Hand

One licensed Pexels aerial match photo (`public/marketing-pitch.jpg`). No testimonials, customer logos, metrics, or real player footage exist; never fabricate them. Product depictions are labelled illustrations.

## Product Principles

1. The coach authors; the product frames.
2. A few moments over a whole match.
3. Private by default; the player owns their space.
4. Calm over compulsive: nothing pressures a child to return.

## Accessibility & Inclusion

Minors use the product. WCAG AA contrast, keyboard access, reduced-motion parity (every animation sits behind `prefers-reduced-motion: no-preference`), axe-clean homepage at 390/768/1440.
