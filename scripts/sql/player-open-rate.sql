-- Operational Phase C gate: first evidence-ready emails opened within 48 hours.
-- `sent_at`, not a publish request, is the invitation clock. Restricting this
-- to the first sent delivery excludes later deliveries/reminders. The result
-- is aggregate, never a player comparison or score.
WITH invitations AS (
    SELECT DISTINCT ON (delivery.player_id)
           delivery.player_id, delivery.publication_id,
           delivery.sent_at AS invited_at
    FROM app.email_delivery delivery
    JOIN app.review_publication publication
      ON publication.id = delivery.publication_id
    JOIN app.game game ON game.id = publication.game_id
    WHERE game.team_id = :'team_id'::uuid
      AND delivery.kind = 'evidence_ready'
      AND delivery.status = 'sent'
      AND delivery.sent_at IS NOT NULL
      AND delivery.sent_at >= :'window_start'::timestamptz
    ORDER BY delivery.player_id, delivery.sent_at, delivery.id
)
SELECT count(*) AS invited_player_count,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1
           FROM app.product_event opened
           WHERE opened.event_type = 'player_opened'
             AND opened.player_id = invitations.player_id
             AND opened.publication_id = invitations.publication_id
             AND opened.occurred_at >= invitations.invited_at
             AND opened.occurred_at <= invitations.invited_at + interval '48 hours'
       )) AS opened_within_48_hours_count
FROM invitations;
