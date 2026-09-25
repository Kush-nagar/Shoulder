# ADR 0023 — Session tracking and team leaderboards

Status: accepted by owner, 2026-09-24. Amends AGENTS.md rule 2 for one surface only.

## Decision

Borrowing from the owner's Ballers Club app, players may record training and
match sessions with their phone's GPS, see their own stats and heatmap, and
compare *physical tracking* totals with teammates on an opt-in team leaderboard.

## What changes

| Rule | Change |
|---|---|
| 2 (no scores or comparisons) | **Waived only for the team leaderboard** of GPS tracking totals (distance, sprint count, top speed, sessions). Coach judgments, reflections, practice videos, pose features and AI suggestions are never ranked, scored or compared. |
| 6 (no persistent biometric data) | **Unchanged.** No heart rate, no identity data. Raw GPS points never leave the device; only aggregates and a pitch-normalised heatmap grid are stored. |
| Player copy | "Personal best" is shown as a plain fact on the player's own progress chart. No confetti, badges, streaks, or nudges. |

## Guardrails (required)

1. **Opt-in, per player, default off.** Leaving hides the player immediately.
2. **Team-scoped.** Only members of the same team (players and its coach) see a
   team's board. No global or cross-team boards.
3. **Nickname, not name.** Joining requires a nickname (2–20 letters, digits,
   spaces; screened against a short blocklist). Real names are never shown.
4. **Tracking totals only.** Weekly and season views; no "worst" ordering, no
   bottom-of-table highlighting, no percentages.
5. **Location privacy.** Latitude/longitude are processed in the browser and
   discarded; the server stores distance, speeds, sprint counts, durations,
   half-time split, and a 12×8 heatmap grid with no geographic reference.
6. **Public demo.** Demo FC is one team of strangers; the same opt-in and
   nickname rules apply. Real-data onboarding stays blocked until consent
   review covers tracking and leaderboards for users aged 13–18.

## Not in scope

Heart rate and Apple Watch (needs a native app), public/global leaderboards,
outside-coach marketplace (separate design, later).
