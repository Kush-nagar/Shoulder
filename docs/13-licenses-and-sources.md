# 13 — Licenses and research sources

Research was rechecked on **2026-08-24**. Official/primary documentation is authoritative over this handoff when versions change. Verify current framework and service documentation again when its implementation task begins.

## External code and data boundary

### SoccerMaster

- Repository: <https://github.com/haolinyang-hlyang/SoccerMaster>
- Paper: <https://arxiv.org/abs/2512.11016>

The repository was useful for designing an offline soccer-understanding experiment, but the inspected repository file list did not contain a `LICENSE` file on the research date. Absence of a license is not permission to copy or redistribute code. Therefore:

- keep SoccerMaster and its weights outside the Shoulder repository;
- do not copy, vendor, modify-and-redistribute, deploy publicly, or include it in a downloadable artifact;
- do not assume the paper, source, model weights, pretrained encoders, or datasets share the same terms;
- record exact commits, weights, datasets, and their individual terms in the private research workspace;
- contact the authors or obtain a clear license before public deployment or distribution;
- recheck this status before Task 24, before sharing a demo, and before any commercial use.

The Shoulder adapter and artifact schema should be implementation-independent so another properly licensed detector/tracker can replace it.

### Fonts and icons

- Obtain Inter Tight from an official source, retain its license text, self-host only the required variable/static files, and record the exact version.
- The supplied Shoulder mark/wordmark is treated as user-provided brand artwork. Obtain the original vector source and confirm ownership/usage rights before public release.
- If a UI icon library is added, choose one consistent set, pin its version, preserve its license notice, and document why native/text controls were insufficient. Do not mix icon libraries.

### Media and test data

- Real team footage, stills, player names, and reflections are never committed to source control or copied to public issue trackers.
- Test videos are synthetic or explicitly licensed fixtures with documented provenance.
- A team's permission to review footage does not automatically authorize training a model, publishing examples, or sharing data with a third party.

## Agent/tooling sources

| Topic | Primary source | Used for |
|---|---|---|
| Codex repository instructions | <https://developers.openai.com/codex/agent-configuration/agents-md> | `AGENTS.md` discovery and layering |
| Codex engineering workflow | <https://developers.openai.com/codex/learn/best-practices> | Planning, testing, review, and task scoping |
| Codex changelog, 2026-08-24 | <https://learn.chatgpt.com/docs/changelog> | Deprecated MCP-server command, official Claude plugin route, and Claude Code import support |
| Official Claude Code plugin | <https://github.com/openai/codex-plugin-cc> | Installation, setup, review, rescue, transfer, and status commands |
| Claude Code memory/instructions | <https://code.claude.com/docs/en/memory> | `CLAUDE.md` and `@AGENTS.md` import pattern |
| Claude Code MCP | <https://code.claude.com/docs/en/mcp> | Current MCP behavior and scope |
| Claude Code headless mode | <https://code.claude.com/docs/en/headless> | Scripted `claude -p` boundary, if later needed |

Do not build a custom Codex↔Claude message bus for the MVP. Use the official plugin in Claude Code or separate processes coordinated through Git, worktrees, `STATUS.md`, and explicit handoffs.

## Platform and security sources

| Topic | Primary source | Decision informed |
|---|---|---|
| Supabase server-side auth | <https://supabase.com/docs/guides/auth/server-side> | Cookie-based SSR sessions and PKCE |
| Supabase Next.js tutorial | <https://supabase.com/docs/guides/getting-started/tutorials/with-nextjs> | Supported browser/server client boundary |
| Supabase RLS | <https://supabase.com/docs/guides/database/postgres/row-level-security> | Policies, indexes, claims, and role cautions |
| Supabase Data API security | <https://supabase.com/docs/guides/api/securing-your-api> | Keep product tables outside exposed schemas and separate grants from RLS |
| R2 uploads | <https://developers.cloudflare.com/r2/objects/upload-objects/> | Direct multipart upload and resumable completed parts |
| R2 presigned URLs | <https://developers.cloudflare.com/r2/api/s3/presigned-urls/> | Object/verb-specific private access |
| HTTP Range requests | <https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Range_requests> | Seekable progressive MP4 delivery |
| Media buffering/seeking | <https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Audio_and_video_delivery/buffering_seeking_time_ranges> | Player seek/load behavior |

Important implementation notes from this research:

- `user_account.id` should use the Supabase Auth user UUID rather than an unrelated application UUID.
- Product tables should remain in a non-exposed `app` schema because Shoulder uses FastAPI rather than the Supabase Data API for product access.
- User authorization must not trust editable metadata.
- Next.js should verify identity with `getClaims()`; a session object used to retrieve a token is not itself authorization evidence.
- The user-request database role must not bypass RLS.
- Use current Supabase publishable/secret key terminology and verify the migration timeline when the project is created.
- One signed HLS manifest does not automatically authorize the referenced private playlists/segments; the MVP therefore uses a seekable progressive MP4 and separately exported player clips.

## Interface standards

| Topic | Primary source | Target |
|---|---|---|
| WCAG 2.2 | <https://www.w3.org/TR/WCAG22/> | Level AA |
| Target size minimum | <https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html> | 24 × 24 CSS px minimum; Shoulder chooses 44 × 44 on mobile |
| Contrast minimum | <https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum> | 4.5:1 normal text baseline |
| ARIA Authoring Practices | <https://www.w3.org/WAI/ARIA/apg/> | Keyboard/focus patterns for complex widgets |
| Core Web Vitals | <https://web.dev/articles/vitals> | LCP <=2.5 s, INP <=200 ms, CLS <=0.1 at p75 |

The visual specification also uses calculated contrast ratios. Recalculate them with the actual CSS, font size, states, opacity, and background during implementation; a token-table ratio does not certify a component.

## Dependency policy

Before adding a runtime dependency:

1. Prefer platform or standard-library capability where it is clear and secure.
2. Confirm maintenance activity, license, transitive dependency footprint, security history, and browser/server compatibility.
3. Pin through the package manager lockfile; do not copy source snippets without provenance.
4. Record the decision when the dependency introduces a service, data processor, UI system, or architectural boundary.
5. Preserve required license/notice files in distributions.
6. Run automated license and vulnerability checks, then review exceptions manually.

Avoid dependencies for basic buttons, status dots, time formatting, simple job backoff, or features deferred from the MVP.

## Research caveats

- Service behavior, pricing, keys, SDKs, framework versions, and product features can change.
- Repository file lists can change after the research date.
- Performance targets are hypotheses until measured with Shoulder footage, browsers, and deployment regions.
- Legal obligations depend on location, organization, age, and data use; engineering controls do not determine compliance by themselves.
