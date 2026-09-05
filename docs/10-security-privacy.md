# 10 — Security and privacy

## Security posture

Shoulder handles identifiable youth-sports footage, coach assessments, and player reflections. Treat it as sensitive data even though the MVP serves one team and is not a commercial product. Privacy controls are product behavior, not optional infrastructure polish.

This document is an engineering baseline, not a substitute for jurisdiction-specific legal advice. Before enrolling any player under 13, expanding beyond the initial team, or using footage for model training, complete a separate legal and consent review.

## Protected assets

- Original and transcoded match footage.
- Isolated player clips and thumbnail sprites.
- Player names, team membership, and jersey identifiers.
- Development goals, coach judgments, and player reflections.
- Authentication sessions, service credentials, signing keys, and presigned URLs.
- CV artifacts, tracklets, candidate observations, and research exports.
- Consent, deletion, access, and security-event records.

## Actors and trust boundaries

| Actor | Allowed | Explicitly not allowed |
|---|---|---|
| Player | Read their own published evidence and goals; manage their own reflection | Read drafts, other players, full matches, coach playback, CV artifacts, or operational logs |
| Coach | Manage the team, players, goals, match footage, and own authored judgments; read team players' reflections | Mutate reflection text, cross-team access, silent player impersonation, raw credentials, or unrestricted research exports |
| Worker | Read/write only media and job objects needed for a claimed task | Interactive user access or broad database administration |
| Operator | Maintain infrastructure and execute documented deletion/security procedures | Routine product browsing without an operational reason |
| External CV workspace | Read one scoped input and write one scoped artifact set during a manual run | Live product access, long-lived credentials, public ingress, or persistent biometrics |

## Primary threats and controls

### Cross-player and cross-team access

Threats include guessed UUIDs, insecure direct-object references, incorrect joins, missing filters, and a privileged database connection that bypasses policies.

Controls:

- Enable RLS on every protected table and force it where supported for the application role.
- Set verified `app.user_id` only with transaction-local scope.
- Use an API role with `NOBYPASSRLS`; do not use table-owner or service-role credentials for user requests.
- Keep product tables in the non-exposed `app` schema; do not add that schema to Supabase Data API settings for convenience.
- Keep any necessary `SECURITY DEFINER` helper in `private`, set an empty search path, qualify every object, revoke default `PUBLIC` execution, and grant only the required caller.
- Repeat resource authorization in the service before creating object URLs or jobs.
- Test player A against player B at both database and HTTP layers.
- Return the same not-found response for nonexistent and unauthorized objects where revealing existence would leak information.

Baseline policies and runtime-role tests ship with Task 4's schema, including role-aware `/v1/me`; Task 5 extends them. Task 3 identity alone grants no team access. Initial coach privileges use an operator-only bootstrap. Every later protected table, including revisions and operational deletion/replay records, follows the same policy-with-schema rule.

### Draft and revision disclosure

- Editable verdict, comment, and bounds live only in immutable `judgment_revision` snapshots. Players can read only the exact revision selected by a currently published judgment, never latest drafts or history.
- Require `If-Match` and original-author/team authorization for edits; atomically increment the judgment version and insert the snapshot. Do not duplicate draft content onto a player-readable judgment row or use an RLS-bypassing view for player projections.
- Publication pins revisions and clip versions. Replacement keeps the prior snapshot visible until a full atomic swap; failure cannot change it. Withdrawal cancels pending replacement and denies new reads/signing immediately. An edit alone, including draft rejection, never alters or withdraws already published evidence.
- Immutable history is not indefinite retention: verified erasure and season expiry delete revisions with their judgment. Ordinary roles cannot mutate history.

### Full-match disclosure to a player

Threats include signing the coach MP4 for a player, exposing an R2 key, using client-side clip boundaries as access control, or leaving a stale URL in logs/history.

Controls:

- Store coach playback and published evidence clips under separate object prefixes.
- The player endpoint accepts a judgment ID plus expected published revision. Its authorized resolver selects the current ready `evidence_clip.id` server-side; no client storage key or coach playback key is accepted.
- Sign one object, one verb, and a short lifetime; never sign a bucket or prefix.
- Player clip URLs last at most five minutes; coach playback URLs last at most fifteen minutes. Clip signing checks the client's expected published revision; a mismatch refreshes the whole evidence set. Previously issued URLs may remain usable until expiry/object deletion; do not promise instant revocation or retrieval of already downloaded copies.
- Do not put signed URLs in analytics, error reports, page source, database rows, or server logs.
- Set private cache behavior deliberately and test expiry, refresh, and copied URLs.

### Session theft and confused identity

- Complete Supabase PKCE on the server and keep refresh/session material in Secure, HttpOnly, SameSite=Lax cookies.
- Use the current framework-supported proxy/session-refresh convention and the SSR `getClaims()` path to verify identity. A `getSession()` result may provide the access token for forwarding, but its embedded user object is not an authorization source.
- Validate JWT signature, issuer, audience, algorithm, expiry, and subject independently in FastAPI.
- Use JWKS rotation-safe verification; never accept `none` or an unexpected algorithm.
- Authorize from database memberships, not editable user metadata.
- Rotate the session after sensitive account changes and invalidate sessions after access revocation.
- Apply CSRF protection to state-changing same-origin BFF routes through SameSite cookies plus origin/host validation and a CSRF token where required by the final framework design.

### Upload abuse and media parsing

- Allocate uploads only for authenticated coaches with a team membership.
- Enforce configured size, part count, filename length, and declared MIME type before creating an upload.
- Generate object keys server-side; never interpolate a client filename into a key or local path.
- Verify completed size and content signature with `ffprobe`; extension and browser MIME are hints only.
- Run ffmpeg in a non-root, resource-limited worker container with no inbound network, read-only base filesystem, bounded CPU/memory/time, and a task-scoped working directory.
- Never pass untrusted values through a shell. Use argument arrays and fixed encoding profiles.
- Abort abandoned multipart uploads on a schedule.

### Job and replay abuse

- Use a unique request idempotency key for each explicit review publication and deterministic keys for its clip exports and transcodes.
- Lock and heartbeat jobs; retry only bounded transient failures.
- Validate that the resource still exists and the actor is still authorized before a delayed publish/export action changes visibility; publish the requested clip set atomically only after every current export is ready.
- Record who requested a publish, retry, cancellation, or deletion.
- Do not let a user-provided job payload select an arbitrary R2 key, command, local path, or callback URL.

### Client and supply-chain compromise

- Use a strict Content Security Policy and avoid inline scripts except framework-generated nonces/hashes.
- No third-party analytics, replay recording, chat widgets, ad pixels, or CDN-hosted fonts in the player product.
- Pin lockfiles and container image digests; review dependency additions.
- Enable automated dependency and secret scanning in CI.
- Generate API types from the pinned OpenAPI artifact; do not trust arbitrary response shapes.
- Sanitize or render coach/player text as text, never HTML.

## Credentials and keys

| Credential | Location | Scope |
|---|---|---|
| Supabase publishable key | Browser/server config | Public project identifier and allowed client operations |
| Supabase secret/service key | Server/ops only | Never used in a user-request query path |
| Postgres API role | FastAPI secret store | `NOBYPASSRLS`, least table/function privileges |
| Postgres migration role | CI/ops secret store | Schema migration only; never in runtime |
| R2 signing credentials | FastAPI/worker secret store | Required buckets/actions only |
| Resend key | Server secret store | Approved sender and email action only |
| RunPod/transfer credential | Operator's ephemeral environment | One run/prefix and short lifetime |

Use current Supabase publishable/secret keys for new work rather than designing around legacy `anon`/`service_role` keys. Separate development, preview, and production projects. Never commit `.env` files, copy secrets into prompts, or expose a server secret through a `NEXT_PUBLIC_` variable.

## Data minimization

- Collect only player name and optional jersey number needed for team use.
- Do not collect birth date, home address, school, precise location, health data, phone contacts, or social profiles in the MVP.
- Audio is preserved only when the team has a reason and consent; otherwise the transcode profile may remove it.
- Do not create face recognition, appearance embeddings, biometric templates, or cross-match identity models.
- Do not train or fine-tune on team footage by default.
- Product analytics use coarse product events with pseudonymous internal IDs and no note/reflection text, URLs, filenames, or media metadata.

## Retention and deletion

Engineering defaults for the initial one-season team workspace follow [ADR 0009](decisions/0009-retention-and-shared-footage-deletion.md). They are conservative operating rules, not a determination of legal compliance. The owner must confirm the notice, season date, collateral-deletion scope, responsible operator, and actual provider backup expiry before real data is onboarded.

| Data | Default retention |
|---|---|
| Incomplete/abandoned multipart upload | Abort and delete within 7 days of initiation, even after resumes |
| Invalid/rejected media | Remove access immediately; delete within 24 hours of rejection |
| Completed upload not successfully processed | Delete by the earlier of first terminal processing failure +7 days or upload completion +14 days; stuck jobs are included |
| Successfully processed original | Delete no later than upload completion +90 days, or earlier season expiry/erasure |
| Coach playback, thumbnails, current player clips | `team.season_end_at + 365 days`, or earlier erasure |
| Goals, observations, judgments and all revisions, publications, reflections | Same season expiry, including drafts and rejected items, or earlier erasure |
| Superseded/withdrawn clip objects | Delete within 24 hours after losing all current references |
| Failed/cancelled unpublished clip exports | Delete within 7 days of first terminal publication failure/cancellation; retries do not extend this deadline |
| Task-local media/scratch files | Delete at task end; crash sweeper removes within 24 hours |
| Operational logs | 30 days, redacted |
| Product events | 180 days; erase/anonymize earlier where required by player erasure |
| Security audit events | 365 days, content-free and restricted |
| Reflection request replay metadata | 7 days, content-free; expired/stale save requests are rejected, never reapplied |
| Deletion manifests and restore-suppression IDs | Through verified active deletion and backup expiry; remove within 30 days after both complete; no text/media retained |
| Provider backups containing personal data | Maximum 30 days, verified with providers before real use; restore must reapply deletion records before access |
| CV artifacts | Per-run research decision; no indefinite default |

Successful processing before the failure/stuck deadline moves the source to successful-source retention; it never extends the absolute upload-completion +90-day cap. The earliest applicable season, failure, erasure, or source deadline wins. Persist first failure/completion times server-side; retries cannot reset clocks. A terminal clip-export failure never shortens a still-current predecessor clip's lifetime. Unreferenced successful exports left by a crash are swept using the pending job/publication deadline. Missing cleanup execution blocks access at expiry, triggers an alert, and remains an unresolved deletion failure until absence is verified.

`team.season_end_at` is a required, owner-confirmed timestamp, not a label parsed into a date. Its cutoff cannot be extended once product data exists; shortening requires an operator impact review. Renewal into another season is outside this initial workspace's MVP. Do not retain content indefinitely because a season date or retention owner is missing.

### Reflection deletion

Only the author may create, edit, or permanently delete a reflection. Coaches read only. Updates retain no previous text; events, emails, replay metadata, and jobs never contain reflection text. Existing own reflections remain manageable after evidence withdrawal while account access is valid. Delete the active row and cached/queued copies, clear local unsent text on delete/sign-out, and serialize save/delete to stop stale retries from restoring it. A deliberate new create requires a new request key and current published evidence. If account access is revoked, the operator request route handles erasure.

Backups may retain deleted text until their verified maximum 30-day expiry. Store only enough restricted content-free deletion metadata to suppress restoration; reapply deletions before restoring product access. Do not describe deletion as instant destruction of all external copies.

### Player erasure and shared footage

Roster archive removes access; it is not erasure. A verified personal-data erasure request uses this auditable procedure:

1. Mark the player deletion-pending, remove membership/access, and fence new signing, uploads, exports, and publications for the affected team videos. Keep failures inaccessible.
2. Build a restricted, durable impact manifest of all stored videos for the player's team, every original/playback/thumbnail/CV derivative, and every dependent clip, observation, judgment/revision, publication item, and reflection. Include clips intentionally published to other players: absence of a player link does not prove the requesting player is absent from the image or audio.
3. The operator verifies request scope and confirms the concrete collateral-deletion impact through the deletion challenge. The pre-onboarding owner-approved policy permits this conservative full-media removal; selective anonymization and face detection are not MVP alternatives. Do not indefinitely delay a valid request while silently retaining access.
4. Cancel/drain affected jobs under database locks, reject late finalization, delete objects idempotently, verify absence, and delete dependent rows in FK-safe order. A final sweep removes any object written by an in-flight worker. Delete the requesting player's goals/profile/reflections and auth account when it has no remaining legitimate association. Remove empty publications and all affected video-dependent product rows, including other players' affected evidence. Clear caches; do not silently recreate them.
5. Other players' unrelated accounts/goals may remain only after operator review confirms they do not retain the requesting player's personal data. Review free text and external research copies explicitly; uncertainty remains an open deletion item, not a completion claim.
6. Record content-free completion/failure metadata, verify backup expiry, and replay deletions before any restore becomes accessible. Manifests outlive deleted job target rows and remain RLS-protected/operator-only; object keys never enter logs or ordinary responses.

This policy can remove another player's useful evidence and must be explained before real use. The owner must confirm the policy and identify the responsible operator. It is not a legal guarantee: obligations and exceptions require the responsible owner/legal reviewer. If a provider cannot meet the 30-day backup bound, block real-data onboarding and document an approved policy change before proceeding. Copies downloaded outside Shoulder cannot be recalled by the service.

## Consent and user control

- Record the team's lawful/consent basis and the version of the notice accepted outside player-facing coaching content.
- Explain what is uploaded, who can see it, how long it remains, and how to request correction or deletion in plain language.
- A player sees only current published snapshots and may create, edit, or permanently delete their own reflection under the active-storage/backup rules above.
- Coaches can unpublish evidence; this revokes new access and schedules obsolete clip objects for deletion.
- Do not enroll under-13 users until the separate age/guardian workflow is approved.

## Logging and monitoring

Log structured operational facts: request ID, route template, status, duration, authenticated internal user ID, resource type/ID when safe, job ID, and error code.

Never log:

- access or refresh tokens;
- magic-link query strings;
- cookie values;
- presigned URLs or R2 credentials;
- raw coach notes or player reflections;
- filenames supplied by users;
- video frames, thumbnails, or CV samples.

Alert on repeated authorization denials, unusual signing volume, RLS or database permission errors, stalled jobs, deletion failures, and unexpected egress. Monitoring must not become surveillance of players.

## Incident procedure

1. Contain: disable affected signing/route credentials and stop the leaking path.
2. Preserve minimal security evidence without copying exposed content unnecessarily.
3. Determine affected accounts, objects, time range, and whether a minor's data was exposed.
4. Rotate credentials and revoke sessions as applicable.
5. Remove exposed objects/links and verify policy fixes with isolation tests.
6. Follow applicable notification obligations with a responsible adult/legal reviewer.
7. Record cause, timeline, impact, fixes, and prevention in a private incident report.

Do not silently repair a suspected cross-player leak and continue.

## Security release gate

- RLS and `FORCE ROW LEVEL SECURITY` posture are verified in the deployed schema.
- Runtime roles and grants are exported and reviewed.
- Cross-player/cross-team tests fail closed.
- Player clip signing cannot accept or derive a coach playback key.
- Session, CSRF, logout, revoked-membership, and expired-token tests pass.
- Upload limits, content validation, ffmpeg sandboxing, and abandoned-upload cleanup pass.
- CSP, security headers, CORS, and cookie attributes are inspected in a production-like deployment.
- Logs and error reports contain none of the prohibited fields.
- Data deletion completes across database, R2, jobs, and CV artifacts.
- A responsible adult/operator knows the incident and deletion procedures before real minors' data is added.
