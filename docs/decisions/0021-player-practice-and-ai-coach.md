# ADR 0021 — Player practice uploads and AI coach

Status: accepted by owner, 2026-09-23. Scope: public demo with synthetic data only.

## Decision

The owner chose to refocus the product on players, and to ship a public demo for
college applications:

1. Players may upload their own **practice videos** into a player-owned private
   space (`practice_video`). This is separate from coach match footage; coaches
   cannot read it, and it expires 90 days after upload completion.
2. Players may ask an **AI coach** for training guidance on a practice video.
   Pose landmarks are extracted **on the device** with MediaPipe Pose Landmarker
   (Apache-2.0). Only derived, non-identifying movement features (joint-angle
   summaries, turn counts, tempo) leave the browser. An LLM served through
   OpenRouter turns those features plus the player's active `development_goal` into
   drill suggestions stored as `ai_coach_feedback`.

## What this supersedes, and what it does not

| Rule | Change |
|---|---|
| 1 (human coach authors every judgment) | **Unchanged for `judgment`.** AI text is a separate record type, `ai_coach_feedback`, never a `judgment`, always labelled "AI suggestion" in the UI, and never shown in coach-published evidence. |
| 2 (no scores or comparisons) | **Unchanged.** Prompts and output filters forbid ratings, percentages, ranks, and comparisons with other players. |
| 4 (no full-match access) | **Unchanged.** Practice videos are the player's own files. |
| 5 (no ML before Phase D) | **Waived for the practice lane only.** The retrieval/CV roadmap for coach footage (Blocks 08–10) stays gated. |
| 6 (no persistent biometric data) | **Unchanged.** Landmarks never leave the device and are never stored; the stored features are aggregate angles/counts and cannot identify a person. |

## Conditions

- Synthetic demo data only. Onboarding real minors requires the open retention
  decisions in `STATUS.md`, the real-use gate, and a consent/legal review of AI
  feedback to users aged 13–18.
- The LLM output goes through a server-side filter (length, banned words from
  `AGENTS.md` player copy, no numbers presented as scores) before storage.
- AI feedback is on demand, never a push or nudge.
