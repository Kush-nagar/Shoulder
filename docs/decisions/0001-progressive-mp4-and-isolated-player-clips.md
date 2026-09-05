# ADR 0001 — Progressive coach MP4 and isolated player clips

- Status: Accepted
- Date: 2026-08-24

## Context

The earlier plan used HLS for full-match playback and proposed presenting time-bounded evidence from the same full-match media. A private HLS manifest references additional playlists/segments that require their own authorization strategy. More importantly, giving a player any URL for a full-match object exposes footage outside the displayed clip bounds; client-side start/end controls are not access control.

## Decision

For the MVP:

1. Transcode a coach-only, seekable 720p H.264/AAC MP4 with fast-start metadata and frequent keyframes.
2. Deliver it from private R2 through an object-specific, short-lived URL and HTTP Range requests.
3. On publish, export a separate MP4 object for each player-visible judgment.
4. Sign only that isolated clip object for the authorized player.
5. Defer HLS until measured 90-minute playback fails the startup/seek budgets.

## Consequences

- Authorization is easier to reason about and test.
- Player access cannot reveal the full match through the same media URL.
- MVP transcoding/storage may duplicate bytes for published clips.
- Progressive delivery may be less adaptive on poor connections.
- Exact clip re-encoding adds worker time but produces safer boundaries.

## Revisit trigger

Task 11 records full-match first-frame, seek, transfer, and failure measurements. If budgets fail, write a new ADR for a private adaptive-streaming design that explicitly authorizes every referenced object and preserves separate player clips.
