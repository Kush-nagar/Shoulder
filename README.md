# Shoulder

Shoulder is a private, coach-led soccer development tool. A coach gives one player one active development goal, marks three to six moments from a match, writes one sentence about each moment, and publishes player-only clips. The player watches on a phone and may write a reflection.

Computer vision is optional and deferred. When it is introduced, it may nominate moments for a coach to inspect. It never judges a player, produces a score, or writes text a player can see.

## Start here

Read in this order:

1. `AGENTS.md`
2. `STATUS.md`
3. `docs/01-product.md`
4. The current task in `docs/06-tasks.md`
5. Only the task-specific references named by that task

Claude Code loads `CLAUDE.md`, which imports `AGENTS.md`. Codex loads `AGENTS.md` directly. The two tools therefore receive the same canonical rules.

## Document map

| File | Purpose |
|---|---|
| `AGENTS.md` | Non-negotiable engineering and product rules |
| `CLAUDE.md` | Claude Code adapter; imports `AGENTS.md` |
| `STATUS.md` | Current task, completed work, decisions, and blockers |
| `PROMPTS.md` | Copy-ready prompts and the two-agent workflow |
| `docs/00-decisions.md` | Resolved contradictions and architecture decisions |
| `docs/01-product.md` | Product definition, users, loop, and scope |
| `docs/02-architecture.md` | System boundaries, data flow, deployment, and storage |
| `docs/03-schema.md` | Database contract and RLS access matrix |
| `docs/04-api.md` | HTTP contract and authorization rules |
| `docs/05-ui.md` | Screen-level behavior and copy requirements |
| `docs/06-tasks.md` | Ordered implementation plan and gates |
| `docs/07-cv.md` | Deferred offline computer-vision plan |
| `docs/08-brand.md` | Brand rules and asset requirements |
| `docs/09-frontend-design-system.md` | Detailed visual, responsive, component, and interaction specification |
| `docs/10-security-privacy.md` | Threat model, minor-safety controls, retention, and deletion |
| `docs/11-testing-quality.md` | Test strategy, performance budgets, and release gates |
| `docs/12-agent-workflow.md` | Codex/Claude Code comparison, setup, handoffs, and conflict rules |
| `docs/13-licenses-and-sources.md` | External-code boundaries and research sources |
| `docs/decisions/` | Focused architecture decision records |
| `assets/` | Supplied brand reference and production-asset requirements |

## Status of this package

This is a planning and build-handoff package. It intentionally contains no application implementation, generated migrations, credentials, datasets, model weights, or vendored SoccerMaster code.

The initial handoff is committed/pushed to the configured GitHub repository. Documentation reconciliation adds decisions D15–D20 and ADRs 0006–0011; see `docs/00-decisions.md` for the authoritative rules. Task 1 remains the first implementation task, but it cannot start until the owner-provided vector/font inputs and repository visibility listed in `STATUS.md` are confirmed. The PNG reference does not satisfy the production-asset gate.

## Product boundary in one sentence

The software retrieves evidence; the coach decides what it means.
