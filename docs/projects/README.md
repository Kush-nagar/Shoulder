# Remaining project-block roadmap

From Task 6 onward, `docs/06-tasks.md` stays the authoritative task list, but delivery is
grouped into project blocks. One block is one branch, one integration, one verification
record, and one external review. Tasks 1–5 are merged and keep their
`docs/task-<n>-verification.md` records.

Dependency source: the `Prerequisites` line of each task in `docs/06-tasks.md`.

| Block | Tasks | Name | Depends on |
|---|---|---|---|
| 01 | 6, 7 | Roster and development goals | Tasks 1–5 |
| 02 | 8, 9, 10 | Video ingest and durable work | 01 |
| 03 | 11, 12, 13 | Media processing and coach playback | 02 |
| 04 | 14, 15, 16 | Coach marking and judgments | 01, 03 |
| 05 | 17 | Player evidence export and publication | 02, 04 |
| 06 | 18, 19, 20, 21 | Player experience and delivery | 05 |
| 07 | 22 | Retention, deletion, and product events | 05, 06 |
| — | — | **Mandatory real-use gate** (`docs/06-tasks.md`) | 07 |
| 08 | 23, 24, 25, 26, 27 | Offline CV feasibility | gate |
| 09 | 28, 29, 30 | Evidence retrieval | 08 |
| 10 | 31 | Candidate ranking, only if data justifies it | 09 |

Blocks 08–10 are Phase D–F. They are listed for sequencing only and are not planned in
detail: nothing about them may be started before the real-use gate passes, and rule 5 in
`AGENTS.md` forbids any inference call before that gate.

---

## Block 01 — Roster and development goals

- **Tasks:** 6, 7
- **Goal:** a coach builds a real roster without collecting player emails and gives one
  player an active development goal.
- **Dependencies:** Task 5 isolation harness, Task 4 identity schema and roles.
- **Deliverables:** roster write policies and grants, `development_goal` table with RLS,
  team/roster/goal API, bulk preview and commit, invitation transaction, archive,
  `/coach/roster` and `/coach/players/[player_id]`.
- **Security/privacy:** high. First product write path; first player-visible product
  table; invitation links an account to a minor's roster row.
- **Remote:** yes. Migration must reach `Shoulder Dev`.
- **Parallel:** yes — database, backend, frontend, tests.
- **Done:** 20 players added in under five minutes with no player email; one active goal
  per player enforced; player reads only their own goal; coach outside the team denied.
- **Spec:** `project-01-roster-goals.md`

## Block 02 — Video ingest and durable work

- **Tasks:** 8, 9, 10
- **Goal:** a full match file reaches private storage and a durable job exists to process it.
- **Dependencies:** Block 01 (Task 9 requires Task 6).
- **Deliverables:** `game`, `video`, `video_upload_part` schema with RLS; private R2
  configuration and CORS; multipart start/sign/list/complete/abort; object-specific
  signed GET; `/coach/upload` resumable UI; `processing_job` queue with leases,
  heartbeat, backoff, cancellation, and stuck-job recovery.
- **Security/privacy:** high. Private buckets, short-lived object-specific signing,
  raw-video retention clock starts at upload completion.
- **Remote:** yes.
- **Parallel:** yes — storage/API lane, queue lane, and upload UI lane are independent
  once the multipart contract is frozen.
- **Done:** interrupted uploads resume without repeating completed parts; video bytes
  never pass through FastAPI; two workers claim 100 jobs with no double execution.

## Block 03 — Media processing and coach playback

- **Tasks:** 11, 12, 13
- **Goal:** a coach watches and scrubs an uploaded match.
- **Dependencies:** Block 02.
- **Deliverables:** safe probe and 720p fast-start H.264/AAC transcode with bounded
  resources; timeline sprite sheets and timestamp index; coach player wrapper, signed-URL
  refresh preserving time, transport controls, scrubber, marker layer.
- **Security/privacy:** medium. Coach-only playback object; fifteen-minute signing ceiling.
- **Remote:** yes, for worker execution.
- **Parallel:** yes — transcode, sprites, and player UI after the media metadata contract
  is frozen.
- **Done:** a full-length fixture starts and seeks inside the named budgets; no HLS.

## Block 04 — Coach marking and judgments

- **Tasks:** 14, 15, 16
- **Goal:** a coach marks clips and writes durable judgments that survive reload and
  network failure.
- **Dependencies:** Blocks 01 and 03.
- **Deliverables:** `observation` schema and API with the full keyboard I/O flow;
  `judgment` and immutable `judgment_revision` with RLS, versioning, mandatory
  `If-Match`, transactional revision append, coach-only history, session-derived author;
  local draft persistence and conflict recovery.
- **Security/privacy:** high. Rule 1 (human author) is enforced here; no published state
  exists yet, so no player-visible surface is created.
- **Remote:** yes.
- **Parallel:** partly — schema, API, and UI lanes; Task 16 integrates last because it
  depends on the finished write path.
- **Done:** load-bearing test 2 (five marked draft clips survive reload and network
  failure) runs in CI; applied, opportunity, and rejected drafts persist correctly.

## Block 05 — Player evidence export and publication

- **Tasks:** 17
- **Goal:** a coach publishes 3–6 revision-pinned clips to exactly one player.
- **Dependencies:** Blocks 02 and 04.
- **Deliverables:** `review_publication`, `review_publication_item`, `evidence_clip`,
  current publication/revision/clip pointers, exact-boundary export worker, atomic
  snapshot swap, full-set replacement, withdrawal, fencing, obsolete-object cleanup.
- **Security/privacy:** highest in the manual product. Single block on purpose: it is the
  boundary that keeps rule 4 true and carries load-bearing tests 1 and 3.
- **Remote:** yes.
- **Parallel:** limited. Schema and the export worker can run in parallel; the state
  machine and pointer swap stay with one writer.
- **Done:** replacement changes text, verdict, and media atomically; old sets survive
  failure; no draft text or coach playback object reaches a player.

## Block 06 — Player experience and delivery

- **Tasks:** 18, 19, 20, 21
- **Goal:** a linked player opens their clips on a phone, may reflect, is notified once,
  and both roles see an honest evidence record.
- **Dependencies:** Block 05.
- **Deliverables:** player home and goal sequence from current published revisions only;
  object-specific clip signing with expected-revision checks; author-controlled
  `player_reflection` with RLS; Resend templates, redirect allowlist, publication email,
  reflection digest; filled/outlined evidence dots for both roles.
- **Security/privacy:** high. Minors' authored text, permanent deletion, and the rule
  that no reflection text ever enters an email, job, or event.
- **Remote:** yes.
- **Parallel:** yes — player UI, reflections, email, and timeline are separable once the
  published-evidence read contract is frozen.
- **Done:** no full video identifier or URL appears in a player response or DOM; a
  reflection never gates playback; no score, rank, or aggregate exists in API or UI.

## Block 07 — Retention, deletion, and product events

- **Tasks:** 22
- **Goal:** every deadline in `docs/10-security-privacy.md` is enforced and verified
  erasure is real.
- **Dependencies:** Blocks 05 and 06.
- **Deliverables:** cleanup of failed uploads and processing, source expiry, season
  cutoff, obsolete export cleanup, product-history expiry, shared-footage hard deletion,
  restricted content-free manifests with RLS, worker fencing, backup deletion replay,
  content-free operational events, review-duration and open-rate SQL.
- **Security/privacy:** highest overall, and destructive. Kept in its own block so no
  feature work shares a branch with irreversible deletion behavior.
- **Remote:** yes, with disposable fixtures only.
- **Parallel:** limited. Deletion ordering is one writer; event and query work can run
  beside it.
- **Done:** deletion removes all scoped objects and rows, marks unresolved failures
  honestly, restore cannot re-expose erased content, and owner confirmations are recorded
  before any real-data onboarding.

## Real-use gate

Blocks 08–10 do not start until every condition in the `Mandatory real-use gate` section
of `docs/06-tasks.md` is true and recorded in `STATUS.md`.
