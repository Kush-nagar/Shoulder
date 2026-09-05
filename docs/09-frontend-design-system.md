# 09 — Frontend design system

## Design objective

Build a quiet evidence workspace that feels made by a small, disciplined product team. The coach interface should make a 90-minute video manageable without resembling an analytics terminal. The player interface should make three to six moments feel personal and understandable without resembling social media, a report card, or a game.

The desired impression is: **calm, exact, warm, and obvious**.

## Experience principles

1. **Video first.** During review, the match occupies the visual hierarchy. Tools support the video instead of surrounding it with cards.
2. **One next action.** Each screen has one primary action. Secondary actions are text or restrained outline controls.
3. **Evidence before abstraction.** Show the clip and the coach's sentence; do not summarize it into scores, charts, rings, or “insights.”
4. **Progressive disclosure.** Put infrequent settings and operational details behind clear secondary surfaces.
5. **Stable layout.** Loading, success, and error states reserve space and do not make the page jump.
6. **Human restraint.** Avoid visual patterns commonly associated with generated SaaS templates: gradient heroes, floating glass cards, generic metric grids, excessive pills, and decorative sparkles.
7. **Mobile dignity.** The player product is not a compressed desktop dashboard. It is a dedicated one-column viewing experience.

## Tokens

Define semantic CSS variables in one global token layer. Tailwind consumes the variables; components must not introduce arbitrary hex values.

### Color

| Token | Value | Intended use |
|---|---:|---|
| `--sh-paper` | `#FAF9F7` | Page background |
| `--sh-surface` | `#FFFFFF` | Dialog, input, player clip surface |
| `--sh-surface-subtle` | `#F3F0EC` | Hover rows, grouped regions, skeletons |
| `--sh-ink` | `#171512` | Primary text and dark controls |
| `--sh-ink-2` | `#4E4944` | Secondary text |
| `--sh-muted` | `#6B6560` | Metadata; 5.46:1 on paper |
| `--sh-line` | `#E5E2DE` | Default dividers and borders |
| `--sh-line-strong` | `#CFC9C2` | Input and selected dividers |
| `--sh-brand` | `#C4633D` | Decorative brand accent; not normal text |
| `--sh-action` | `#9E472C` | Accessible action text/fill |
| `--sh-action-hover` | `#843A24` | Hover/pressed progression |
| `--sh-action-soft` | `#F4E4DD` | Selected moment background |
| `--sh-focus` | `#7C341F` | Keyboard focus outline |
| `--sh-error` | `#9B2C2C` | Operational errors |
| `--sh-error-soft` | `#F9E8E6` | Error background |
| `--sh-warning` | `#7A5412` | Coach-only warning text |
| `--sh-warning-soft` | `#F7EFD9` | Warning background |

Contrast baselines on paper: ink 17.32:1, muted 5.46:1, and action 5.88:1. White on action is 6.19:1. The original brand terracotta is decorative because it is only 3.84:1 on paper and white on it is 4.04:1.

Do not add green success banners to the player experience. Completion is communicated through plain copy and a check icon in ink. Error and warning colors are reserved for a real state, never decorative category coding.

### Typography

Load Inter Tight locally with `next/font`. Use variable optical behavior if the approved files provide it; otherwise use weights 400, 500, and 600. Apply font-feature settings for `tnum` on timecodes and numeric metadata.

| Role | Desktop | Mobile | Weight | Line height |
|---|---:|---:|---:|---:|
| Display | 40 px | 32 px | 600 | 1.08 |
| Page title | 30 px | 26 px | 600 | 1.15 |
| Section title | 22 px | 21 px | 600 | 1.25 |
| Component title | 17 px | 17 px | 600 | 1.35 |
| Body | 15 px | 16 px | 400 | 1.5 |
| Body strong | 15 px | 16 px | 500 | 1.5 |
| Label | 13 px | 14 px | 600 | 1.35 |
| Metadata | 13 px | 13 px | 400 | 1.4 |
| Timecode | 13 px | 14 px | 500 | 1.2 |

Do not reduce player body copy below 16 px. Use at most three type sizes in one compact component. Titles use sentence case; never all caps for navigation or labels.

### Spacing, shape, elevation

- Base unit: 4 px.
- Common spacing: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, and 80 px.
- Page gutter: 20 px mobile, 24 px tablet, 32 px desktop.
- Control height: 40 px desktop; 44 px for all player/mobile controls.
- Input radius: 8 px.
- Button radius: 8 px.
- Panel radius: 12 px.
- Player video surface radius: 14 px.
- Pills are reserved for short statuses and filters, never general containers.
- Default shadow: none. Floating dialog only: `0 16px 48px rgba(23,21,18,.14)`.
- Use one-pixel borders. Do not simulate hierarchy with nested shadows.

### Layout widths and breakpoints

| Name | Width | Behavior |
|---|---:|---|
| `sm` | 640 px | Small-tablet adjustments |
| `md` | 768 px | Player text width and two-pane thresholds |
| `lg` | 1024 px | Coach navigation rail becomes persistent |
| `xl` | 1280 px | Review page reaches full three-region layout |
| `2xl` | 1440 px | Content stops growing; add outer whitespace |

Coach content max width is 1440 px except the review workspace, which may fill the viewport. Reading/form content maxes at 680 px. Player content maxes at 560 px and stays centered on larger screens.

## Coach shell

### Desktop, 1024 px and wider

- A 72 px fixed left rail uses paper, a right border, and the mark at the top.
- Primary destinations are Dashboard and Players. Each icon has a visible text tooltip and `aria-label`.
- Team/settings and sign-out sit at the bottom; settings are secondary.
- The content header is 64 px tall with page title, optional breadcrumb, and one right-aligned primary action.
- The page background is paper. Surfaces are introduced only where grouping helps scanning.

At widths above 1280 px, the rail may expand to 216 px only on list/form pages. The review workspace keeps the narrow rail to protect video width.

### Tablet and small desktop, 768–1023 px

- Use a 60 px rail or a top bar when landscape width is constrained.
- Review retains video above a full-width moment editor; it does not squeeze both into unusable columns.
- Tables convert low-priority columns to secondary row text before horizontal scrolling is considered.

### Below 768 px

Coach upload status and basic list/detail pages remain usable. Full match review presents a polite “Use a larger screen for match review” message and permits the limited view-only playback/draft-comment behavior in `05-ui.md`; it does not pretend the keyboard timeline is mobile-ready. The player experience remains fully supported.

## Core coach pages

### Sign-in

- Center a 400 px column vertically within a calm paper page.
- Horizontal lockup at 148–176 px wide.
- Title: “Sign in to Shoulder.”
- One email field, one full-width primary button, and one line explaining the magic link.
- After submit, keep the email visible in confirmation copy and offer “Use a different email.”
- No split-screen stock photo, testimonial, feature cards, or fake trust badges.

### Dashboard

- Header: “Matches” with primary “Upload match.”
- First section: recent matches as a compact list, not a KPI card grid.
- Each row contains opponent/date, processing state, review progress in words, and last activity.
- A narrow “Players needing evidence” section may appear below only when it is actionable. It contains names and the active goal, never a score or count badge implying performance.
- Empty state: mark, “No matches yet,” one sentence, and “Upload match.”

### Players list

- Search is a standard field at the top, not an oversized command bar.
- Rows show player name, optional jersey number, active goal text, and last published evidence date.
- Do not show avatars unless the team supplies consented images; initials are unnecessary decoration.
- Add-player opens a focused dialog with name and optional jersey number.

### Player detail

- Name and roster metadata lead.
- Active development goal appears as one bordered editorial block, not a progress widget.
- Evidence history is chronological and grouped by match.
- Reflection text appears beneath its related evidence set and is visibly player-authored.
- Goal editing requires confirmation when replacing an active goal. Keep the prior goal history read-only.

### Upload

- Use a single bordered drop region, 560–680 px wide, with a normal file picker fallback.
- Before selection: accepted types, maximum configured size, and “Choose video.”
- After selection: filename, size, checksum/preparation state, one progress bar, transferred bytes, and current stage.
- During upload: “Keep this tab open while the video uploads.”
- On interruption: “Upload paused. Re-select the same file to continue from the last completed part.”
- Only after multipart completion: “Upload complete. It is safe to close this tab while Shoulder prepares the video.”
- Transcoding progress is stage-based and clearly distinguished from byte upload progress.

### Match detail

- Match identity, video state, date, opponent, and upload owner appear in a simple header.
- Primary action becomes “Start review” or “Continue review.”
- Operational actions (retry processing, delete match) live in a labeled overflow menu and require confirmation when destructive.

## Review workspace

This is the signature desktop screen. It should resemble a focused editing bench, not a broadcast-analysis cockpit.

### Layout at 1280 px and wider

- Top bar: 56 px, containing back action, match identity, save state, and “Publish clips.”
- Main area: video on the left at roughly 68% width; moment editor on the right at 32%, minimum 340 px, maximum 420 px.
- Timeline spans the video column below the player and remains visible while the moment editor scrolls.
- Background around the video is ink; the rest is paper. Keep the transition crisp, without gradient.

### Video player

- Native video behavior is wrapped in a custom minimal control bar only where required for frame-accurate keyboard work.
- Controls: play/pause, 5-second back/forward, current time/duration, volume, playback speed, and fullscreen.
- Do not autoplay with sound.
- A visible loading state reserves the aspect ratio.
- Playback errors give a retry and diagnostic ID; never reveal signed URLs.
- The current marked range may be drawn as a thin brand-colored range on the scrub track.

### Timeline

- Base height 64 px, increasing to 84 px when thumbnail sprites are ready.
- Ruler shows readable minute marks based on zoom.
- Draft moments use thin vertical flags and a short labeled range, not bubbles.
- Selected moment uses action terracotta; published moments use ink; machine candidates, after Phase D, use a hollow muted mark.
- Overlapping markers stack into two lanes before clustering. Never hide a selected mark.
- Zoom is explicit with plus/minus controls and a “Fit match” action. Trackpad zoom is optional.
- A keyboard-focused playhead has an accessible time label.

### Moment editor

- Heading displays “Moment 2 of 5” and the start/end time.
- The route is scoped to one player; show that player's name and active goal as fixed context rather than a changeable select.
- Judgment choice uses two radio-card rows: “You did this” and “Chance to do this.” Internal values remain `applied` and `opportunity`.
- Coach note is a plain textarea with the active goal nearby as context.
- Use a soft character guidance message, not a punitive counter. One sentence is the writing target.
- Actions: “Save moment” primary, “Delete draft” secondary-danger, previous/next as icon plus text.
- Draft save state is explicit: Saving…, Saved, or Could not save—Retry.

### Review keyboard map

| Key | Action |
|---|---|
| `Space` | Play/pause when focus is not in a text field |
| `J` / `K` / `L` | Rewind / pause / forward; repeated `L` increases playback rate |
| `ArrowLeft` / `ArrowRight` | Seek back/forward 1 second |
| `Shift+ArrowLeft` / `Shift+ArrowRight` | Seek back/forward 10 seconds |
| `I` / `O` | Set the selected clip in/out point |
| `1` / `2` / `3` | Applied / opportunity / not relevant |
| `C` | Focus the coach comment |
| `Enter` | Save the valid draft and advance |
| `Escape` | Return focus to the video controls; never discard a draft |
| `?` | Open keyboard help |

Show the shortcut reference from a visible “Keyboard shortcuts” action. Do not trap browser or assistive-technology shortcuts.

### Publish flow

- The primary button includes the count: “Publish 4 clips.”
- Preflight lists incomplete drafts and blocks publishing only for missing required fields or unavailable clip bounds.
- Confirmation names the player and explains that the clips become visible after export.
- After confirmation, the coach sees per-clip preparation state. The complete set remains player-invisible until every current clip is ready, then becomes visible in one transaction.
- Never imply all clips are published while an export is still pending.

## Player mobile experience

Design from 320–430 px first. It must work at 200% text zoom without horizontal scrolling.

### Player shell

- A 52 px top bar contains the mark, page title, and a menu button for sign-out/account actions.
- Use a two-item bottom navigation only when both destinations exist: “Today” and “Progress.” Each target is at least 44 × 44 px.
- Respect safe-area insets.
- Page gutter is 20 px; section gap is 32 px.
- Avoid sticky calls to action that cover video captions or reflection controls.

### Today / current evidence

- Greet with the player's first name only if reliably available; otherwise use “Your clips.”
- The active goal is written near the top in one quiet block labeled “What you’re working on.”
- Evidence appears one clip at a time. Do not create a feed with engagement counts.
- The plain judgment label and coach sentence appear before the video so the player knows what to watch for.
- The clip video uses full content width, a 16:9 reserved box, native mobile playback behavior, and captions when audio contains relevant speech.
- Below the clip: match/date metadata and previous/next controls.
- Progress wording is neutral: “2 of 4.” It is navigation, not completion pressure.
- Each clip offers an optional reflection beneath its evidence. The final clip has no special completion pressure, confetti, or streak.

### Reflection

- Label: “What did you notice? (optional)”
- One multiline field, “Save reflection,” and a quiet “Skip for now.”
- Saved confirmation: “Reflection saved.”
- The player can edit or remove their reflection while the related evidence remains available.
- The coach can read the reflection but cannot edit it.

### Progress

- Show past development goals and evidence sets in reverse chronological order.
- Each item contains the goal text, match/date, clip count as ordinary metadata, and the player's reflection when present.
- No charts, percentages, streaks, comparisons, score colors, or “improvement” claims.

## Components

### Buttons

- Primary: action background, white text, 40/44 px height, 8 px radius.
- Secondary: transparent, ink text, line-strong border.
- Tertiary: transparent, ink or muted text, no border.
- Destructive: error text on transparent surface by default; filled only in final destructive confirmation.
- Icon-only controls require a visible tooltip on hover/focus and an accessible name.
- Loading retains width, replaces the leading icon with a spinner, and remains disabled.

### Fields

- Labels remain visible above fields. Placeholder text never substitutes for a label.
- Help text appears below before validation; an error replaces or follows it without shifting unrelated layout.
- Border becomes line-strong on hover and focus; the outer focus ring remains distinct.
- Required fields use text, not color or an asterisk alone.
- Use native input types and autocomplete tokens where applicable.

### Dialogs and sheets

- Use a centered dialog for compact desktop decisions and a bottom sheet only for simple player/mobile actions.
- Trap focus, return focus to the invoker, close with Escape when safe, and label the dialog programmatically.
- Unsaved or destructive work requires explicit confirmation; routine informational dialogs do not.
- Maximum desktop dialog width is 560 px.

### Lists and tables

- Prefer aligned rows with dividers over separate cards.
- Headers stay visible on long coach lists.
- Every row has a meaningful primary link; do not make an inaccessible row-wide click target without semantics.
- Sort state is textual and announced.
- Empty, loading, and error rows preserve the table structure.

### Statuses

- Use a small dot plus text or icon plus text; color never carries the meaning alone.
- Status labels are literal: Uploading, Processing, Ready, Failed, Draft, Preparing clips, Published.
- Avoid “Live” unless a resource is genuinely live.

### Toasts

- Use toasts only for completed background actions whose result is also visible in the page.
- Errors that block a task stay next to the relevant control or in a persistent inline banner.
- Toast duration is at least five seconds, pauseable on hover, and announced politely.

### Skeletons

- Match final geometry and use a subtle flat fill.
- Do not pulse continuously when reduced motion is enabled.
- Do not show a skeleton for an action that failed; show the error.

## Interaction and motion

- Default transition: 140 ms ease-out for color, opacity, and small transforms.
- Dialog enter: 180 ms; exit: 120 ms.
- Do not animate layout during review or shift the video/timeline when saving.
- No parallax, scroll-jacking, animated gradients, count-up metrics, or logo choreography.
- Under `prefers-reduced-motion: reduce`, remove nonessential movement and use instant state changes.
- Progress indicators reflect known bytes or stages; never animate a fake percentage.

## Accessibility contract

- Target WCAG 2.2 AA.
- Text contrast is at least 4.5:1; large text and meaningful non-text controls meet their applicable ratios.
- All mobile interactive targets are at least 44 × 44 px. Desktop targets never fall below the WCAG 24 × 24 px minimum.
- Keyboard focus is a two-pixel focus-color ring with a two-pixel offset and is never removed.
- DOM order follows visual order. Use landmarks, one `h1`, and logical heading levels.
- Video controls, timeline, dialogs, radio groups, tabs, and toasts follow WAI-ARIA Authoring Practices. Prefer native elements before ARIA.
- Provide captions when relevant speech is intentionally included. Never generate inaccurate captions and present them as verified.
- Every state is understandable without color, sound, hover, or animation.
- Support browser zoom to 200% and text spacing overrides without clipped content.

## Responsive and browser QA matrix

Review every changed page at these exact viewports:

| Product | Viewports |
|---|---|
| Player | 320×568, 360×800, 390×844, 430×932, 768×1024 |
| Coach lists/forms | 768×1024, 1024×768, 1280×800, 1440×900 |
| Coach review | 1024×768, 1280×800, 1440×900, 1920×1080 |

Test current stable Chrome, Safari, and Firefox; include iOS Safari for player video and one Android Chrome device. Check keyboard-only and one screen-reader pass on every critical flow.

## Visual quality rules

The implementation is not accepted if it includes:

- gradients, glassmorphism, glow, neon, or frosted layers;
- a generic four-card metric dashboard;
- decorative icons inside every heading;
- excessive rounded containers or fully rounded primary buttons;
- emoji as interface art;
- random shadows or inconsistent radii;
- a giant marketing hero inside the authenticated product;
- fake analytics, example scores, or fabricated player data in production;
- a mark or wordmark approximated from the raster sheet;
- dark mode added by inversion without a separate reviewed palette;
- placeholder lorem ipsum or AI-themed copy.

## Implementation acceptance

For each frontend task, attach to the handoff:

1. screenshots at the relevant matrix sizes;
2. keyboard path and visible-focus confirmation;
3. automated accessibility results plus manual notes;
4. loading, empty, error, offline/interrupted, and success states;
5. measured Web Vitals for the player page and playback timing for video pages;
6. confirmation that no hard-coded colors, unapproved font requests, or unauthorized external scripts were introduced.

Pixel polish does not override product clarity or privacy. If a visual choice makes a player comparison, ranking, or full-match exposure easier, the choice is wrong.
