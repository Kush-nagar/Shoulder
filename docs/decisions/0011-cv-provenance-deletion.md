# ADR 0011 — Phase D CV provenance deletion

- Status: Accepted for Phase D only
- Date: 2026-09-04

## Context

Deleting observations by cascade would violate the mandatory `judgment.observation_id` relationship or destroy human judgments.

## Decision

During Phase D run deletion, delete unreferenced CV observations, tracks, assignments, and raw artifacts. Retain any observation referenced by a judgment, preserving its ID, player/video, source label, and time bounds. Clear its CV run, segment provenance when removed, confidence, event/features, and artifact pointers; mark provenance as removed. A provenance-state constraint permits a null run only after this controlled cleanup. A referenced observation cannot be deleted (`RESTRICT`), and `judgment.observation_id` never becomes null. Serialize cleanup with judgment creation and clear provenance before removing the run.

This is a narrow exception to ordinary append-only observation behavior, not an editing endpoint. It does not change human authorship or any revision. Verified personal-data/season erasure can delete the entire dependent graph under ADR 0009. No Phase D table, model dependency, or CV implementation is introduced before the gate.

## Consequences and validation

Task 27 tests referenced/unreferenced observations, deletion versus judgment-creation races, repeat deletion, preserved human revisions, and absence of retained machine metadata. Add the required RLS/constraints in that phase's migration. The detailed contract lives in `docs/07-cv.md`.
