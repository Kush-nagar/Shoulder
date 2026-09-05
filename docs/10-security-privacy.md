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
| Coach | Manage the team, players, goals, match footage, draft/published judgments, and reflections for their team | Cross-team access, silent player impersonation, raw credentials, or unrestricted research exports |
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

### Full-match disclosure to a player

Threats include signing the coach MP4 for a player, exposing an R2 key, using client-side clip boundaries as access control, or leaving a stale URL in logs/history.

Controls:

- Store coach playback and published evidence clips under separate object prefixes.
- Player signing code accepts an `evidence_clip.id`, resolves the current ready clip object server-side, and has no code path for a video playback key.
- Sign one object, one verb, and a short lifetime; never sign a bucket or prefix.
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

Default proposal for the initial team:

| Data | Default retention |
|---|---|
| Original upload | 90 days after successful processing |
| Coach playback and thumbnails | Season end plus 1 year |
| Published player clips | Season end plus 1 year |
| Goals, judgments, reflections | Season end plus 1 year unless earlier request |
| Failed/abandoned upload parts | Abort/delete within 7 days |
| Operational logs | 30 days, redacted |
| Security audit events | 1 year |
| CV artifacts | Per-run research decision; no indefinite default |

Deletion is an auditable job:

1. Mark the resource `deletion_pending` and remove normal access.
2. Enumerate original, playback, thumbnail, clip, and CV object keys server-side.
3. Delete objects idempotently and verify absence.
4. Delete or tombstone database records according to required audit retention.
5. Clear cached derivatives and revoke outstanding access where possible; short URL expiry limits residual access.
6. Record completion time, actor/request source, and failed items without recording sensitive content.

Account or player deletion must not silently leave orphaned media. Backups need a documented expiry; deleted data may persist only until that bounded backup cycle completes.

## Consent and user control

- Record the team's lawful/consent basis and the version of the notice accepted outside player-facing coaching content.
- Explain what is uploaded, who can see it, how long it remains, and how to request correction or deletion in plain language.
- A player can see only evidence intentionally published to them and can remove their own reflection.
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
