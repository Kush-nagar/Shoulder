@AGENTS.md

## Claude Code adapter

- At session start, read `STATUS.md` and the assigned task in `docs/06-tasks.md`.
- Do not run `/init` to replace this file. Suggest focused edits instead.
- Use plan mode before a task that touches authentication, RLS, storage authorization, video publishing, or more than one service.
- The OpenAI Codex plugin may be used for a read-only second review or a bounded rescue task. Do not let two write-capable agents edit the same checkout simultaneously.
- Prefer `/codex:review --background` after the task's local tests pass. Use `/codex:adversarial-review` for auth, RLS, deletion, storage access, queue concurrency, and data-loss risks.
- Do not enable an automatic review gate by default; it can create long agent loops and unnecessary usage.
