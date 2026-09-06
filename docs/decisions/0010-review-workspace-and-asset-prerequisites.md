# ADR 0010 — Review workspace and asset prerequisites

- Status: Accepted; Task 1 asset/deployment timing amended by ADR 0012
- Date: 2026-09-04

## Context

Screen behavior removed the review navigation rail while the visual specification retained it. Keyboard verdict 3 lacked a specified visible control. Required fonts and vector artwork were absent from the handoff.

## Decision

Review has no global rail at any viewport. Its top bar contains Back to match, fixed match/player/goal context, save state, keyboard help, and Publish clips. Ordinary coach pages retain the global rail. The verdict fieldset has three visible radio choices: You did this, Chance to do this, and Not relevant. The third is coach-only, labelled “Kept for the coach; excluded from publishing,” and fully operable without shortcuts.

For Task 1, use the owner-approved mark and wordmark in `assets/brand/` under `docs/decisions/0012-task-1-local-acceptance.md`. Obtain and approve remaining SVG variants in `docs/08-brand.md` before their placements ship. Record receipt in `assets/README.md` and `STATUS.md`. The supplied PNG is reference-only. Raster derivatives can be exported later from approved vectors; no tracing or font approximation substitutes for approval.

## Task 1 font sourcing amendment

Inter Tight may be added during Task 1 through `@fontsource-variable/inter-tight`. Self-host its WOFF2 assets covering weights 400/500/600 through `next/font/local`, preserve its included SIL Open Font License with the assets and in distributions, and make no runtime request to Google Fonts. Pin an exact package version in the dependency manifest and project lockfile. After installation, document the exact resolved version, package provenance, asset paths, and retained license location in `assets/README.md`; record the resolved version and completion in `STATUS.md`. Font receipt is not a pre-start prerequisite; the approved family and visual specification are unchanged.

This package supplies approved font binaries that the platform font loader does not provide. It is an asset delivery decision, with no change to typography, logo approval, or review behavior. Installation and verification remain Task 1 work.

## Consequences and validation

Task 1 asset receipt is now recorded from the supplied SVGs, not inferred from documentation reconciliation; local acceptance and deferred deployment follow ADR 0012. Frontend acceptance checks the common shell, three verdict controls, keyboard parity, and approved asset usage. The visual layout follows screen behavior for dashboard ordering and evidence dots; dots are discrete links, not a chart or score.
