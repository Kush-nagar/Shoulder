# Block 10M — Coach marketplace phases 2–3 (adults only, test mode)

Design: [coach-marketplace.md](../design/coach-marketplace.md). Owner decisions
(2026-09-24): independent coaches allowed; build phases 2–3 only (coach
onboarding + verification, then booking and payment for **adult players only**);
background checks verified by an admin from an uploaded certificate (Checkr
later, same flow); platform fee **10 %**, full refund when the player cancels
**> 24 h** before the session or whenever the coach cancels.

**Not for real use yet.** Every marketplace endpoint and page is behind
`MARKETPLACE_ENABLED` (API) / `NEXT_PUBLIC_MARKETPLACE_ENABLED` (web), default
off. Stripe runs in **test mode** only. Legal review (design doc §"What legal
review must approve") must sign off before either flag is turned on for real
users. Minor bookings (phase 4) are out of scope: an account without an adult
age attestation cannot browse, view or book coaches.

Branch: `coach-marketplace` from `main`. Migration: `0020_coach_marketplace`
(`down_revision = "0019_team_leaderboard"`).

## Frozen schema — 0020_coach_marketplace

```
app.platform_admin            user_id uuid pk fk app.user_account on delete cascade, granted_at, granted_by uuid null
app.age_attestation           user_id uuid pk fk app.user_account on delete cascade,
                              birth_year integer check (birth_year between 1900 and extract(year from now())::int),
                              attested_at timestamptz default now()
app.coach_profile             id uuid pk, user_id uuid unique fk app.user_account on delete cascade,
                              display_name text check 2..60, bio text check ≤ 600,
                              specialties text[] check (cardinality between 1 and 5 and all from
                                ('scanning','first_touch','passing','finishing','dribbling','defending',
                                 'goalkeeping','fitness','tactics')),
                              city text check 2..80, formats text[] check (subset of ('in_person','online'), non-empty),
                              rate_cents integer check (rate_cents between 1000 and 50000),   -- per hour, USD
                              status text check in ('draft','pending_review','verified','suspended','rejected') default 'draft',
                              review_note text null check ≤ 500, verified_at, verified_by uuid null,
                              stripe_account_id text null, charges_enabled boolean default false,
                              created_at, updated_at
app.coach_document            id uuid pk, coach_profile_id fk (indexed) on delete cascade,
                              kind text check in ('background_check','id','certification'),
                              object_key text unique, content_type text check in ('application/pdf','image/jpeg','image/png'),
                              size_bytes integer check (1..10485760), uploaded_at, status text check in ('uploading','ready')
app.coach_slot                id uuid pk, coach_profile_id fk (indexed), starts_at timestamptz, ends_at timestamptz,
                              check (ends_at > starts_at and ends_at - starts_at between '30 min' and '3 hours'),
                              format text check in ('in_person','online'),
                              venue text null check ≤ 120,   -- required for in_person: public venue name only
                              status text check in ('open','held','booked','cancelled') default 'open', created_at
app.coach_booking             id uuid pk, slot_id uuid unique fk app.coach_slot, coach_profile_id fk (indexed),
                              player_user_id uuid fk app.user_account (indexed),
                              status text check in ('pending_payment','confirmed','cancelled_by_player',
                                'cancelled_by_coach','expired','completed') default 'pending_payment',
                              price_cents integer, platform_fee_cents integer,   -- fee = round(price * 0.10)
                              refund_cents integer default 0, note text null check ≤ 280,
                              stripe_checkout_session_id text unique null, stripe_payment_intent_id text null,
                              hold_expires_at timestamptz, created_at, updated_at, cancelled_at null
app.marketplace_report        id uuid pk, reporter_user_id fk, coach_profile_id fk (indexed), booking_id null fk,
                              reason text check 10..1000, status text check in ('open','resolved') default 'open', created_at
app.marketplace_audit         id bigserial pk, actor_user_id uuid null, action text not null, subject_type text,
                              subject_id uuid, detail jsonb, created_at    -- append-only: no UPDATE/DELETE grants
```

RLS (all tables forced): coach reads/writes own profile, documents, slots; admin
(`private.is_platform_admin()`) reads all profiles/documents/reports/audit and
updates profile status; adults (`private.is_adult()`: attestation with
`birth_year <= current_year - 18`) read **verified, not suspended** profiles and
their `open` future slots through a SECURITY DEFINER view-function
`private.marketplace_coaches(p_specialty text, p_city text)` returning public
columns only (never user_id, email, stripe ids, review_note); player reads own
bookings; coach reads bookings on own profile (player shown as first name from
`user_account.display_name` only). An open report on a coach blocks new
bookings (checked inside the booking function). Every status change writes
`marketplace_audit` via a definer helper.

Slot holding: booking creates `pending_payment`, sets slot `held`, and
`hold_expires_at = now() + 15 min`; the retention sweep (or a check on read)
expires stale holds back to `open`.

## Frozen API (all 404 when `MARKETPLACE_ENABLED` is not `on`)

| Method | Path | Who | Notes |
|---|---|---|---|
| PUT | `/v1/me/age-attestation` | any signed-in | `{birth_year}`; once set, lowering the age is refused |
| GET | `/v1/me/age-attestation` | any | `{birth_year, adult}` or 404 |
| GET/PUT | `/v1/coach-profile` | coach self | create/update draft; verified profiles return to `pending_review` only when rate/specialties/bio change |
| POST | `/v1/coach-profile/documents` | coach | `{kind, content_type, size_bytes}` → presigned PUT (size + type signed) |
| POST | `/v1/coach-profile/documents/{id}/complete` | coach | HEAD-verify |
| POST | `/v1/coach-profile/submit` | coach | draft → pending_review; needs ≥1 ready `background_check` doc |
| POST | `/v1/coach-profile/stripe/onboarding` | coach (verified) | Stripe Connect Express account + account link URL |
| GET/POST | `/v1/coach-profile/slots` | coach (verified, charges_enabled) | future slots only |
| DELETE | `/v1/coach-profile/slots/{id}` | coach | open → cancelled; booked → cancels booking with full refund |
| GET | `/v1/coach-profile/bookings` | coach | own |
| GET | `/v1/admin/coach-reviews?status=` | admin | queue |
| GET | `/v1/admin/coach-reviews/{id}` | admin | profile + 60 s signed doc URLs |
| POST | `/v1/admin/coach-reviews/{id}/decision` | admin | `{decision: approve|reject|suspend|reinstate, note}` |
| GET | `/v1/admin/reports` / POST `/v1/admin/reports/{id}/resolve` | admin | |
| GET | `/v1/marketplace/coaches?specialty=&city=` | adult | public columns |
| GET | `/v1/marketplace/coaches/{id}` | adult | + open future slots |
| POST | `/v1/marketplace/bookings` | adult | `{slot_id, note}` → `{booking_id, checkout_url}` (Stripe Checkout, destination charge with `application_fee_amount`) |
| GET | `/v1/me/bookings` | adult | own |
| POST | `/v1/me/bookings/{id}/cancel` | player | refund per 24 h rule |
| POST | `/v1/marketplace/reports` | adult | `{coach_profile_id, booking_id?, reason}` |
| POST | `/v1/stripe/webhook` | Stripe | signature-verified; `checkout.session.completed` → confirmed; `checkout.session.expired` → expired; `account.updated` → charges_enabled |

Stripe: new production dependency `stripe` (official SDK; webhook signature
verification and Connect are not safe to hand-roll). Env: `STRIPE_SECRET_KEY`
(must start `sk_test_` while in test mode — refuse `sk_live_` unless
`MARKETPLACE_LIVE=on`), `STRIPE_WEBHOOK_SECRET`, `APP_ORIGIN`. All Stripe calls go
through `services/api/payments.py` so tests mock one module.

Admins: `scripts/grant_admin.py --email ...` (operator DB URL) inserts
`platform_admin`. No self-service admin.

## Web (all hidden when `NEXT_PUBLIC_MARKETPLACE_ENABLED` is not `on`)

- `/coaching` — adult gate (birth-year form, explains 18+ pilot), browse coaches
  (specialty/city filters), coach detail with open slots, book → Stripe Checkout,
  `/coaching/bookings` (list, cancel with refund preview, report).
- `/coaching/coach` — coach onboarding wizard: profile → background-check upload →
  submit for review → Stripe onboarding → slots → bookings.
- `/admin/coaches` — review queue, document viewer (signed URLs), decisions with
  note, reports list. Only for platform admins.
- Player app: Profile gets "Train with a coach (18+ pilot)" entry when enabled.
- Coach profile public page shows: name, bio, specialties, city, formats, rate,
  "Background check verified" once verified. No ratings (design decision 8 open).

## Workstreams

| ID | Area | Notes |
|---|---|---|
| M1 backend | migration 0020, `services/api/marketplace_*.py`, `payments.py`, webhook, tests, `scripts/grant_admin.py` | mocks Stripe in tests |
| M2 web | `apps/web/app/coaching/**`, `apps/web/app/admin/**`, BFF under `apps/web/app/api/coaching/**` and `api/admin/**` | writes against this contract with a TEMP types file |
| F fixes | player-mobile "earlier version", Windows agentops test, bootstrap tests with pre-existing data | test/infra only |

Agents must not run `check-db.ps1` or migrate/truncate the shared DB; the
coordinator runs DB and browser suites serially after integration, then an
independent security review, then deploy with both flags **off** in production.
