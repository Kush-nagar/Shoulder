# 08 — Brand system

## Brand idea

Shoulder is the quiet space beside a player where evidence becomes useful coaching. It should feel calm, exact, humane, and trustworthy—not loud, gamified, clinical, or futuristic.

The visual identity is built from an offset bracket mark: two structured forms that create room between them. The mark suggests support and focus without using a literal shield, ball, player silhouette, trophy, or AI symbol.

## Supplied master artwork

The uploaded `assets/shoulder-icon-system.png` is a reference sheet, not the production source for every placement. It defines:

- the offset bracket symbol;
- the custom lowercase `shoulder` wordmark;
- horizontal and vertical lockups;
- 24 × 24 icon construction;
- 2.5-unit stroke;
- 5-unit outer radius;
- 3.5-unit vertical offset;
- light, dark, terracotta, favicon, and app-icon examples.

The custom wordmark is fixed artwork. Do not re-create it by typing “shoulder” in Inter Tight or another font.

## Required production asset pack

Before Task 1 starts, the owner must supply/approve the original vector source and every SVG variant listed below, plus local Inter Tight files covering weights 400/500/600 with license text, exact version, and provenance. Record receipt and usage approval in `assets/README.md` and `STATUS.md`. These inputs are currently absent. Raster derivatives listed below may be exported during frontend implementation from those approved vectors; they are required before their placements ship. Do not auto-trace the raster sheet and call it final.

| Asset | Format | Color/background | Use |
|---|---|---|---|
| `mark-ink.svg` | SVG | ink, transparent | Default header and document mark |
| `mark-paper.svg` | SVG | paper, transparent | Dark surfaces |
| `mark-terracotta.svg` | SVG | brand accent, transparent | Decorative/launch use only |
| `wordmark-ink.svg` | SVG | ink, transparent | Wide product header |
| `wordmark-paper.svg` | SVG | paper, transparent | Dark surfaces |
| `lockup-horizontal-ink.svg` | SVG | ink, transparent | Sign-in and communications |
| `lockup-horizontal-paper.svg` | SVG | paper, transparent | Dark surfaces |
| `lockup-vertical-ink.svg` | SVG | ink, transparent | Documents and selected marketing |
| `favicon.svg` | SVG | ink mark on paper | Modern browsers |
| `favicon-32.png` | PNG | ink mark on paper | Fallback |
| `apple-touch-icon.png` | 180 × 180 PNG | paper mark on ink | iOS |
| `pwa-192.png` | PNG | paper mark on ink | Installed web app |
| `pwa-512.png` | PNG | paper mark on ink | Installed web app |
| `og-default.png` | 1200 × 630 PNG | approved lockup | Private-link preview if enabled |

SVG files must use a tight `viewBox`, expanded or approved strokes, no embedded raster, no font dependency, and no editor metadata. Run SVG optimization and visually compare it with the master.

## Logo rules

- Default to the wordmark on wide sign-in and desktop-header placements.
- Use the mark alone at 24–32 px in the coach rail and as the mobile home link.
- Maintain clear space at least equal to the mark's stroke-offset gap on all sides.
- Do not render the mark below 20 px.
- Use only ink, paper, or brand terracotta versions.
- Keep the exact bracket offset and corner geometry.
- Never rotate, skew, outline, add a container, add a shadow, recolor each bracket separately, or animate the pieces apart.
- The symbol is not a generic UI icon and does not replace play, add, back, or status icons.
- Do not put the terracotta mark on the darker action-terracotta background.

## Color character

The brand uses warm near-neutrals rather than cold dashboard gray. Ink carries authority, paper creates quiet, and terracotta points to human attention.

The supplied terracotta (`#C4633D`) remains the brand accent for marks, rules, small dots, focus moments, and non-text decoration. It does not have enough contrast for normal-sized text on the paper background or for white normal text on a filled control. The interface therefore uses a darker action terracotta (`#9E472C`) where contrast is required. Exact UI tokens and ratios live in `09-frontend-design-system.md`.

Do not add a team-color theme in the MVP. Team kits and opponent colors appear only inside match footage.

## Typography character

Inter Tight is the interface and editorial family. It has compact proportions without feeling mechanical. Use supplied or self-hosted variable-font files through `next/font`; do not make a third-party font request from the browser.

- Wordmark: custom vector artwork only.
- Product UI: Inter Tight.
- Timecodes and dense identifiers: Inter Tight with tabular numerals.
- Long technical/code examples in internal docs only: a system monospace stack.
- Maximum visible weight: 600. Avoid black/extrabold display text.

## Voice

Write like a thoughtful coach who has watched the moment: brief, concrete, and uninflated.

| Prefer | Avoid |
|---|---|
| “Mark moment” | “Capture an insight” |
| “Publish 4 clips” | “Unlock the player's report” |
| “You did this.” | “Elite execution” |
| “Chance to do this.” | “Failed action” |
| “Add a reflection (optional)” | “Complete your reflection” |
| “Video is still processing.” | “Our AI is working its magic.” |
| “Try again” | “Oops!” |

Sentence case is the default. Use punctuation in complete sentences, not in short labels. Do not use emoji, exclamation marks, hype, sports clichés, or artificial urgency.

## Photography and illustration

The authenticated product does not need stock photography or decorative illustration. The match video is the visual material. Sign-in may use the mark, one concise explanation, and a restrained crop or still only when the team has rights and consent.

Do not use AI-generated athlete imagery, faceless 3D characters, stadium hero images, trophy graphics, tactical-board wallpaper, confetti, or abstract “AI network” art.

## Brand acceptance checklist

- The logo shown in the UI comes from approved vector artwork.
- The wordmark is not approximated with a font.
- Ink and paper remain the dominant colors.
- Terracotta is a precise attention signal, not a page wash.
- The interface contains no gradients, gloss, glow, glass, neon, or oversized shadows.
- Copy describes the coach's action or the player's evidence without claiming intelligence or improvement.
- Light and dark logo variants pass a visual check at actual size and on high-density screens.
