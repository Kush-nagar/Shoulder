# Player redesign brief

Status: proposal for the build agent. Owner decisions are listed in section 10.
Scope: player routes only (`/player/**`). Coach routes are untouched.
Supersedes, once the owner approves: the "Player mobile experience" shell rules in `docs/09-frontend-design-system.md` (560 px column, two-item bottom bar). Every other rule in `AGENTS.md`, `08-brand.md`, `09-frontend-design-system.md`, `05-ui.md`, and ADR 0021 still holds.

---

## 1. Design read and dials

**Design read:** Operate-mode player app for 13 to 18 year old footballers, used one-thumbed on a phone after training and on a school laptop at a desk, with a calm, editorial-athletic language (a good matchday programme, not a betting app), leaning toward the existing ink / paper / terracotta tokens, Tailwind 4 utilities, Inter Tight, and Server Components with tiny client leaves.

| Dial | Value | Why |
|---|---:|---|
| `DESIGN_VARIANCE` | 5 | Product UI. Asymmetric 8/4 dashboard grid on desktop, strict single column on phone. No artsy offsets. |
| `MOTION_INTENSITY` | 3 | CSS transitions only (140 to 180 ms). No motion library. The video is the moving thing. |
| `VISUAL_DENSITY` | 5 | "Daily app": a full dashboard on first load, but every section keeps one job and room to breathe. |

What is wrong today (from `shots3/`): desktop renders a 512 px phone column in a 1280 px window with the bottom tab bar still at the foot of the screen (a1, a4); the home page has three sections and two are empty on first run (a1, m-home); the AI card is a wall of text with no hierarchy (m-detail); nothing on the page says "football" or "you" except the goal title.

---

## 2. Reference board

| Reference | Borrowed pattern | Avoid | URL |
|---|---|---|---|
| Oura, "Today" tab (Instrument redesign) | One "big thing" at the top, then progressively deeper layers. Maps to our goal hero, then clips, then practice. | Readiness scores, rings, colour-coded health states. | https://ouraring.com/blog/new-oura-app-experience/ , https://www.instrument.com/work/oura-app |
| WHOOP home (2025) | Single scrollable home replaced swipe tabs; each tile is "a doorway, not a destination" (tile shows a headline, tap for depth). Coach entry lives in a fixed corner, not in the feed. | 72 pt score numerals, red/yellow/green judgement colours, strain dials. | https://www.whoop.com/us/en/thelocker/the-all-new-whoop-home-screen/ , https://www.925studios.co/blog/whoop-design-breakdown |
| Nike Run Club plans (COLLINS) | A small, fixed taxonomy of session types each with its own cover treatment. We borrow it for drill focus tags: one quiet typographic cover per tag. | Expressive per-run colour systems (breaks our one-accent rule). | https://www.printmag.com/branding-identity-design/nike-run-club-app-improves-user-experience-with-help-from-collins/ |
| Nike Training Club | Browse-by-focus library: large sentence-case titles, a short meta line (duration, equipment), filter row on top. Direct model for `/player/drills`. | Full-bleed athlete photography, "Let's go" hype copy. | https://www.kristinayao.com/work/nike-training-club-app-feature |
| Strava (2024 nav: Home / Maps / Record / Groups / You) | Four to five labelled bottom tabs with icons; everything personal collected under one "You" place. Our Profile takes the "You" role but sits in the top bar so tabs stay about training. | Kudos, feed, segments, leaderboards. | https://www.bikeradar.com/news/strava-beta-test-layout |
| Veo (player/clip viewing) | Clip markers as small filled circles above the scrub bar; on mobile the menu bar sits at the bottom. Supports our filled/outlined evidence dots. | Heat maps, possession stats. | https://play.google.com/store/apps/details?id=co.veo.veocam |
| Hudl (athlete highlights) | Clip list as short, titled rows with duration and source game; playback on a dark surface separate from the page. | Highlight reels, music, share-to-recruiter pressure. | https://www.hudl.com/support/athletes-guide-to-hudl/guides/highlights |
| Ladder | Coach's short video/note at the top of the day, exercise demo loops beside cue text. We copy "coach voice first, then the thing to do". | Team cheers, streak counters, performance-based plan changes. | https://www.joinladder.com/ |
| Future | Human coach is named and present on every plan card; plan items are compact rows with duration. Supports showing `coach_display_name` next to coach text. | Daily check-in nudges. | https://www.garagegymreviews.com/future-app-review |
| Apple Fitness+ | Library filters by type, duration, equipment; filters are simple chips above a list. | Rings, awards, burn bar (a live comparison). | https://support.apple.com/en-ae/108761 |
| Linear UI redesign | Neutral chrome, darker text in light mode for contrast, sidebar with aligned icon + label rows, one header behaviour per level. Model for our desktop sidebar. | Dense issue-tracker density. | https://linear.app/now/how-we-redesigned-the-linear-ui |
| Vercel dashboard (2026 nav) | Sidebar on desktop, floating bottom bar for one-handed mobile, same destinations in both. Confirms our dual shell. | Hidden/resizable sidebars (unneeded with four destinations). | https://vercel.com/changelog/dashboard-navigation-redesign-rollout |
| Material 3 navigation | Bar below 600 dp, rail at medium widths, drawer/sidebar at expanded. Our breakpoints follow this at 768 / 1024. | Material visual styling. | https://m3.material.io/components/navigation-rail/guidelines |
| Things 3 | Quiet typographic headers, generous whitespace, content not boxes. Model for list sections and the profile page. | Colourful per-list icons. | https://culturedcode.com/things/features/ |
| The Athletic (Metalab) | Editorial hierarchy: one strong headline, a short standfirst, then compact rows; sport vocabulary in plain language. Model for goal hero and coach note. | Dark dramatic palette, scores ticker. | https://www.metalab.com/work/the-athletic |
| Mobbin, health and fitness | Survey of empty states and onboarding cards; checked that our first-run guide is inline, not a modal carousel. | Onboarding carousels, permission walls. | https://mobbin.com/explore/mobile/app-categories/health-fitness |

---

## 3. Visual direction

### 3.1 Palette (evolve, do not discard)

Keep every existing `--sh-*` token and value. Add three tokens, and optionally a reviewed dark palette (owner decision D2).

New light tokens:

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--sh-control-border` | `#8A837B` | Input, select, checkbox borders (WCAG 1.4.11) | 3.56:1 on paper. Current `line-strong` is 1.56:1 and fails for input boundaries. |
| `--sh-night` | `#171512` (same as ink) | Video stage and goal hero surface | Paper text 17.32:1 |
| `--sh-night-muted` | `#B9B2A9` | Secondary text on night surfaces | 8.68:1 on night |
| `--sh-action-on-night` | `#E58B66` | Links/labels on night surfaces | 7.13:1 on night |

Dark palette (separate, reviewed; not an inversion). Apply under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])` and under `:root[data-theme="dark"]`.

| Token | Dark value | Ratio on `#141311` |
|---|---|---:|
| `--sh-paper` | `#141311` | page |
| `--sh-surface` | `#1D1B18` | panel |
| `--sh-surface-subtle` | `#26231F` | hover, skeleton |
| `--sh-ink` | `#F2EFEA` | 16.19 |
| `--sh-ink-2` | `#CDC7BF` | 11.07 |
| `--sh-muted` | `#A29A91` | 6.69 |
| `--sh-line` | `#2F2B27` | divider |
| `--sh-line-strong` | `#45403A` | divider |
| `--sh-control-border` | `#7A736B` | 3.97 |
| `--sh-brand` | `#C4633D` | 4.6 (decorative only) |
| `--sh-action` | `#E58B66` | 7.26; filled buttons use ink-dark text `#141311` on it (7.26) |
| `--sh-action-hover` | `#F0A585` | |
| `--sh-action-soft` | `#3A2219` | ink on it 12.87 |
| `--sh-focus` | `#F0A585` | 9.22 |
| `--sh-error` | `#F08A80` | 7.65 |
| `--sh-error-soft` | `#2A1716` | error on it 7.02 |

Rules: one accent (terracotta family) everywhere. No green success, no red/amber judgement colours. `applied` and `opportunity` differ by label and filled/outlined dot, never by hue. Night surfaces are used for exactly two things: the video stage and the goal hero.

### 3.2 Typography

- Inter Tight stays the UI and body face (installed). Weights 400/500/600 only.
- Optional display face (owner decision D1): `@fontsource-variable/archivo` (SIL OFL, one variable WOFF2 with `wdth` 62 to 125 and `wght`). Use it at `wdth 75, wght 600` for only three roles: page `h1`, goal hero title, drill cover title. It gives the condensed, kit-number, matchday-programme voice that makes the product read as football without pictures. Fallback if declined: Inter Tight 600 with `letter-spacing: -0.02em` in the same slots. Nothing else changes.
- Scale (px, mobile / desktop, line-height):

| Role | Mobile | Desktop | LH | Face |
|---|---:|---:|---:|---|
| Display (home greeting, goal hero title) | 32 | 44 | 1.05 | Display |
| Page title `h1` | 28 | 34 | 1.1 | Display |
| Section title `h2` | 20 | 22 | 1.25 | Inter Tight 600 |
| Card title `h3` | 17 | 17 | 1.35 | Inter Tight 600 |
| Body | 16 | 16 | 1.5 | Inter Tight 400 |
| Label | 14 | 14 | 1.35 | Inter Tight 600 |
| Meta | 13 | 13 | 1.4 | Inter Tight 400, `tabular-nums` |

Player body never drops below 16 px. No all-caps labels. Max three sizes per card.

### 3.3 Spacing, radius, elevation

- 4 px base. Gutter: 16 px at 320 to 374, 20 px at 375 to 767, 32 px at 768+.
- Section gap: 32 px phone, 40 px desktop. Card padding: 16 px phone, 20 to 24 px desktop.
- Radius (documented lock): controls 8, cards/panels 12, video and goal hero 14, filter chips full pill (the only pill use).
- Elevation: none on the page. Borders do grouping (`1px var(--sh-line)`). Only dialogs and the mobile account sheet get `0 16px 48px rgba(23,21,18,.14)`.
- Content widths: dashboard grid max 1200; reading columns (drill detail, profile, upload form) max 680.

### 3.4 Icons

Add `lucide-react` as the single icon dependency (owner decision D3). Justification: bottom tabs and the sidebar need icons with labels for scanability at thumb size; hand-drawn SVG paths are banned by the taste rules; lucide is per-icon tree-shaken, renders in Server Components with no client JS, ISC licensed, and its 2 px stroke on a 24 grid matches the mark's 2.5-unit stroke closely. Phosphor is the taste skill's preference but its RSC path is a separate `/ssr` entry and a heavier default set; either is acceptable, but pick one and never mix.
Pass `strokeWidth={2}` and `size={20}` (nav 22) inline; no wrapper component. Icons always sit beside a text label except the account button (`aria-label="Account"`). The brand mark is never used as an icon.
Icon set used: `House`, `Footprints` (Practice), `ListChecks` (Drills), `Route` (Progress), `CircleUser`, `Upload`, `Play`, `Clock`, `Package` (equipment), `Info`, `Trash2`, `LogOut`, `ChevronRight`, `ArrowLeft`, `Check`. `Sparkles` and any "AI" glyph are banned; label AI with text only.

### 3.5 Motion

- Colour/opacity/border transitions 140 ms ease-out. Tab indicator `scale-x` 180 ms. Sheet/dialog enter 180 ms, exit 120 ms.
- Press feedback: `active:scale-[0.98]` on buttons and tiles.
- Dashboard sections fade in once (opacity 0 to 1, `translateY(6px)` to 0, 200 ms, 40 ms cascade via `--i`), CSS only.
- All of the above inside `@media (prefers-reduced-motion: no-preference)`. Under `reduce`: instant state changes, skeletons static.
- Banned: count-ups, parallax, scroll listeners, looping animations, confetti, progress rings.

---

## 4. App shell

| Width | Navigation | Header |
|---|---|---|
| 320 to 767 | Bottom tab bar, 4 tabs, icon over label, 64 px + `env(safe-area-inset-bottom)`, `fixed` | 56 px top bar: mark (links to `/player`), page title (hidden on Home), account button (avatar initial circle, 44x44) opening a bottom sheet |
| 768 to 1023 | Left rail 88 px, icon over label, `sticky top-0 h-dvh` | 64 px content header: page title left, page primary action right |
| 1024+ | Left sidebar 240 px: wordmark at top, labelled rows (44 px), "Film practice" primary button under the nav, account block at bottom (name, email truncated, chevron to `/player/profile`) | 64 px content header as above |
| 1440+ | Sidebar unchanged; content column caps at 1200 and centres in remaining space | |

Tabs (same order everywhere): Home `/player`, Practice `/player/practice`, Drills `/player/drills`, Progress `/player/progress`. Profile is reached from the account button (phone) or account block (rail/sidebar), never a fifth tab.

Implementation notes:
- `app/player/layout.tsx` renders `<Sidebar/>` (hidden below `md`), `<TopBar/>` (hidden `md+`), `<main>` and `<BottomTabs/>` (hidden `md+`). Only the active-state logic is a client leaf (`usePathname`), as today.
- `main` gets `pb-[calc(64px+env(safe-area-inset-bottom)+24px)] md:pb-12` so the tab bar never covers content.
- Active tab: ink text 600, 2 px `--sh-action` bar (top edge on bottom bar, left edge on rail/sidebar), `aria-current="page"`.
- Account sheet (phone): name, email, "Profile and settings", "Sign out". Native `<dialog>` with focus return.
- Remove the fixed bottom bar at `md+` (today it floats mid-page on desktop, see a4).

---

## 5. Screen specs

Data helpers already in `apps/web/lib/api.ts`: `fetchMe`, `fetchGoals`, `fetchEvidence`, `fetchReflections`. Practice helpers call `/v1/player/practice-videos*`. Every dashboard section is its own async Server Component wrapped in `<Suspense>` with a same-geometry skeleton, so one failing endpoint shows an inline section error, never a blank page.

### 5.1 Home `/player`

Sections in order:
1. Greeting `h1`: "Hi, {first name}." from `Me.display_name` first token when it is not an email address; else "Your training." Meta line under it: today's date (`Thursday 24 September`).
2. Goal hero (night surface, 14 radius, 2 px brand rule on the left edge): label "What you're working on", goal title (Display), description, footer line "Set by {coach_display_name}" when the latest evidence item provides it, else "Set by your coach". Actions: "Watch your clips" (when evidence exists) and "Drills for this goal".
3. Try this today: one drill from the static library matched to the goal, rotated by day of year. Shows title, focus tag, duration, space, "Open drill". Label: "Try this today" (not "challenge").
4. Latest from your coach: newest evidence set. Game label, "{n} clips, shared {date}", then up to 3 clip rows (verdict label, coach sentence clamped to 2 lines, duration `0:12`). Row links to `/player/goals/{goal_id}?publication=...&clip=n`. "Earlier games" disclosure below, as today.
5. Your practice: 3 most recent practice videos as tiles (poster frame, title, date, status: Uploading / Ready / Analysed). "Film practice" and "See all".
6. Training ideas: newest `ai_coach_feedback` across recent videos: label "AI suggestion" (text + outlined chip, never an icon alone), first 2 drill titles with one-line "why", link to the video. Footnote: "Suggestions from software. Your coach's notes come from your coach."
7. Your notes: latest own reflection (text clamped to 3 lines, clip/game it belongs to), "All your notes" to `/player/progress#notes`. Empty: "Notes you write on a clip show up here. They're optional."
8. How Shoulder works (first-run guide): three inline blocks with verbs as headings: "Watch your coach's clips", "Film your own practice", "Pick a drill". Each one sentence and one link. Dismiss button "Hide this guide" (localStorage `sh.guide.hidden`, try/catch; always visible if storage fails). Also reachable from Profile.

First-run state (no evidence, no practice, no reflections): order becomes 1, 2, 8, 3, 5 (as an invitation block), 4 (as the empty message "Your coach adds 3 to 6 clips after a game. They'll show up here."), 7 hidden. The page is still full because 2, 3, and 8 are always populated (goal is seeded in demo; drill and guide are static). No goal: hero reads "Your coach hasn't set a goal yet." and section 3 picks from all drills.

Returning state: order 1 to 7; 8 hidden once dismissed.

Phone wireframe (375):
```
┌───────────────────────────────┐
│ [mark]                   (S)  │ top bar 56
├───────────────────────────────┤
│ Hi, Sam.                      │
│ Thursday 24 September        │
│┌─────────────────────────────┐│
│▌ What you're working on      ││ night
│▌ CHECK YOUR SHOULDER         ││ display
│▌ BEFORE YOU RECEIVE          ││
│▌ Look before the ball comes..││
│▌ Set by Coach Reyes          ││
│▌ [Watch your clips] Drills > ││
│└─────────────────────────────┘│
│ Try this today                │
│ ┌───────────────────────────┐ │
│ │ Scanning · 12 min         │ │
│ │ Two-look receive          │ │
│ │ Half a pitch, 2 cones     │ │
│ │ Open drill >              │ │
│ └───────────────────────────┘ │
│ Latest from your coach        │
│ vs Riverside · 4 clips, Sep 20│
│ You did this.          0:09   │
│ Checked twice before the pass.│
│ ─────────────────────────────│
│ Chance to do this.     0:12   │
│ ...                           │
│ Your practice   [Film practice]│
│ [poster][poster][poster] →    │ scroll-snap row
│ Training ideas  (AI suggestion)│
│ ...                           │
├───────────────────────────────┤
│ Home  Practice  Drills  Progress│ 64 + safe area
└───────────────────────────────┘
```

Desktop wireframe (1280, sidebar 240, grid 12 col, gap 24):
```
┌──────────┬───────────────────────────────────────────────────────┐
│ shoulder │ Hi, Sam.                                              │
│          │ Thursday 24 September                                │
│ ▌Home    │ ┌───────────── goal hero (8) ─────────┐┌─ today (4) ─┐│
│  Practice│ │ What you're working on              ││ Try this    ││
│  Drills  │ │ CHECK YOUR SHOULDER BEFORE YOU      ││ today       ││
│  Progress│ │ RECEIVE                             ││ Two-look    ││
│          │ │ description · Set by Coach Reyes    ││ receive     ││
│[Film     │ │ [Watch your clips] Drills for goal  ││ 12 min      ││
│ practice]│ └─────────────────────────────────────┘└─────────────┘│
│          │ ┌── Latest from your coach (8) ───────┐┌─ notes (4) ─┐│
│          │ │ clip rows x3, Earlier games         ││ last note   ││
│          │ └─────────────────────────────────────┘└─────────────┘│
│          │ ┌── Your practice (8): 3 tiles ───────┐┌─ AI (4) ────┐│
│          │ └─────────────────────────────────────┘└─────────────┘│
│ (S) Sam  │ How Shoulder works (12, 3 inline columns, first run)  │
└──────────┴───────────────────────────────────────────────────────┘
```
768 to 1023: rail + single column in the same order at max 680 wide, practice tiles in a 3-up grid.

States: loading = `loading.tsx` skeleton of hero + 3 section outlines (flat `surface-subtle`). Per-section error: "This section couldn't load. Try again." with a link that reloads the route. Offline: sections from cache are not attempted; show "You're offline. Clips need a connection."

### 5.2 Practice list `/player/practice`

Sections: header "Practice" + primary "Film practice"; privacy line "Only you can see these videos. Each one is removed 90 days after upload."; list grouped by month headings (no counts). Each row/tile: poster, title, date, duration, status. Phone: one column of 72 px rows (poster 96x54 left). Tablet: 2-col tile grid. Desktop: 3-col tile grid (16:9 poster, text below).
Empty: short block "Film a drill, see how you moved, and get training ideas." + "Film practice" + link "Need an idea? Browse drills".
Loading: 6 tile skeletons. Error: inline alert, keep header and button usable.

```
Phone                          Desktop
Practice      [Film practice]  Practice                    [Film practice]
Only you can see these...      Only you can see these videos...
September                      September
[▭] First touch drill  0:18    [ poster ] [ poster ] [ poster ]
    Sep 23 · Analysed          title      title      title
[▭] Wall passes        0:41    date/stat  date/stat  date/stat
```

### 5.3 Upload `/player/practice/new`

Phone: single column. Desktop: form column (7) + "Filming tips" column (5).
Order: `h1` "Film practice"; notice (bordered, not alarming): "Film only yourself. If teammates are in the shot, crop or re-film."; title field with suggestions as buttons that fill it (the four focus names, and `?title=` prefill from a drill); file picker drop region ("Choose video", accepted types, max size); after pick: filename, size, single progress bar with bytes, stage text; after upload: "Uploaded. Open your video" link.
Tips (static): hold the phone sideways; keep your whole body in the frame; 10 to 60 seconds is plenty; film in daylight; no one else in the shot.
Errors keep the chosen file and title; "Upload paused. Choose the same file to continue." when interrupted.

```
Film practice
┌ Film only yourself... ┐
Title [First touch drill      ]
[Scanning][First touch][Passing][Half-turn]
┌ - - - - - - - - - - - - ┐
  Choose video
  MP4 or MOV, up to 200 MB
└ - - - - - - - - - - - - ┘
```

### 5.4 Practice detail `/player/practice/[id]`

Phone order: back link, title (h1), meta (uploaded date; "Removed on {date}"), video stage (night, 14 radius, 16:9 reserved) with pose overlay toggle "Show body lines" (button, `aria-pressed`), "Your movement" panel (status + one primary action), Training ideas (AI card), "What was sent" disclosure, delete.
Desktop: 12-col, video + movement in 7, AI card in 5 (`sticky top-24`), delete at page foot.

AI card structure (fix the wall of text in m-detail):
- Header row: chip "AI suggestion" + "Suggested {date}". One-line explainer: "Suggestions from software, based on how you moved. Your coach's notes come from your coach."
- Intro sentence (max 2 lines, clamp; "Read more" expands).
- Each drill as a collapsible `<details>` (first open): title (h3), "Why it helps" one line, "How to do it" as numbered steps if the text splits cleanly on sentences, else paragraph. Footer link "Film this drill" to `/player/practice/new?title=...`.
- "Ask again" secondary, disabled with text reason when the daily cap is reached: "You've asked for ideas 10 times today. Try again tomorrow." (neutral, it's a limit not a nudge).
- "What was sent" `<details>`: the literal `PracticeFeatures` fields in plain words ("Head turns seen: 9", "Knee bend at lowest: 34 degrees"), labelled "Measurements from this video only. They are not a grade." Never compare with other videos.

States: analysing = stage text "Finding your body position on this device..." with an indeterminate thin bar (static under reduced motion); pose failed = "Couldn't find a clear view of you. Try a video where your whole body is in frame."; video still processing; AI error = "Training ideas didn't load. Try again." Delete: tertiary destructive text button, confirm dialog "Delete this video? It's removed now and can't be recovered."

```
Desktop
← Practice
First touch drill
Uploaded Sep 23 · Removed on Dec 22
┌──────── video 7 ─────────┐ ┌─ AI suggestion ──── 5 ─┐
│                          │ │ Suggestions from ...   │
│                          │ │ ▾ Shoulder check pass  │
└──────────────────────────┘ │   Why: ...             │
[Show body lines]            │   1. ... 2. ...        │
Your movement                │   Film this drill >    │
Done. [Get training ideas]   │ ▸ Direction change     │
▸ What was sent              │ ▸ Coach call           │
                             └────────────────────────┘
Delete this video
```

### 5.5 Progress `/player/progress`

Sections: `h1` "Progress"; goal block (active goal, "Since {created_at}"); "From your coach": evidence grouped by game, reverse chronological, filled dot = "You did this.", outlined dot = "Chance to do this.", text legend above, each dot a 44x44 link; "Practice log": practice videos by month, rows only; "Past goals": closed goals with date range, collapsed; "Your notes" (`id="notes"`): own reflections with edit/delete, withdrawn ones labelled "Clip unavailable".
Desktop: 8/4 split: timeline and practice log left; goal block, legend, past goals right (sticky). Phone: single column in listed order.
No totals, no charts, no per-week counts. Empty: "Clips from your coach and your practice videos will line up here over the season."

### 5.6 Goal detail `/player/goals/[goal_id]`

Keep the existing evidence sequence behaviour and rules (sentence before video, no autoplay, one published revision, preload only next).
Phone order: back, goal title, game label + "2 of 4" navigation, verdict label, coach sentence with coach name, video (16:9, night), prev/next (44 px), reflection field "What did you notice? (optional)", "Save note" + "Skip for now".
Desktop: game switcher row on top; left 7: video + prev/next; right 5: verdict, sentence, coach name, reflection. Below the video: clip strip of the set as numbered 44 px buttons with filled/outlined dots (navigation only).

### 5.7 Drills library `/player/drills` (new) and `/player/drills/[slug]` (new)

Source: `apps/web/content/drills.ts` (typed array, section 8). Pure Server Components; filtering via `?focus=` search param and `<Link>` chips (no client JS).
List order: `h1` "Drills"; one line "Written by coaches for players 13 to 18. Pick one, film it, see how you moved."; "For your goal" row (drills whose `goalKeywords` match the active goal title/description, case-insensitive; hidden if none); focus chips (All, Scanning, First touch, Receiving on the half-turn, Passing, Ball mastery, 1v1, Both feet, Defending); drill grid.
Drill tile ("cover", NRC-style): 12 radius, `surface` with a 3 px top rule in `--sh-brand` for "For your goal" tiles only; focus tag (label), title (Display face at 22), duration + space + equipment meta with icons. Phone: 1 col. Tablet: 2 col. Desktop: 3 col, first "For your goal" tile spans 2 cols with the "why" line visible (rhythm, not three identical cards).
Detail order: back, focus tag, title, meta row (duration, space, equipment), "Why it helps", "How to do it" (`<ol>`), "Make it harder" (one line, optional), primary "Film this drill" (`/player/practice/new?title={title}`), "More {focus} drills" (3 rows). Reading column 680.
Empty filter result: "No drills with that focus yet." + "Show all".

### 5.8 Profile and settings `/player/profile` (new)

Reading column 680, sections separated by `border-t`, no cards.
1. Account: display name, email (`/v1/me`). "Sign out" (existing `sign-out-form`).
2. Appearance (only if D2 approved): radio group System / Light / Dark; sets `data-theme` on `<html>` and a `sh-theme` cookie so SSR renders the right theme without flash.
3. How your data is used (static, matches ADR 0021):
   - "Your coach's clips are cut from team game video. You only ever see your own clips."
   - "Practice videos are yours. Your coach can't see them. Each one is deleted 90 days after upload."
   - "Body position is worked out on this device. Only a short summary of angles and head turns is sent when you ask for training ideas."
   - "Training ideas are AI suggestions, stored with the video. They are never shown to your coach or added to your coach's clips."
   - "Notes you write on clips are read by your coach. Only you can change or delete them."
4. Delete something: "A practice video: open it and choose Delete this video. It's removed straight away." / "A note: go to Progress, Your notes, and delete it." / "A coach clip or your whole account: ask your coach. They can remove clips and start account deletion."
5. Help: "How Shoulder works" (re-opens the guide on Home by clearing the flag), "Filming tips" (anchor to upload tips).

States: `/v1/me` failure shows "Your account details didn't load." but keeps sign out and all static sections usable.

---

## 6. Dashboard feature list

| Feature | Data source | Backend work |
|---|---|---|
| Greeting with first name | `GET /v1/me` (`display_name`) | None |
| Goal hero + description | `GET /v1/players/{player_id}/goals` (`fetchGoals`), active one | None |
| "Set by {coach}" | `EvidenceItem.coach_display_name` from `GET /v1/me/goals/{goal_id}/evidence`; fallback "your coach" | None (optional later: coach name on `Goal`) |
| Latest coach clips (3 rows) + earlier games | `GET /v1/me/goals/{goal_id}/evidence` | None |
| Try this today (goal-matched drill) | Static content in repo (`content/drills.ts`), day-of-year rotation | None |
| Drills for your goal / library | Static content in repo | None |
| Recent practice with posters | `GET /v1/player/practice-videos` (list), then `GET /v1/player/practice-videos/{id}` for the top 3 only to get `playback_url`; poster via `<video preload="metadata" muted playsinline src="{url}#t=0.5">` client leaf with a typographic fallback tile | None. Better later: server poster frame (backend) |
| Latest training ideas | `GET /v1/player/practice-videos/{id}/ai-feedback` for the newest `Analysed` video | None |
| Your notes | `GET /v1/me/reflections` (`fetchReflections`) | None |
| How Shoulder works guide | Static, dismiss flag in localStorage | None |
| Filming tips | Static | None |

Explicitly not built: streaks, "days active", clip counters as totals, watched/unwatched badges, reminders, "you haven't reflected" prompts, percentages, charts of features across videos.

---

## 7. Copy guidelines

- Voice: a good youth coach talking to one player after training. Short, concrete, second person, football words ("first touch", "check your shoulder", "half-turn", "switch play").
- Sentence case. Full stops only in full sentences. No exclamation marks, emoji, or hype.
- Say what happened and the next action. Never praise or grade ("great", "strong", "needs work").
- AI text is always introduced with the label "AI suggestion" and never phrased as the coach.
- Banned (grep before merge): failed, weak, incorrect, performance score, insights, unlock, level up, elite, AI-powered, streak, badge, rank, score (as a noun for the player), percent, "Oops", "magic", em dash character.

Ten example strings:
1. "What you're working on"
2. "Your coach adds 3 to 6 clips after a game. They'll show up here."
3. "Try this today"
4. "Film only yourself. If teammates are in the shot, crop or re-film."
5. "Suggestions from software, based on how you moved. Your coach's notes come from your coach."
6. "What did you notice? (optional)"
7. "Note saved."
8. "This section couldn't load. Try again."
9. "Delete this video? It's removed now and can't be recovered."
10. "Measurements from this video only. They are not a grade."

---

## 8. Drill library seed (static content)

Shape: `{ slug, title, focus, goalKeywords: string[], why, steps: string[], space, equipment, minutes, harder }`.

1. **Two-look receive** (slug `two-look-receive`, focus Scanning, keywords shoulder/scan/look/check)
   Why: Looking twice before the ball arrives tells you where the space is before you need it.
   Steps: 1) A partner passes from 10 m. 2) A second partner stands behind you and holds up 1 to 3 fingers. 3) Look over your shoulder once as the pass is played and once just before it arrives. 4) Call the number out loud, then take your touch away from the side your partner stands on. 5) Swap roles every 8 passes.
   Space: 15 x 10 m. Equipment: 1 ball, 2 cones. Time: 12 min. Harder: partner moves side to side after the pass.

2. **Gate scan** (`gate-scan`, Scanning, shoulder/scan/look)
   Why: Builds the habit of checking which way is open before you receive.
   Steps: 1) Set two cone gates 5 m behind you, left and right. 2) A partner stands behind you and steps into one gate as the pass comes. 3) Check your shoulder, then turn through the gate your partner is not in. 4) Dribble through and pass back. 5) Ten turns, rest, repeat.
   Space: 15 x 15 m. Equipment: 1 ball, 6 cones. Time: 10 min. Harder: receive with your back fully to the gates.

3. **Wall first touch** (`wall-first-touch`, First touch, touch/control/receive)
   Why: A clean first touch into space gives you time for the next action.
   Steps: 1) Stand 5 m from a wall. 2) Pass with your right foot, cushion with your left, pass again. 3) Next set, take the touch across your body into a cone gate 1 m to the side. 4) Swap feet. 5) Step back to 8 m and use firmer passes.
   Space: a wall and 8 m in front. Equipment: 1 ball, 2 cones. Time: 10 min. Harder: receive on the half-volley.

4. **Open body angle** (`open-body-angle`, Receiving on the half-turn, half-turn/turn/body/receive)
   Why: Standing side-on lets you see more of the pitch and play forward in one touch.
   Steps: 1) A partner passes from the side. 2) Stand side-on, back foot pointing where you want to go. 3) Receive on your back foot and play forward to a target cone gate. 4) Change sides every 6 passes. 5) Film one set side-on to check your angle.
   Space: 20 x 10 m. Equipment: 1 ball, 4 cones. Time: 12 min. Harder: add a passive defender who steps in from behind.

5. **Half-turn under pressure** (`half-turn-pressure`, Receiving on the half-turn, half-turn/turn/pressure)
   Why: Game passes arrive with a defender close; practising the half-turn with pressure makes it usable.
   Steps: 1) Play in threes: server, you, defender behind you. 2) Check your shoulder as the pass is played. 3) If the defender is tight, set the ball back. If they are off, half-turn and dribble to the far line. 4) Defender goes at half pace to start. 5) Rotate after 6 balls.
   Space: 20 x 15 m. Equipment: 1 ball, 4 cones, bib. Time: 15 min. Harder: defender at full pace.

6. **Triangle passing with a look** (`triangle-look`, Passing, pass/scan/tempo)
   Why: Passing sharply while checking around you keeps the ball moving in games.
   Steps: 1) Three players in a triangle 10 m apart. 2) Pass and follow your pass to the next cone. 3) Before each receive, glance away from the ball once. 4) Two touches, then one touch. 5) Change direction every 2 minutes.
   Space: 10 m triangle. Equipment: 1 ball, 3 cones. Time: 12 min. Harder: add a second ball.

7. **Switch the play** (`switch-the-play`, Passing, switch/long/pass/vision)
   Why: A good switch moves the whole game and needs a look before the ball arrives.
   Steps: 1) Two partners 25 m apart on opposite sides. 2) Receive from one, open your body, and pass long to the other. 3) Look to the target side before the first pass reaches you. 4) Aim to land it in front of your partner, not at them. 5) Rotate positions each set.
   Space: 30 x 20 m. Equipment: 1 ball, 4 cones. Time: 15 min. Harder: two-touch maximum.

8. **Box ball mastery** (`box-ball-mastery`, Ball mastery, touch/close control/dribble)
   Why: Many small touches build the close control you need in tight spaces.
   Steps: 1) Mark a 3 m box. 2) 30 seconds each: sole rolls, inside-outside touches, pull-backs, drag-and-push. 3) Keep your head up between touches and look at a cone outside the box. 4) Rest 30 seconds between patterns. 5) Two rounds.
   Space: 3 x 3 m. Equipment: 1 ball, 4 cones. Time: 10 min. Harder: a partner calls a colour and you touch that cone.

9. **1v1 to a gate** (`one-v-one-gate`, 1v1, dribble/beat/1v1/attack)
   Why: Attacking a defender at speed and choosing a side is a skill you only build by doing it.
   Steps: 1) Attacker and defender 15 m apart, two gates behind the defender. 2) Defender passes to the attacker to start. 3) Attacker drives at the defender and dribbles through either gate. 4) Defender tries to win the ball or push the attacker wide. 5) Swap roles after each go.
   Space: 20 x 15 m. Equipment: 1 ball, 6 cones. Time: 15 min. Harder: attacker must check their shoulder before the first touch.

10. **Other-foot wall work** (`other-foot-wall`, Both feet, other foot/left/right/both feet)
    Why: Being able to use both feet means defenders can't show you one way.
    Steps: 1) Stand 6 m from a wall. 2) Use only the foot you use less: 20 inside-foot passes. 3) Then 20 laces passes. 4) Then receive with that foot and pass with it. 5) Finish with 10 one-touch passes.
    Space: a wall and 10 m. Equipment: 1 ball. Time: 12 min. Harder: step back to 10 m.

11. **Jockey and show wide** (`jockey-show-wide`, Defending, defend/press/1v1/tackle)
    Why: Staying on your feet and guiding the attacker away from goal wins more balls than diving in.
    Steps: 1) Channel 8 m wide and 20 m long. 2) Attacker dribbles toward your end line. 3) Get side-on, knees bent, and steer them toward one touchline. 4) Only tackle when their touch goes too far. 5) Swap after each go.
    Space: 20 x 8 m. Equipment: 1 ball, 4 cones. Time: 12 min. Harder: attacker can pass to a partner at the end line.

12. **Talk and receive** (`talk-and-receive`, Scanning, communicate/talk/scan/awareness)
    Why: Calling "man on" or "time" helps teammates, and listening for it helps you choose your touch.
    Steps: 1) Groups of three: passer, receiver, caller behind the receiver. 2) Caller shouts "time" or "man on" as the pass is played. 3) On "time", turn and play forward. On "man on", set it back first time. 4) Receiver also checks their shoulder to confirm the call. 5) Rotate every 8 passes.
    Space: 15 x 10 m. Equipment: 1 ball, 2 cones. Time: 12 min. Harder: caller sometimes stays silent and the receiver decides alone.

Chip-to-focus map: Scanning (1, 2, 12), First touch (3), Receiving on the half-turn (4, 5), Passing (6, 7), Ball mastery (8), 1v1 (9), Both feet (10), Defending (11).

---

## 9. Acceptance checklist (build agent must attach evidence)

Responsive
- [ ] Screenshots of Home (first-run and returning), Practice, Upload, Practice detail, Progress, Goal detail, Drills, Drill detail, Profile at 320, 375, 768, 1024, 1440 widths.
- [ ] Bottom tabs only below 768; rail 768 to 1023; sidebar 1024+. No bottom bar visible on desktop.
- [ ] No horizontal page scroll at any width, including 320 and at 200% zoom (only the practice scroll-snap row scrolls, inside its own container with visible overflow cue).
- [ ] `min-h-dvh`, never `h-screen`. Safe-area insets on the tab bar and top bar.

Accessibility
- [ ] One `h1` per page, logical heading order, landmarks (`nav` labelled "Player navigation", `main`).
- [ ] All touch targets 44x44 px minimum on player routes, including dots, chips, prev/next.
- [ ] Focus ring 2 px `--sh-focus`, 2 px offset, visible on every control, in both themes if D2 ships.
- [ ] Text contrast 4.5:1, input borders 3:1 (`--sh-control-border`). Verified in light and (if shipped) dark.
- [ ] Verdict meaning never carried by colour alone (label + filled/outlined dot).
- [ ] Axe run clean on every player route; one keyboard-only pass and one VoiceOver or NVDA pass on Home, Goal detail, Practice detail.

Motion and performance
- [ ] Every transition inside `prefers-reduced-motion: no-preference`; with reduce on, nothing moves.
- [ ] No motion library added; no scroll listeners.
- [ ] Home LCP under 2.5 s on throttled 4G; sections stream with Suspense; no layout shift when sections resolve (skeletons match geometry).
- [ ] No third-party scripts or analytics on player routes. Fonts self-hosted.

Product rules
- [ ] `grep -riE "failed|weak|incorrect|performance score|insight|unlock|level up|elite|ai-powered|streak|badge|rank|percent|oops|—"` over changed player files returns nothing user-visible.
- [ ] No totals, trends, charts, scores, or cross-video comparisons of practice features.
- [ ] AI text always labelled "AI suggestion" and visually separate from coach text.
- [ ] Reflections optional everywhere; no reminder or count of unreflected clips.
- [ ] No hard-coded hex in components; all colours via `--sh-*` tokens. Radius lock followed (8 / 12 / 14 / pill chips only).
- [ ] Generated OpenAPI types only; no hand-written API types.
- [ ] Existing Playwright player suites pass unchanged (load-bearing test 1 and 3 untouched).

---

## 10. Owner decisions

- **D1 Display face:** add `@fontsource-variable/archivo` for display roles only (recommended), or stay Inter Tight only. Changes `08-brand.md` typography section either way it is approved.
- **D2 Dark mode:** ship the reviewed dark palette with a System/Light/Dark setting (recommended; players use phones at night), or light only for now.
- **D3 Icons:** approve `lucide-react` as the one icon dependency (recommended) or Phosphor.
- **D4 Shell change:** approve replacing the 560 px player column and two-tab bar in `09-frontend-design-system.md` with the responsive shell in section 4 (record as a short ADR).
- **D5 Practice posters:** accept 3 extra detail calls (3 short-lived signed URLs) per Home load for poster frames, or show typographic tiles until a server-side poster frame exists.

---

## Motion & loading, 2026-09-25

Owner follow-up to the shipped redesign, recorded in
[ADR 0024](../decisions/0024-app-shell-motion-and-streaming.md). Applies to the
player, coaching and coach shells. Patterns adopted:

| # | Pattern | Where it lands | Source |
|---|---|---|---|
| 1 | Collapsible sidebar with a one-key toggle (`[`), state remembered | `sh-sidebar` cookie, server-rendered, no flash; `[` outside text fields | https://linear.app/changelog/unpublished-collapsible-sidebar , https://x.com/linear/status/1613682657719877632 |
| 2 | Dimmer, quieter navigation chrome so content leads; icon + label rows aligned on one grid | 44 px sidebar rows, icon-only rail with tooltips, brand icon on section heads | https://linear.app/now/how-we-redesigned-the-linear-ui |
| 3 | Sidebar that can be hidden on desktop; one-handed bottom bar on phones with the same destinations | Collapse to a 76 px rail; phone tabs unchanged | https://vercel.com/changelog/dashboard-navigation-redesign-rollout |
| 4 | Modal expanded navigation rail: opens over content with a scrim and does not move the layout grid | 768 to 1023 px rail expands as an overlay; Escape or scrim closes | https://m3.material.io/components/navigation-rail/guidelines |
| 5 | Adaptable sidebar that collapses and expands in place, as on iPadOS | One toggle, width animates via `grid-template-columns` | https://developer.apple.com/videos/play/wwdc2024/10147/ |
| 6 | Skeletons that match the final layout and reserve its space; a slow, steady wave reads as shorter than a pulse; no spinners | `loading.tsx` per segment and `<Suspense>` fallbacks on Home, one 1.6 s shimmer, static under reduced motion | https://blog.logrocket.com/ux-design/skeleton-loading-screen-design/ |
| 7 | Same-document View Transitions: snapshot old and new state, animate with CSS; progressive enhancement | Content region fades up on navigation; shell and root do not animate | https://developer.chrome.com/docs/web-platform/view-transitions/same-document |
| 8 | React `<ViewTransition>` in the App Router, `default="none"` so Suspense reveals and refreshes do not animate | `PageTransition` keyed by pathname in both shells | https://github.com/vercel/next.js/blob/canary/docs/01-app/02-guides/view-transitions.mdx |
| 9 | Shared-element morph for the active tab marker (named view transition) | `sh-nav-marker`, `sh-tab-marker`, `sh-section-marker` glide between tabs | https://developer.chrome.com/blog/view-transitions-in-2025 |

Rules kept: one accent, no gradients for decoration, no emoji, no badges,
streaks, nudges or scores. Changed from section 3.5: skeleton shimmer is the
single allowed loop (loading placeholders only), and rail items may be
icon-only when they carry an accessible name and a tooltip.
