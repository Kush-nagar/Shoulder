# ADR 0010 — Review workspace and asset prerequisites

- Status: Accepted
- Date: 2026-09-04

## Context

Screen behavior removed the review navigation rail while the visual specification retained it. Keyboard verdict 3 lacked a specified visible control. Required fonts and vector artwork were absent from the handoff.

## Decision

Review has no global rail at any viewport. Its top bar contains Back to match, fixed match/player/goal context, save state, keyboard help, and Publish clips. Ordinary coach pages retain the global rail. The verdict fieldset has three visible radio choices: You did this, Chance to do this, and Not relevant. The third is coach-only, labelled “Kept for the coach; excluded from publishing,” and fully operable without shortcuts.

Before Task 1 begins, obtain all approved SVG variants listed in `docs/08-brand.md`, the original vector source/usage approval, and licensed local Inter Tight files covering weights 400/500/600 with version/provenance. Record receipt in `assets/README.md` and `STATUS.md`. The supplied PNG is reference-only. Raster derivatives can be exported later from approved vectors; no tracing or font approximation substitutes for approval.

## Consequences and validation

Task 1 remains gated while the required inputs are absent; a documentation reconciliation cannot mark them received. Frontend acceptance checks the common shell, three verdict controls, keyboard parity, and approved asset usage. The visual layout follows screen behavior for dashboard ordering and evidence dots; dots are discrete links, not a chart or score.
