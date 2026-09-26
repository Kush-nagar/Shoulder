# ADR 0025 — Public marketing homepage

## Decision

The root route serves a public, coach-led soccer homepage when no verified
session exists. Existing database-backed coach and player redirects remain for
signed-in members. Sign-in stays at `/auth/sign-in`; authenticated product routes
and global product styles are unchanged.

Marketing styles use a scoped warm-paper, ink, and restrained signal-yellow
palette. Existing approved SVG wordmark and installed self-hosted fonts are
reused. The signal color belongs to tactical motion and controls, not the logo.
No animation or UI package is added. CSS/SVG and one passive scroll listener
drive the hero; reduced-motion and small-screen layouts show a static aperture.

One licensed Pexels aerial soccer photograph illustrates the visual sequence.
The coach workspace depiction is explicitly labelled an illustration and uses
no player data, private video, model output, or generated judgment. Copy reflects
current manual review: a human coach chooses moments, writes text, and publishes
isolated player clips. The page makes no CV availability claim.

The expanded product story stays below the original hero and match-film
sequence. Player and coach previews are CSS/SVG illustrations based on the
local product UI, not screenshots of private accounts. The public demo redirects
to sign-in, so it supplies no reusable authenticated imagery. The page omits
the team board under the repository's no-comparison rule. It labels the
owner-reported 18+ coaching pilot and Stripe test payments explicitly; no
marketplace feature flag or payment behavior changes here.
