# Coach marketplace — design only (not built)

Status: design document per Block 09B W5. No schema, API, or UI in this
document is implemented. Any build requires the legal/owner review below and
a fresh project block with its own frozen contracts.

## Goals

- Let a parent/guardian (or an 18+ player) find and book paid 1:1 or small-group
  sessions with an independent or team-affiliated coach outside the existing
  team-goal loop.
- Keep the existing product's rules intact: no AI-authored coach feedback, no
  player scoring/ranking, RLS on every table, footage/privacy boundaries per
  `docs/10-security-privacy.md`.
- Make safeguarding (minor protection) and payment compliance first-class,
  not bolted on.

## Non-goals

- Not a replacement for the team/goal/judgment loop; marketplace coaches are a
  separate relationship from a player's team coach.
- No in-app video calls, no live-streamed sessions in v1.
- No coach discovery ranking driven by player performance data, ratings tied
  to minors' identities, or leaderboards of coaches.
- No AI matching, AI-generated coach bios/feedback, or CV-based recommendation.
- No cash/off-platform payment support; no direct bank transfer bypassing Stripe Connect.

## User types

| Type | Age | Capabilities |
|---|---|---|
| Player 13–17 | minor | Browse (guardian-linked account only), never books alone, never messages a coach without guardian in thread |
| Player 18+ | adult | Browse, book, pay, message directly |
| Parent/guardian | adult | Creates/approves minor's linked account, must approve every minor booking, receives copy of all messages involving their minor, can cancel/report |
| Independent coach | adult | Lists services after identity verification + background check clears; sets availability/pricing; cannot see other coaches' clients |
| Team coach | adult | May optionally also be a marketplace coach; existing team-coach role and marketplace-coach role are separate grants, not implied by each other |
| Admin (Shoulder operator) | adult | Reviews verification/background-check status, moderates reports, suspends listings/accounts, cannot read message content except during an active report investigation |

## Safeguarding requirements (mandatory, pre-build)

Modeled on US Center for SafeSport MAAPP and youth-sports marketplace norms.

1. **Verified identity + cleared background check before any listing goes
   live.** No coach profile is visible or bookable pre-clearance. Re-check on
   a recurring cadence (annual, matching typical NGB policy) and on any
   report. Provider candidates: Checkr (developer/API-first) or Sterling
   Volunteers (nonprofit/youth-sector-specific, includes abuse-prevention
   training tracking) — https://checkr.com/resources/articles/coach-background-checks,
   https://www.ankored.com/blog/best-background-check-software-youth-sports.
2. **Guardian account link required for any user under 18.** A minor cannot
   create a bookable account unattached to a guardian; the guardian holds
   payment method and approval authority. No under-13 accounts at all
   (COPPA — Shoulder already excludes under-13 users per `docs/01-product.md`).
3. **No private one-to-one electronic communication with a minor.** Every
   message thread involving a minor always includes the guardian as a
   party (mirrors MAAPP's "open and transparent" electronic-communications
   rule: https://uscenterforsafesport.org/how-to-safely-communicate-with-minor-athletes/,
   https://uscenterforsafesport.org/wp-content/uploads/2021/03/MAAPP_OnePagers_Communication.pdf).
   In-app messaging only — no exchange of phone numbers, personal social
   handles, or personal email inside message content; the system scans/blocks
   obvious contact-info patterns and flags for review.
4. **Message retention and reporting.** All in-app messages retained for a
   fixed window (proposed 365 days, matching season-scoped retention already
   used elsewhere) for abuse investigation; never deleted by either party
   unilaterally; admin can read only after a report opens an investigation
   case (audited access, not routine).
5. **Session location and observability rules.** In-person sessions with a
   minor must occur at a public/observable venue disclosed at booking time
   (field, gym, public court) — no private residences, no unsupervised
   transport by the coach. This is a policy/contract term enforced by
   acceptance checkbox + terms, not a technical control; document it in the
   booking contract, not assume the app can verify it.
2b. **No unsupervised one-to-one online coaching (video/voice) with a minor**
   without the guardian present or the session recorded, if the product ever
   adds live sessions — out of scope for v1 (no live calls), but note now so
   a future workstream doesn't quietly add 1:1 video without this control.
6. **Reporting and blocking.** Any user can report a coach or a message;
   report immediately suspends the coach's ability to book new sessions
   (not necessarily existing ones) pending admin review; guardian/player can
   block a coach unilaterally.
7. **Admin moderation.** Admin dashboard for verification queue, report
   queue, suspension/reinstatement actions; every moderation action is
   logged with actor, reason, timestamp (immutable, like `judgment_revision`
   pattern already used in the core product).
8. **No off-platform contact info exchange** and **no cash payment** — both
   are safeguarding controls as much as payment ones: off-platform payment
   removes the marketplace's ability to refund/dispute and often precedes
   off-platform (unsupervised) contact attempts.

## Booking + payment flow

- **Stripe Connect, Express accounts** for coaches (least platform dev
  burden, Stripe handles KYC/tax forms):
  https://stripe.com/connect/marketplaces, https://docs.stripe.com/connect.
- Coach onboards via Stripe-hosted onboarding; platform checks
  `charges_enabled`/`payouts_enabled` capability status before allowing the
  listing to go live — this check is in addition to, not instead of, the
  background-check gate in requirement 1.
- Player/guardian pays platform (destination charge or separate
  charges-and-transfers, decide at build time); platform holds funds until
  session completion (e.g., T+24h after scheduled end) then transfers coach's
  share minus platform fee — reduces immediate chargeback exposure and gives
  a window to act on a same-day safeguarding report.
- Refunds: guardian/player can request cancellation up to a configurable
  cutoff (e.g., 24h before) for full refund; late cancellation/no-show policy
  is a coach-set term shown at booking, capped by platform-wide limits so a
  coach can't impose predatory terms.
- Disputes: use Stripe's dispute/chargeback tooling; any dispute pauses that
  coach's future payouts for the disputed amount, not their whole balance.
- Platform fee: flat percentage, taken as `application_fee_amount` on the
  charge.

## Data model sketch (not frozen, illustrative only)

```
app.marketplace_coach
  id uuid pk, user_id uuid fk auth user (indexed, unique),
  stripe_account_id text, background_check_status text check in
    ('pending','clear','flagged','expired'),
  background_check_checked_at timestamptz,
  bio text, is_listed boolean default false,  -- false until check clears
  created_at, updated_at

app.marketplace_service
  id uuid pk, coach_id uuid fk marketplace_coach (indexed),
  title text, description text, duration_min integer, price_cents integer,
  location_type text check in ('public_venue','online'),  -- no 'coach_home'
  active boolean default true

app.marketplace_guardian_link
  id uuid pk, minor_user_id uuid fk (indexed, unique),
  guardian_user_id uuid fk (indexed), consented_at timestamptz not null

app.marketplace_booking
  id uuid pk, service_id uuid fk (indexed), buyer_user_id uuid fk (indexed),
  minor_user_id uuid null fk,  -- set when booking is for a minor
  guardian_user_id uuid null fk,  -- required if minor_user_id set
  scheduled_at timestamptz, status text check in
    ('pending_approval','confirmed','completed','cancelled','disputed'),
  stripe_payment_intent_id text, created_at

app.marketplace_message
  id uuid pk, booking_id uuid fk (indexed), sender_user_id uuid fk,
  body text, created_at
  -- RLS: readable by buyer, coach, and guardian_user_id if set on the booking;
  -- never readable by admin except via a separate audited investigation-access path

app.marketplace_report
  id uuid pk, booking_id uuid fk null, reported_user_id uuid fk,
  reporter_user_id uuid fk, reason text, status text check in
    ('open','investigating','closed'), created_at

app.marketplace_moderation_event
  id uuid pk, actor_user_id uuid fk (admin), target_user_id uuid fk,
  action text, reason text, created_at  -- immutable, append-only
```

RLS intent: every table above scoped by `auth.uid()` matching buyer, coach's
`user_id`, or linked guardian — same pattern as existing `app` tables. No
table exposed through Supabase Data API. `marketplace_message` is the
highest-risk table: policy must include guardian read access, and any admin
read path must go through a `private.` SECURITY DEFINER function gated on an
open `marketplace_report` row, logged in `marketplace_moderation_event`.

## Interaction with ADR 0021 / 0023

- **ADR 0021 (no AI authorship for player-facing text):** applies unchanged.
  A marketplace coach's messages/notes are human-authored; no LLM drafts or
  summarizes coach-to-player marketplace communication. If a future AI-coach
  feature ever touches marketplace data, it stays `ai_coach_feedback`-shaped
  (labelled, filtered, never a judgment) — not needed for v1 since there is
  no AI surface in this design.
- **ADR 0023 (leaderboard waiver is narrow):** the leaderboard exception is
  for GPS tracking totals only. This design must not add coach ratings,
  rankings, or "top coach" surfaces computed from minors' data — coach
  discovery uses static filters (sport, location, price, availability), not
  a score. Verified reviews, if added later, are a separate legal-reviewed
  decision (see below) and never a numeric ranking of coaches by minors.

## Rollout phases

1. **Legal/policy phase (no code).** Owner + legal review: safeguarding
   policy text, minor-consent flow, background-check vendor contract, Stripe
   Connect platform agreement/tax obligations, state-specific youth-sports
   coaching regulations, insurance/liability question (is Shoulder a
   marketplace facilitator or a coaching provider — changes liability).
2. **Coach onboarding + verification only.** Build background-check +
   Stripe Connect onboarding, no bookings yet. Admin verification queue.
3. **Booking + payment, adults only (18+ players).** No minors in this phase;
   proves payment/refund/dispute flow without safeguarding complexity.
4. **Minor bookings.** Guardian linking, guardian-copied messaging, session
   location rules, reporting/blocking, admin moderation — only after phase 3
   is stable and legal review of minor-specific terms is signed off.
5. **Optional: reviews/ratings of coaches** (adults' reviews of coaches, not
   using any minor performance data) — separate legal review before build.

## What legal review must approve before any build

- Safeguarding policy text and whether it satisfies applicable state/NGB
  requirements (this doc borrows from SafeSport MAAPP but Shoulder is not a
  SafeSport-covered NGB program — confirm what actually applies).
- Background-check vendor choice, data retention of check results, and
  adverse-action process if a check comes back flagged.
- Guardian-consent flow wording and whether e-signature/checkbox consent is
  sufficient for the target states.
- Insurance/liability position (marketplace facilitator vs. employer of
  coaches) and required disclaimers.
- Stripe Connect platform responsibilities (1099s, KYC failures, prohibited
  business types) under the actual entity's Stripe agreement.
- App-store age-verification obligations under new state "app store
  accountability" laws (TX, UT, LA effective around Jan 2026) if any minor
  booking flow ships in the mobile app —
  https://www.cslawreport.com/21263356/navigating-three-new-state-laws-that-require-apple-and-google-app-stores-to-check-all-users-ages.thtml.
- Message-retention window and who (if anyone outside admin-investigation)
  can be compelled to produce messages.
- Whether independent coaches are contractors and what tax/labor
  classification risk that creates.

## Explicit decisions the owner must make

1. Do we allow independent (non-team) coaches at all in v1, or only a team's
   own coaches selling extra 1:1 time to their own team's players?
2. What background-check vendor and cost-per-check, and who pays for it
   (coach or platform)?
3. Minimum coach age-gap-from-minor rule, if any, beyond the background check.
4. Platform fee percentage and refund/cancellation cutoff windows.
5. Do minors 13–17 get in-person sessions at all, or online-only (which
   raises its own supervision requirements) in early phases?
6. Message retention window (this doc proposes 365 days) and who can access
   it under what process.
7. Is Shoulder willing to carry the liability/insurance posture of a
   marketplace facilitator, or does this require a different corporate
   structure/insurance product first?
8. Do we ever want coach reviews/ratings, and if so, are they gated to
   adults' voluntary reviews only, never algorithmic ranking?

## Sources

- https://uscenterforsafesport.org/how-to-safely-communicate-with-minor-athletes/
- https://uscenterforsafesport.org/wp-content/uploads/2021/03/MAAPP_OnePagers_Communication.pdf
- https://maapp.uscenterforsafesport.org/how-it-works/
- https://stripe.com/connect/marketplaces
- https://docs.stripe.com/connect
- https://checkr.com/resources/articles/coach-background-checks
- https://www.ankored.com/blog/best-background-check-software-youth-sports
- https://www.cslawreport.com/21263356/navigating-three-new-state-laws-that-require-apple-and-google-app-stores-to-check-all-users-ages.thtml
