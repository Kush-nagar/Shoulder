@AGENTS.md

## Claude Code adapter

- At session start, read `STATUS.md` and the assigned task in `docs/06-tasks.md`.
- Each finished task keeps a `docs/task-<n>-verification.md` record of its contract, decisions, file inventory, and verification commands. Read the relevant record before opening source; use it as the index into that task's implementation.
- Do not recursively read the repository or re-derive the architecture without a concrete reason: a named file in a record, a failing check, a review comment, or a file you are changing.
- Do not run `/init` to replace this file. Suggest focused edits instead.
- Use plan mode before a task that touches authentication, RLS, storage authorization, video publishing, or more than one service.
- The OpenAI Codex plugin may be used for a read-only second review or a bounded rescue task. Do not let two write-capable agents edit the same checkout simultaneously.
- Prefer `/codex:review --background` after the task's local tests pass. Use `/codex:adversarial-review` for auth, RLS, deletion, storage access, queue concurrency, and data-loss risks.
- Do not enable an automatic review gate by default; it can create long agent loops and unnecessary usage.
