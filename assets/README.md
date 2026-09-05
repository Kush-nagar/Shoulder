# Brand asset workspace

The PNG is reference artwork only. Task 1 uses the two owner-approved vector
sources in `brand/`, as authorized in ADR 0012. Other production variants in
`docs/08-brand.md` remain required before their placements ship.

| Input | Status |
|---|---|
| Raster reference | Present: `shoulder-icon-system.png`; not production artwork |
| Task 1 mark | Present and validated: `brand/shoulder-mark.svg`, viewBox 0 0 24 24 |
| Task 1 wordmark/lockup | Present and validated: `brand/shoulder-wordmark.svg`, viewBox 0 0 70 24 |
| Additional color/placement variants and raster derivatives | Deferred until their placements; retain approval and visual verification requirements |

The SVGs contain currentColor vector paths, no embedded raster, script, external
resource, or metadata. `apps/web/components/brand.tsx` reproduces their paths and
transforms as inline React SVGs; ordinary img tags are not used for theme colors.
The supplied `brand/svg-source.md` describes the export history; the actual
checked-in SVGs already have no C2PA metadata. Do not trace or redraw the PNG.

## Installed Task 1 font

- Package: `@fontsource-variable/inter-tight`.
- Exact resolved version: **5.3.0**, installed during Task 1.
- Pin: `apps/web/package.json` and root `pnpm-lock.yaml`; no version range.
- Provenance: npm registry package, with tarball integrity in the lockfile.
- Source WOFF2: `apps/web/node_modules/@fontsource-variable/inter-tight/files/inter-tight-latin-wght-normal.woff2`.
- Loader: `apps/web/app/layout.tsx`, using `next/font/local`, normal style, weights 400–600.
- Delivery: same-origin Next.js static WOFF2 output; no runtime Google Fonts request.
- Included SIL Open Font License: preserved verbatim from the package's `LICENSE`
  at `apps/web/public/licenses/inter-tight-OFL.txt`, shipped at
  `/licenses/inter-tight-OFL.txt`.
- Verification: frozen lockfile install, package-version/license equality tests,
  production build, and Chromium/Firefox/WebKit network/font checks.

Inter Tight, weights 400/500/600, tabular numeral requirements, and the approved
visual specification remain unchanged. No external font service is needed.
Any upgrade must update the exact pins and this record, preserve the included
license, and rerun font/network checks.
