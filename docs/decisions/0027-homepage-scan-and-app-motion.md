# ADR 0027: Homepage scan and app motion refresh

Status: accepted, 2026-10-03. Scope: public homepage (`app/marketing.*`),
sign-in page, and app-wide motion utilities in `globals.css`. Refines ADR 0025
(homepage) and ADR 0026 (motion values); brand, tokens, routes and API are
unchanged.

## Decision

1. **Homepage structure.** Hero (live formation, photo iris that opens with
   scroll, ticking match clock), then one pinned horizontal "scan" on desktop:
   Watch, Mark, Say why, Share. Below 900 px or with reduced motion the scan is
   a normal vertical flow. Then coach/player side by side, between-matches
   tools, privacy, and the close. Nine numbered editorial sections became six.
2. **Reveals never fade text.** Entrances are a mask wipe (`clip-path`) plus a
   translate, so text contrast holds on every frame, including when an audit
   scrolls content into view. Elements already on screen at load skip the
   hidden state. Masked elements cannot intersect, so the observer watches
   their unmasked parent.
3. **Marketplace pilot section** renders only when
   `NEXT_PUBLIC_MARKETPLACE_ENABLED` is `on`, matching the product flag.
4. **App motion.** A 2 px signal route-progress line on link navigations
   (`components/route-progress.tsx`); `.sh-reveal` scroll-driven reveal
   (`animation-timeline: view()`, transform only, time-based fallback) for
   lower player Home sections; `.sh-lift` transform-only entrance and
   `.sh-draw` line drawing on sign-in; sign-in submit buttons show a pending
   state. `sh-rise` is unchanged.

## Unchanged

No new dependency, no backend change, no copy-rule change. All motion sits
behind `prefers-reduced-motion: no-preference`. Smoke suite (homepage axe at
390/768/1440, reduced motion, sign-in shell at nine widths) passes in
Chromium, Firefox and WebKit.
