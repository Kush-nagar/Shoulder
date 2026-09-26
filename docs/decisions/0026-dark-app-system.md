# ADR 0026: Dark-first app system

Status: accepted, 2026-09-26. Scope: the authenticated web app (player,
coach, coaching marketplace, admin, sign-in). Supersedes the visual parts of
ADR 0022 (palette, terracotta action colour, light-only coach pages) and ADR
0024 (motion values). Their structure (shell geometry, `sh-sidebar` cookie,
`[` shortcut, tablet overlay, phone sheet, View Transitions, skeletons) stays.
The public marketing homepage (ADR 0025) is unchanged; the app borrows its
signal lime, ivory, and type so the two read as one brand.

## Decision

1. **Dark by default.** Every app shell carries `.sh-themed`. With no
   `sh-theme` cookie the app is dark; Profile still offers System, Light, and
   Dark, and every choice is now stored explicitly (`system` follows
   `prefers-color-scheme`). Coach pages are themed too.
2. **Palette** (warm, not blue-black): root `#0A0A09`, rail `#0E0E0C`, panel
   `#11110F`, raised `#171714`, popover `#1D1D19`; text `#F5F5F0`, secondary
   `#A4A198`, muted `#8A877F` (the brief's `#77756F` measured 4.1:1 on the
   panel, so it was lifted to 5.0:1); lines white at 8% and 12%; input
   boundary `#66635C` (3.2:1). Functional: warning `#F4C95D`, danger
   `#FF6262`, comparison coral `#FF805C`. The warm-light variant is derived
   from the marketing ivory (`#F2F0E9` / `#F8F7F2`, ink `#11110F`).
3. **Signal lime `#DFFF3F` means "look here".** Used for the active nav item
   (8% tint, 2 px edge marker, lime icon), the playhead, the selected clip,
   the primary action, the active filter, and the focus ring. Not for
   headings, section icons, badges, or decoration. In light mode the same
   roles use ink, with a lime-tinted selected fill.
4. **Type.** Inter Tight for UI, Archivo condensed for page titles only, and
   **Geist Mono** (new) for match data: timestamps, halves, shirt numbers,
   dates in dense lists, counts. Coach UI is 13 to 15 px; page titles 26 to 32
   px; section titles 16 to 20 px.
5. **Shape.** Controls 6 px, buttons 8 px, panels 10 px, media and dialogs
   12 px (Tailwind `rounded-md/lg/xl/2xl` retuned in `@theme`). No shadows
   except the one popover shadow (`shadow-pop`); no gradients, glass, or glow.
6. **Video is the centre.** Coach match and review pages put the footage on a
   night stage with the transport and a custom match timeline attached to it
   (mono ruler, marked clips as ranges, in point, lime playhead, sprite hover
   preview). A native range input stays on top for precise, accessible
   seeking. Review opens as a full-screen workspace with a context bar and a
   clip inspector beside the video from 1280 px; global navigation is hidden
   there (`.sh-review`).
7. **Motion tokens** in `globals.css`: press 100 ms, hover 140, micro 160,
   menus 170, sidebar 210, modal 220 (fade and 0.98 scale), panels 240, page
   280; entry `cubic-bezier(0.22, 1, 0.36, 1)`, exit
   `cubic-bezier(0.55, 0, 1, 0.45)`. Transform and opacity only; everything
   sits behind `prefers-reduced-motion: no-preference`. The one new loop is
   the processing line on a match whose video is being prepared; it carries
   no fake percentage.
8. **Coach dashboard** now leads with the team's matches (real video state,
   one next step each), then players, shared clips, and plans, as dense rows.
   Empty states are a small centre-circle mark, a mono label, one sentence,
   and one action.

## Dependency

- `@fontsource-variable/geist-mono` 5.3.0: self-hosted OFL monospace for
  match data; the platform has no consistent tabular mono and the rules
  forbid runtime font requests. License shipped at
  `/licenses/geist-mono-OFL.txt`; pinned and checked by
  `tests/repository.test.mjs`.

## Unchanged

Routes, API contracts, generated types, auth, copy rules (verdicts stay "You
did this." / "Chance to do this."), keyboard map, accessible names the tests
use, and every load-bearing test. No backend change.
