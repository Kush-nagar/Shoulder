# ADR 0022 — Player app shell and visual refresh

Status: accepted by owner, 2026-09-24. Scope: player routes (`/player/**`) plus
the sign-in and session fallback pages. Coach routes are unchanged.
Spec: `docs/design/player-redesign-brief.md` (owner decisions D1 to D5).

## Decision

1. **Responsive shell.** Replaces the 560 px player column and bottom bar at
   every width. Below 768 px: 56 px top bar (mark, page title, account menu)
   and a fixed four-tab bottom bar. 768 to 1023 px: 88 px left rail, icon over
   label. 1024 px and wider: 240 px sidebar with wordmark, labelled rows,
   "Film practice", and an account block linking to `/player/profile`. Content
   caps at 1200 px. Tabs everywhere: Home, Practice, Drills, Progress. Profile
   is reached from the account menu or block, never a fifth tab.
2. **Display face (D1).** Archivo, condensed (`font-stretch: 75%`, weight
   600), for page titles, the goal hero title, and drill cover titles only.
   Inter Tight stays the UI and body face.
3. **Dark palette (D2).** The reviewed palette from the brief, applied under
   `prefers-color-scheme: dark` or an explicit choice on the Profile page. The
   choice is a `sh-theme` cookie read on the server and rendered as
   `data-theme` on the themed wrapper, so there is no flash and no inline
   script. Only pages that opt in with `.sh-themed` (player routes, sign-in,
   session fallback) theme; coach pages stay light until reviewed.
4. **Icons (D3).** `lucide-react` is the single icon library; icons always sit
   beside a text label. No AI glyph.
5. **Practice posters (D5).** Home makes at most three practice detail calls,
   in parallel, for short-lived signed URLs used as poster frames; any failure
   falls back to a text tile.
6. **Drill library.** Twelve coach-written drills live as static typed content
   in `apps/web/content/drills.ts`. No API, table, or generation.

## New production dependencies

- `@fontsource-variable/archivo` 5.3.0: self-hosted OFL display face with a
  width axis; the platform has no condensed face and the rules forbid runtime
  font requests. License shipped at `/licenses/archivo-OFL.txt`.
- `lucide-react` 1.47.0: labelled navigation and action icons; hand-drawn icon
  paths are not allowed, and it renders in Server Components with per-icon
  tree shaking.

## Unchanged

Product rules 1 to 4, player copy rules, generated API types, existing
endpoints, and every load-bearing test. No backend, API, or migration change.
