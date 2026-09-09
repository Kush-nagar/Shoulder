@AGENTS.md

# Claude Code adapter

## Session start

- Read `STATUS.md`.
- Read the assigned project/task file before opening source.
- For legacy Tasks 1–5, use `docs/task-<n>-verification.md` as the implementation index.
- From Task 6 onward, prefer the assigned `docs/projects/project-*.md` and its workstream file over rereading all of `docs/06-tasks.md`.
- Read `docs/06-tasks.md` only when the assigned project file requires resolving an authoritative task requirement or dependency.
- Do not recursively read the repository or re-derive architecture without a concrete reason: a named file in a verification/project record, a failing check, a review comment, or a file you are changing.
- Do not run `/init` to replace this file. Suggest focused edits instead.

## Planning and scope

- Use plan mode before work involving authentication, RLS, storage authorization, video publishing, destructive data behavior, or more than one service.
- Avoid over-engineering. Implement only the assigned project/task and requirements clearly necessary for it.
- Do not begin later project blocks early.
- Preserve accepted architecture unless a failing test, specification conflict, or verified defect requires a change.
- Clean up temporary scripts/files created during investigation.

## Project-block workflow

From Task 6 onward:

- The coordinator owns the complete project block.
- Freeze shared contracts before parallel implementation.
- Delegate genuinely independent workstreams to subagents.
- Use separate branches/worktrees for concurrent write-capable agents.
- One writer per file/area at a time.
- Do not let multiple agents independently redefine the same schema, API contract, migration, or shared type.
- The coordinator reviews every subagent diff before integration.
- Integrate work in dependency order.
- Run project-level verification after integration.
- Produce one project-level verification record mapping evidence back to included repository tasks.
- Do not start the next project block until the current block is reviewed and merged.

## Tool / context discipline

- Use Caveman Full during implementation when available.
- Delegate independent investigation/build/review work to subagents and return compact findings to the coordinator.
- Use Context7 only for current/version-specific third-party API or library documentation, preferably through a docs-researcher subagent.
- Do not use Context7 for repository logic or information already present in project docs.
- Use Supabase MCP only for `Shoulder Dev`, preferably project-scoped and read-only unless a task explicitly requires a controlled write.
- Only the coordinator may manage GitHub PR, CI, review, push, and merge state.
- Subagents must not recursively explore the repository.
- Each subagent should read only:
  - `CLAUDE.md`
  - its project-block file
  - its workstream file
  - directly relevant source/test files
- Do not load tools, docs, or files merely because they are available.

## Git and agent safety

- Do not let two write-capable agents edit the same checkout simultaneously.
- Do not force-push, reset shared work, delete branches, drop data, or bypass verification without explicit approval.
- Use simple commit messages.
- Do not merge a project branch until required checks and independent review pass.
- Never commit `.env.remote`, Supabase temp state, credentials, tokens, passwords, or machine-specific artifacts.

## Review

- The OpenAI Codex plugin may be used for a read-only second review or a bounded rescue task.
- Prefer `/codex:review --background` after project-level local tests pass.
- Use `/codex:adversarial-review` for authentication, RLS, deletion, storage access, queue concurrency, destructive migrations, and data-loss risks.
- Do not enable an automatic review gate by default; it can create unnecessary agent loops and usage.
- External GPT/Codex review should evaluate the completed project block, not every small subtask individually.
- If review causes changes, subsequent review should normally inspect only the delta from the previously reviewed SHA.

## Verification discipline

- Run targeted tests during implementation.
- Before a project block is considered complete, run its required integration/security/remote tests plus the repository quality gate.
- No required suite may silently skip.
- Verification records are evidence indexes, not narrative logs; keep them concise and current.
- Never record secrets in verification files.

## Context efficiency

- Prefer:
  project/verification record → targeted file → targeted test → fix

  over:
  full repo scan → architecture rediscovery → broad refactor

- Do not reread completed tasks unless a current dependency or defect requires it.
- Use Git history and verification records as indexes into prior work.
- Keep coordinator summaries compact so context is preserved for implementation.
