# ADR 0024: App-shell motion, collapsible sidebar, and streamed loading

Status: accepted, 2026-09-25. Scope: web only (player, coaching, and coach
shells). Amends ADR 0022 where noted. Patterns and sources:
`docs/design/player-redesign-brief.md`, "Motion & loading, 2026-09-25".

## Decision

1. **Sidebar.** Player and coach shells share one geometry: icon rail from
   768 px, 248 px labelled sidebar from 1024 px with the wordmark centred in
   an 80 px header (the mark alone, centred, on the rail). From 1024 px the
   sidebar collapses to the rail; the choice is the `sh-sidebar` cookie, read
   on the server, so the first paint is already right. On the 768 to 1023 px
   rail the same control opens a labelled overlay with a scrim (Escape or
   the scrim closes it). `[` toggles it outside text fields. Width animates
   through `grid-template-columns`; no layout library.
2. **Icons first (amends ADR 0022 D3).** Rail and collapsed-sidebar items are
   icon-only, named by visually hidden text and shown with a CSS tooltip on
   hover and keyboard focus. Section headings carry one brand-coloured icon.
   Phone bottom tabs keep their labels.
3. **Phone account sheet.** Still a native `<details>`/`<summary>` (works
   before hydration, keeps the "Account menu" name). A client leaf adds a
   bottom sheet that slides in and out, a scrim, Escape, a Tab loop that
   includes the trigger, and focus return.
4. **Loading.** Every fetching route segment has a `loading.tsx` skeleton in
   the shape of its page (flat fill plus one slow shimmer; no spinners). Home
   starts all five reads at once and streams three `<Suspense>` rows (goal and
   drill; week and plans; clips, notes, practice and ideas), so the greeting
   paints with the shell. The coach layout now gates access itself (redirect
   or real 404 above every loading boundary; the requested path comes from an
   `x-shoulder-path` header the proxy always overwrites and the layout
   sanitises) and streams the team label.
5. **Motion.** Route changes use native View Transitions through React's
   `<ViewTransition>` (bundled with Next 16.3, no config flag): the content
   region fades up, the shell holds still, and the active nav marker glides
   between tabs via `view-transition-name`. Sections and card lists rise in a
   short stagger; buttons, tiles and icons have hover and press feedback. All
   motion is CSS or Web APIs and sits behind `prefers-reduced-motion:
   no-preference`; under `reduce` every change is instant and skeletons are
   static. The shimmer is the one looping animation, an owner-requested
   exception to the brief's "no loops" rule, limited to loading placeholders.

## Consequences

- No new dependency. No backend, API, schema, or migration change.
- A `notFound()` raised inside a page (a missing video, session, or goal)
  now renders after the skeleton, so its HTTP status is 200 with the same
  not-found content; shell-level gates (player layout, coach layout) still
  return 307/404. `/coaching` already behaved this way.
- A non-coach at `/coach` gets the root not-found page instead of the coach
  one, because the gate moved into the layout.
