# ADR 0019 — A cloud-hosted, multi-provider autonomous build system

- Status: Accepted
- Date: 2026-09-12

## Context

Blocks 01 to 03 were built with a human running Claude Code on one Windows
workstation. That works, but it makes progress depend on a laptop being awake
and on a conversation staying alive. `STATUS.md` named `AGENTOPS_BOOTSTRAP` as
the next action: move execution into the cloud so the remaining canonical
backlog (Tasks 14 to 22, then the real-use gate) can proceed without routine
intervention.

The system needs to survive context exhaustion, worker crashes, and provider
quota limits, and it must not weaken any Shoulder invariant to do so. It also
has to be cost-aware: Tasks 14 to 22 are mostly ordinary application work, and
paying frontier prices for all of it is waste.

Three constraints shaped the design more than anything else.

**Codex cannot authenticate from GitHub Actions with a ChatGPT subscription.**
`openai/codex-action@v1` accepts an API key only. Subscription-backed Codex
access tokens exist but require a ChatGPT Business or Enterprise workspace.
Project policy requires OpenAI to write all frontend code, so that lane bills
the OpenAI API or it does not exist.

**Codex CLI no longer speaks Chat Completions.** `wire_api` accepts only
`responses`, so Codex cannot be pointed at OpenRouter. The two are not
interchangeable transports.

**Claude Code can be pointed at OpenRouter.** OpenRouter serves an
Anthropic-compatible endpoint at `https://openrouter.ai/api`, and Claude Code
reaches it through `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`, preserving
tool use and reasoning. That makes one harness serve two lanes.

## Decision

Three execution lanes, two harnesses, one control plane.

| Lane | Harness | Billing | Writes |
|---|---|---|---|
| `claude_subscription` | `anthropics/claude-code-action@v1` | Claude subscription | backend, review |
| `codex_api` | `openai/codex-action@v1` | OpenAI API | frontend and backend, review |
| `openrouter` | `anthropics/claude-code-action@v1` | OpenRouter credits | backend overflow, review |

GitHub Actions is the durable control plane. A coordinator selects and
dispatches work, a worker implements exactly one task on its own branch, and a
watchdog recovers what event-driven continuation misses. State lives in
`ops/state/` and in Git history, never in a conversation.

Routing is by **capability class**, not by model name. `services/agentops/catalog.py`
discovers what exists now and records context, modalities, tool support,
reasoning support, price, and deprecation. The router picks the cheapest
qualified model in the highest-priority eligible lane that clears the class
requirements. A model that ships next month is picked up without an orchestrator
change.

Four rules bind before cost, as filters rather than scores:

1. Frontend implementation goes to the OpenAI lane or it does not happen.
2. A model is `CANDIDATE` until it passes a synthetic qualification suite.
3. An endpoint that cannot meet zero data retention is ineligible at any price.
4. When no authorised lane qualifies, the result is `BLOCKED_PROVIDER`.

Subscription capacity outranks metered capacity even when the metered model has
a lower list price: allowance already paid for is cheaper than new API spend.

## Consequences

Claude Code on the workstation becomes the bootstrap environment rather than a
permanent dependency. Work continues while the laptop sleeps.

Frontend tasks have a hard cost floor. Without `OPENAI_API_KEY` they block
rather than being routed to a forbidden writer. That is the intended failure:
policy is not negotiable against availability.

Discovery depends on OpenRouter's public catalogue, including for the Anthropic
and OpenAI families. The endpoint needs no key and its metadata matched the
providers' own documentation when checked, but it is a third party describing
someone else's models. Capability metadata is treated as a filter for
eligibility, never as a promise, and qualification is what actually admits a
model to real work.

Autonomy ships disabled. `AUTONOMY_ENABLED` is a repository variable, so it can
be switched off without landing a commit.

Phase D and later stay out of reach. `allow_phase_d_and_later` is false and
Task 23 carries the gate flag, so the coordinator cannot start machine-learning
work however the backlog is edited. `AGENTS.md` rule 5 is enforced in code, not
by convention.

## Alternatives considered

**A separate DeepSeek API key.** Rejected. OpenRouter already serves the current
DeepSeek family with ZDR enforcement, so a fourth credential adds a secret to
manage and buys nothing.

**Writing an agent loop so OpenRouter could drive frontend work.** Rejected. It
would mean maintaining a worse coding agent to avoid one API key, and it would
route frontend work around the policy that exists to stop exactly that.

**Cron-driven sequencing.** Rejected as the primary path. Merges already
generate events; waiting for a tick between healthy tasks adds latency for
nothing. Cron is kept for recovery only.

**Parsing task completion from `STATUS.md` prose.** Rejected. `ops/state/progress.json`
is the machine-readable ledger and `STATUS.md` stays the human summary; the
coordinator updates both.
