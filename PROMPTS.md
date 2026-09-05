# Working prompts

Use one coherent chat per task. Do not paste the whole documentation set into a prompt; both agents can read the repository.

## Start a planning session

> Project: Shoulder. Read `AGENTS.md`, `STATUS.md`, `docs/01-product.md`, and Task N in `docs/06-tasks.md`. Read only the references named by that task. Do not implement yet. Check the prerequisites, identify one blocking ambiguity at most, and give me a file-by-file plan with the exact tests that will prove the task is done.

## Implement one task later

> Implement Task N from `docs/06-tasks.md`. Follow `AGENTS.md` and the relevant numbered docs. Stay within this task, write the named tests, run the relevant checks, review your diff, and update `STATUS.md`. Stop if a rule, prerequisite, or security boundary is unresolved.

## Ask Claude Code to use Codex as reviewer

After tests pass in Claude Code:

> Run `/codex:review --background`, continue with other non-overlapping checks, then use `/codex:result`. Address only findings supported by the spec, tests, or code. If a finding changes architecture or schema, stop and present the tradeoff instead of silently changing it.

For high-risk work:

> Run `/codex:adversarial-review --background` focused on cross-player access, full-match video exposure, signed-URL scope, session validation, RLS bypass, deletion completeness, race conditions, and draft loss.

## Ask Codex to review a Claude branch

> Review this branch against `AGENTS.md`, the assigned task in `docs/06-tasks.md`, and `docs/11-testing-quality.md`. Prioritize correctness, security, privacy, regressions, and missing tests. Do not rewrite the feature. Report only findings that are actionable and cite the affected files.

## Transfer from Claude Code into Codex

Inside Claude Code, use `/codex:transfer`, then run the printed `codex resume <session-id>` command in a terminal. Use this when the discussion context matters, not for ordinary code review.

## Resolve agent disagreement

> Claude recommends X and Codex recommends Y. Compare both against the product rule, ADRs, named acceptance test, and smallest-correct-thing rule. State which evidence decides the issue. If the evidence does not decide it, design the smallest experiment or ask me to choose; do not average the proposals.

## End-of-task handoff

> Before stopping, update `STATUS.md`. Summarize the outcome, changed files, tests and results, remaining risks, and the next eligible task. Do not claim completion if the named definition-of-done evidence is missing.
