# 01 — Product

## What Shoulder is

A coach assigns one player one active development goal. After a game, the coach marks three to six moments, selects either “You did this” or “Chance to do this,” writes one sentence in their own words, and publishes separate player-only clips. The player watches on a phone and may write what they noticed.

Over time, the clips form a private development record organized by goal and game.

## What Shoulder is not

- Not a scouting platform
- Not a team analytics dashboard
- Not a highlight generator
- Not a score, ranking, or comparison system
- Not an AI coach
- Not a parent monitoring product
- Not a live match tool

## Why the name works

“Check your shoulder” is the coach's phrase for looking before receiving the ball. “Shoulder-to-shoulder” also describes the product relationship: the coach stands beside the player rather than measuring them from above.

The name also marks the technical boundary. Sideline phone video cannot reliably reveal a small, distant player's head and eye direction. The system can find the situation in which scanning matters; the coach decides whether it happened.

## Users

| | Coach | Player |
|---|---|---|
| Primary device | Laptop | Phone |
| Typical session | 10–25 minutes after a game | 3–5 minutes after publication |
| Creates | Roster, games, goals, observations, judgments | Optional reflections |
| Reads | Data for the one team they coach | Their own active goals, published judgments, clips, and reflections |
| Never receives | Player-private password/session data | Full match video, drafts, rejected candidates, or another player's data |

The initial age range is 13–18. Do not onboard anyone under 13 until a specific consent and legal path is approved.

## The product loop

1. Coach sets one active goal for a player.
2. Coach uploads a game video.
3. The worker produces coach-only playback and timeline thumbnails.
4. Coach manually marks candidate moments.
5. Coach records a human judgment and one sentence.
6. Publish exports three to six isolated player clips.
7. Player opens a secure link, reads the coach's sentence, and watches the clip.
8. Player may write a reflection.
9. Coach reads the reflection and adjusts the next goal or next review.

Computer vision later changes only step 4 by nominating timestamps. It changes none of the other authority or visibility rules.

## Three record types

| Record | Meaning | Author | Mutability |
|---|---|---|---|
| `observation` | Something may have happened at a time range | Coach or retrieval system | Append-only |
| `judgment` | What a coach concluded about an observation | Authenticated coach only | Editable by author until/after publish with history |
| `player_reflection` | What the player said about one judgment | Authenticated player | Append-only in MVP |

Never collapse these types. Their separation is what makes model evaluation possible without allowing a model to become the author.

## Non-negotiable behavior

1. Every judgment has a human `author_user_id`.
2. A player sees no number intended to measure ability or compare them with anyone.
3. A player receives no full-match object or URL.
4. A player sees at most six clips from one game.
5. `applied` renders as “You did this.”
6. `opportunity` renders as “Chance to do this.”
7. `not_relevant` remains coach-only.
8. Reflection is optional and never blocks playback.
9. Raw uploads expire after 90 days.
10. No biometric or persistent appearance identity is stored.

## MVP scope

**Included:** one team, coach and player roles, magic-link login, roster bulk entry, one active goal per player, game upload, 720p coach playback, thumbnails, keyboard-first manual marking, coach-authored judgments, clip export, player mobile view, reflections, evidence-by-game timeline, email notification, deletion and retention jobs.

**Excluded:** computer vision, parent accounts, billing, organizations, native apps, practices, live analysis, chat, push/SMS, social features, team analytics, recommendations, generated summaries, and multiple active goals per player.

## MVP definition of done

A coach can complete the entire loop without developer help for two consecutive real games. Median review time is below 25 minutes for a roster, at least half the invited players open within 48 hours without a reminder, at least one reflection is submitted, and the coach chooses to repeat the process for a third game.

All load-bearing privacy tests pass, and the workflow uses zero machine learning.

## Product metric

Primary: count of players who received coach-verified evidence on an active goal in the previous 14 days.

Supporting operational measures:

- Median coach review time per player
- Time from publish click to all player clips ready
- Player open rate within 48 hours
- Coach return for the next game

These measures are for operating the product. They never appear in a player's interface and are never compared across players.

## Kill and redesign conditions

- Coach review stays above 25 minutes for a roster after two iterations.
- Players avoid opening because the experience feels punitive or confusing.
- Clip export or upload reliability repeatedly causes lost work.
- A safe player-only video boundary cannot be demonstrated in automated tests.

If any condition holds, fix the manual loop. Do not add computer vision to hide the problem.
