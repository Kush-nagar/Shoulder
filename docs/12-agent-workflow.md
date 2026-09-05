# 12 — Claude Code and Codex workflow

## Recommendation for Shoulder

Use **Claude Code as the terminal session driver and Codex as the independent reviewer, adversarial reviewer, rescue path, and occasional isolated implementer**. This is a workflow choice, not a claim that one model is universally better.

Why this arrangement fits this project:

- The existing conversation and planning context started in Claude Code.
- OpenAI's official Claude Code plugin can launch Codex against the same repository and return structured results.
- `CLAUDE.md` imports the canonical `AGENTS.md`, so both agents receive one rule set.
- A separate reviewer is particularly valuable for Shoulder's RLS, minor privacy, signed-media, upload recovery, and clip-boundary risks.

For a long build, consistency matters more than constantly switching. Keep one tool as the writer for a task and the other as reviewer. Switch the primary only at a clean task/branch boundary.

## Practical comparison

| Dimension | Claude Code | Codex | Shoulder use |
|---|---|---|---|
| Repository instructions | Reads `CLAUDE.md`; can import `@AGENTS.md` | Reads layered `AGENTS.md` files | One canonical `AGENTS.md`; thin adapter for Claude |
| Long terminal session | Terminal-first planning, editing, commands, plugins | CLI/IDE/Work/cloud workflows, review, isolated worktrees | Claude hosts the main loop; either may implement one bounded task |
| Cross-tool integration | Official OpenAI plugin can invoke local Codex | Codex CLI can import supported Claude Code setup and recent chats with `/import` | Use the plugin for live review; use import for setup/continuity, not simultaneous editing |
| Independent review | Can review but shares the active conversation | Plugin supports review/adversarial review from a separate Codex run | Use Codex after tests and before merge |
| Context transfer | Claude conversation can be transferred to Codex through the plugin | Returned session can be resumed with Codex CLI | Use only for genuinely context-heavy debugging |
| Parallel work | Supports separate agents/worktrees | Supports isolated work/worktrees | One writer per worktree; never edit the same checkout concurrently |

Do not choose a winner from a single benchmark or brand claim. Run Tasks 1–3 with the recommended workflow, record defects/rework/time, and keep the process that produces clearer, tested changes.

## Official connection: Codex inside Claude Code

The supported direct connection is OpenAI's `codex-plugin-cc`. It wraps the local Codex CLI/app server and uses the same Codex authentication, configuration, and repository.

### Prerequisites

- Claude Code is installed and working in the terminal.
- Node.js 18.18 or newer is available.
- You have a ChatGPT plan with Codex access or an OpenAI API key.
- Run the commands from the Shoulder repository root.

### Install

Inside Claude Code, run:

```text
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/reload-plugins
/codex:setup
```

If setup reports that the Codex CLI is missing, install it in the terminal:

```bash
npm install -g @openai/codex
codex login
```

Then restart or reload Claude Code and run `/codex:setup` again. Authenticate through the official browser/device flow or the environment method you already use; never paste a secret key into a repository file or chat prompt.

### Verify

From the Shoulder repository root in Claude Code:

```text
/codex:status
```

Then request a read-only review:

```text
/codex:review Review AGENTS.md and docs/00-decisions.md. Report conflicts only; do not edit files.
```

The result should show that Codex ran in the same repository and followed `AGENTS.md`. If it references a different working directory or cannot see the files, stop and fix the repository/session location before using it to edit.

### Useful plugin commands

| Command | Use |
|---|---|
| `/codex:setup` | Install/configure the local Codex bridge |
| `/codex:status` | Inspect current Codex task/session status |
| `/codex:review` | Independent review of a plan, diff, or branch |
| `/codex:adversarial-review` | Try to break security, privacy, and correctness assumptions |
| `/codex:rescue` | Ask Codex to investigate a stuck implementation/debugging path |
| `/codex:transfer` | Import the current Claude conversation into a resumable Codex session |
| `/codex:result` | Retrieve a completed task result |
| `/codex:cancel` | Stop an active Codex task |

`/codex:transfer` prints a command similar to `codex resume <session-id>`. Use it when the current Claude conversation materially affects the work. For ordinary task review, the repository, diff, `STATUS.md`, and a concise prompt are better context than transferring an entire history.

Do not use the old `claude mcp add codex -- codex mcp-server` setup. OpenAI documents `codex mcp-server` as deprecated and directs Claude Code users to the official plugin.

## Optional reverse handoff: import Claude Code into Codex

Current Codex CLI versions support `/import` for supported Claude Code setup and recent chats. From the Shoulder repository root, start Codex, run `/import`, choose Claude Code, inspect what Codex proposes to bring over, and accept only the project material you actually want. The Codex desktop app also exposes this under Settings > Import and can keep supported imported setup updated.

Import is useful when moving the primary terminal session to Codex or recovering prior context. It is not a live two-agent bridge and does not replace `AGENTS.md`, Git, worktrees, or `STATUS.md`. After import, ask Codex to summarize the active repository instructions and current task before permitting edits.

## Repository instruction setup

Keep the root files exactly as follows:

```text
AGENTS.md       canonical product and engineering rules
CLAUDE.md       @AGENTS.md plus Claude-only workflow notes
STATUS.md       current task, branch, decisions, blockers, test results
PROMPTS.md      reusable planning/review/transfer prompts
```

`CLAUDE.md` should stay short. Do not copy the whole of `AGENTS.md` into it because duplicated rules drift. Add directory-specific `AGENTS.md` files later only when a subtree truly needs extra commands or constraints.

## Daily task loop

1. **Select:** pick one eligible task from `06-tasks.md`; verify prerequisites in `STATUS.md`.
2. **Plan:** the primary agent names files, migrations, tests, risks, and acceptance criteria before editing.
3. **Implement:** one writer works on one branch/worktree and keeps the scope bounded.
4. **Self-check:** the writer runs targeted tests, lint, types, and reviews the diff.
5. **Independent review:** Codex reviews the diff against the task and load-bearing rules.
6. **Adversarial pass:** for auth, RLS, signed URLs, upload, deletion, media, and CV, explicitly ask for bypass/failure scenarios.
7. **Resolve:** the writer verifies every finding against code/tests. Fix valid findings; explain rejected findings with evidence.
8. **Handoff:** update `STATUS.md` with files, commands/results, decisions, remaining risks, and next eligible task.
9. **Commit:** the human reviews and commits/merges. Do not let an automatic reviewer create an endless fix-review loop.

Use the optional automatic review gate only after the manual workflow is stable. Keep it off by default because repeated autonomous review/fix cycles can drain time and usage while changing already-correct code.

## When Codex should implement instead of review

Give Codex a full implementation task when one of these is true:

- the task is isolated in a separate worktree and has exact acceptance tests;
- the Claude session is stuck and `/codex:rescue` identifies a bounded alternative;
- an independent implementation is useful for a security-sensitive component;
- the user intentionally wants two approaches compared before choosing.

In those cases, pause Claude's writes to the same files. Codex reports a commit or patch and test evidence; Claude reviews the result after it is complete.

## Safe parallel work

Parallelize only independent tasks with no shared migrations, generated API types, lockfiles, or central tokens.

Good pair:

- one worktree prepares synthetic media fixtures;
- another worktree implements a pure timecode utility.

Bad pair:

- both edit the current database migration;
- one changes the OpenAPI schema while the other hand-edits client types;
- both modify the design tokens or the same review screen;
- both run formatters against the same checkout.

Each worktree owns a branch. Merge foundational changes first, rebase the dependent branch, rerun tests, then review the combined diff.

## Conflict rule

If Claude and Codex disagree:

1. Compare both claims with `00-decisions.md`, `AGENTS.md`, the task acceptance criteria, and an executable test.
2. Prefer the smaller design that preserves privacy and the product boundary.
3. Ask the user only when the choice changes product behavior, data model, cost, or irreversible architecture.
4. Record the final non-obvious choice in `docs/decisions/`.

Never resolve disagreement by asking both tools to keep editing until one stops objecting.

## Prompt hygiene

- Give the task ID and named source documents; do not paste the entire planning package into every prompt.
- State whether the request is plan, implement, diagnose, or review.
- For reviews, say “do not edit files” unless a patch is wanted.
- Require command output/test evidence and distinguish facts from assumptions.
- Keep credentials, real player data, signed URLs, and raw footage out of prompts.
- Use `PROMPTS.md` as the starting templates.

## Handoff record

Every agent handoff must include:

```text
Task and branch/worktree
Goal and acceptance criteria
Files changed
Migrations or public API changes
Commands run and exact results
Manual checks/screenshots
Security/privacy review findings
Known risks or open decisions
Next eligible task
```

This record—not an unbounded chat transcript—is the durable context for the next coding session.
