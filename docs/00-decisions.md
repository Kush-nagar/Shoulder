# 00 — Resolved decisions

This file records the decisions that reconcile the uploaded plans. It outranks the other numbered documents when wording differs.

## D1 — One canonical instruction file

`AGENTS.md` is the canonical repository contract because Codex reads it directly. Claude Code does not automatically read `AGENTS.md`; `CLAUDE.md` imports it with `@AGENTS.md` and contains only Claude-specific workflow notes. Do not duplicate the full rule set.

## D2 — Private project, production-quality privacy

Shoulder is a personal project intended for one real team, not a commercial launch. That removes billing, organizations, growth features, and broad multi-tenant scope. It does not weaken privacy: real minors and real team footage still require least-privilege access, consent, deletion, and isolation tests.

## D3 — Progressive MP4 before HLS

The MVP worker creates one 720p H.264/AAC MP4 with fast-start metadata and frequent keyframes. The browser uses byte-range requests to seek. HLS is deferred because a private HLS package contains many objects and a single presigned manifest URL does not authorize its referenced playlists and segments. Add adaptive streaming only if measured playback fails the targets.

## D4 — Player evidence is a separate object

The earlier “clips are not files” approach is rejected. Giving a player a signed URL to a full-match object, then relying on the UI to stop playback at clip boundaries, is not access control. Publishing creates one `evidence_clip` object per judgment. Players receive only that object-specific signed URL.

## D5 — Uploads resume; they do not continue after tab close

Browser requests stop when the tab closes. The UI must not say “You can close this tab” while bytes are still uploading. Multipart state is persisted so the user can reopen the page, reselect the same file if necessary, and upload only missing parts. “Safe to close” appears only after R2 confirms completion.

## D6 — Next.js owns browser sessions

Next.js uses Supabase's server-side auth flow and secure cookies. Browser JSON requests are same-origin. A small BFF layer obtains and validates the session, forwards the access token to FastAPI, and never exposes a secret key to the browser. FastAPI independently validates the JWT before opening a database transaction.

## D7 — Supabase identity is the application identity

`user_account.id` equals the UUID in `auth.users.id`; it is not a separately generated identifier. FastAPI sets the verified UUID in a transaction-local Postgres setting. The API database role must not have `BYPASSRLS`.

## D8 — Manual product before computer vision

The manual review loop must work across three real games before any ML or CV integration begins. CV is an offline file-producing batch, never part of an HTTP request and never required for the product to function.

## D9 — No parent dashboard

There is no parent product role or parent-facing critique feed. This does not remove required operational handling of consent, access, export, and deletion requests. No participant under 13 is onboarded without a separate legal and consent review.

## D10 — One team first

The schema retains `team_id` because authorization needs it, but the product is designed and tested for one team. No organization, subscription, billing, invitation marketplace, or multi-club administration ships in the MVP.

## D11 — The logo is a fixed asset

The supplied wordmark uses a custom squared logotype while the interface uses Inter Tight. The wordmark must be exported as vector artwork; do not try to reproduce it by applying the UI font to the word “shoulder.”

## D12 — External SoccerMaster code stays external

The public SoccerMaster repository had no license file when rechecked on 2026-08-24. It may be studied and run only in a separate private research workspace. Do not vendor it, its weights, or its datasets into the Shoulder repository. Recheck terms before Phase D and before any public demonstration.

## D13 — Application data stays outside the exposed Data API schema

Shoulder does not use Supabase's browser Data API for product data. Application tables live in an `app` schema that is not listed in the project's exposed schemas. RLS still applies as defense in depth. Authentication/profile synchronization and policy helpers live in a `private` schema with explicit grants, safe search paths, and no default `PUBLIC` execution.

## D14 — Publication is an explicit database entity

Publishing three to six judgments is represented by `review_publication` and `review_publication_item` rows. The requested set, order, idempotency key, clip versions, failures, and final visibility therefore survive worker restarts. The set becomes player-visible only in one transaction after every item points to a ready isolated clip.

## Reconciliation decisions

The following reconciliation decisions supplement D1–D14 and govern the detailed contracts:

- **D15 — Identity before roles, protection with schema.** Task 3 proves verified session identity only. Task 4 completes role-aware `/v1/me`, memberships, baseline RLS, and runtime-role isolation tests for every table it creates. Task 5 extends that harness. See [ADR 0006](decisions/0006-foundation-auth-and-rls-sequence.md).
- **D16 — Author-controlled reflections.** Reflections are mutable by their player author and permanently deletable from active storage, with no retained text history. Backup expiry and restore suppression are explicit operational limits. See [ADR 0007](decisions/0007-author-controlled-reflections.md).
- **D17 — Versioned human judgments.** Creation and every content edit create immutable snapshots; edits require optimistic concurrency. Publication pins exact revisions and isolated clips. Replacement keeps the old published set visible until an atomic swap; withdrawal is immediate for new requests. See [ADR 0008](decisions/0008-judgment-revisions-and-republication.md), which extends ADR 0005.
- **D18 — Bounded retention and conservative shared-footage deletion.** Source retention starts at upload completion and never extends on retries. Failed work has earlier deadlines; season expiry has an explicit timestamp. A verified player-erasure request removes shared team footage and its dependent evidence rather than claiming selective anonymization. Operational ownership, collateral deletion, and backup limits need owner confirmation before real data. See [ADR 0009](decisions/0009-retention-and-shared-footage-deletion.md).
- **D19 — Review shell and asset gate.** Review has no global navigation rail; three visible accessible verdict choices include coach-only `not_relevant`. The owner-approved Task 1 mark and wordmark satisfy the health shell asset gate; additional variants are required before their placements ship. Task 1 local acceptance and deferred deployment follow [ADR 0012](decisions/0012-task-1-local-acceptance.md). Inter Tight may be added during Task 1 through `@fontsource-variable/inter-tight`. Self-host its WOFF2 assets covering weights 400/500/600 through `next/font/local`, preserve its included SIL Open Font License with the assets and in distributions, and make no runtime request to Google Fonts. Pin an exact package version in the dependency manifest and project lockfile. After installation, document the exact resolved version, package provenance, asset paths, and retained license location in `assets/README.md`; record the resolved version and completion in `STATUS.md`. Font receipt is not a pre-start prerequisite; the approved family and visual specification are unchanged. See [ADR 0010](decisions/0010-review-workspace-and-asset-prerequisites.md).
- **D20 — Phase D provenance deletion.** A CV observation referenced by a judgment is retained as a minimal observation with machine provenance cleared. Only unreferenced CV observations can be deleted during run cleanup. The non-null judgment relationship stays intact. See [ADR 0011](decisions/0011-cv-provenance-deletion.md).

## Open decisions that require measurements

| Decision | Test | Owner task |
|---|---|---|
| Is 720p progressive playback fast enough? | Measure startup and random seek on a full 90-minute fixture | Task 11 |
| Is 32 MiB the right upload part size? | Test 1–3 GB uploads on normal home Wi-Fi and one interrupted network | Task 8 |
| Is a coach able to review one player in three minutes? | Time the manual workflow across two games | MVP gate |
| Does SoccerMaster help on this footage? | Measure recall, tracklet purity, keep rate, and review time | Tasks 25–30 |

If a test fails, write an ADR before changing the related decision.
