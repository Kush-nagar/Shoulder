# Block 07 verification — retention, deletion, and product events

Task 22 is implemented on `block-07-t22-retention-deletion-and-first-party-produ`.

## Evidence

- Migration `0013_retention_deletion` adds immutable retention confirmation,
  restricted content-free deletion manifests, product events, worker fencing,
  restore replay, RLS, least-privilege grants, and reversible migration steps.
- Deadline coverage includes abandoned uploads, rejected media, unprocessed or
  failed uploads, the 90-day source cap, season cutoff, obsolete clips, private
  exports, product events, replay metadata, scratch files, manifests, and
  provider backups.
- Shared-footage erasure tests cover two players, two published sets, both
  reflections, an in-flight replacement export, late worker completion,
  second-sweep deletion, FK-safe cleanup, account rules, unrelated goals and
  accounts, idempotency, and backup confirmation.
- Restore tests prove replay blocks access and suppresses restored reflection
  text. Manifest, event, job, and log paths accept only fixed codes and IDs or
  exact object keys; they contain no text, filenames, URLs, tokens, or media
  metadata.
- Coach UI records owner retention prerequisites, shows verified erasure impact,
  requires an exact deletion challenge, starts deletion through the real API,
  reports unresolved work honestly, and records actual backup expiry only after
  its confirmed deadline.
- `scripts/sql/review-duration.sql` and `scripts/sql/player-open-rate.sql` expose
  aggregate Phase C gate queries without player scores or comparisons.

## Commands

- `./scripts/check-db.ps1` — passed: 1,478 tests against local
  Supabase/Postgres/MinIO; 18 documented ffmpeg/ffprobe availability skips;
  empty upgrade plus downgrade/clean re-upgrade passed.
- `./scripts/check.ps1` — passed: Biome, TypeScript, 53 Node tests, Ruff, mypy,
  1,478 Python tests with 385 environment-gated skips, generated-contract drift,
  production build, browser-secret scan, and Chromium/Firefox/WebKit smoke.
- `git diff --check` — passed; only existing line-ending warning for
  `services/worker/.env.example`.

## Human gates and remaining operations

- No season, notice, collateral-deletion, operator, or provider-backup fact was
  inferred. Real product writes fail closed until the team owner records all
  five confirmations through the retention setup.
- Revision `0013_retention_deletion` has not been applied to a shared or
  production project in this task. Deploy with disposable fixtures first.
- Task 23 remains blocked until every mandatory real-use condition is recorded.
