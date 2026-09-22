-- Operational Phase C gate: median elapsed full-roster review minutes.
-- A review completes only when every player rostered at its start has a
-- successful publication. Failed, cancelled, and replacement requests do not
-- create false completions. The result is aggregate, never a player score.
WITH review_starts AS (
    SELECT event.game_id, min(event.occurred_at) AS started_at
    FROM app.product_event event
    WHERE event.team_id = :'team_id'::uuid
      AND event.event_type = 'review_started'
      AND event.occurred_at >= :'window_start'::timestamptz
    GROUP BY event.game_id
), first_success AS (
    SELECT publication.game_id, publication.player_id,
           min(publication.published_at) AS published_at
    FROM app.review_publication publication
    JOIN app.game game ON game.id = publication.game_id
    WHERE game.team_id = :'team_id'::uuid
      AND publication.published_at IS NOT NULL
    GROUP BY publication.game_id, publication.player_id
), completed_games AS (
    SELECT start.game_id,
           extract(epoch FROM (max(success.published_at) - start.started_at))
               / 60.0 AS review_minutes
    FROM review_starts start
    JOIN app.game game ON game.id = start.game_id
    JOIN first_success success
      ON success.game_id = start.game_id
     AND success.published_at >= start.started_at
    JOIN app.player player
      ON player.id = success.player_id
     AND player.team_id = game.team_id
     AND player.created_at <= start.started_at
     AND (player.deleted_at IS NULL OR player.deleted_at > start.started_at)
    GROUP BY start.game_id, start.started_at, game.team_id
    HAVING count(DISTINCT success.player_id) = (
        SELECT count(*)
        FROM app.player rostered
        WHERE rostered.team_id = game.team_id
          AND rostered.created_at <= start.started_at
          AND (rostered.deleted_at IS NULL
               OR rostered.deleted_at > start.started_at)
    )
    AND count(DISTINCT success.player_id) > 0
)
SELECT count(*) AS completed_game_count,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY review_minutes)
           AS median_review_minutes
FROM completed_games;
