# Clean SVG source

The two `.svg` files in this folder carry a **C2PA provenance manifest** that this
platform injects into every SVG it writes — a `<metadata><c2pa:manifest>…` base64 block
plus an `xmlns:c2pa="http://c2pa.org/manifest"` attribute on the root element. It is not
artwork, it cannot be removed at save time here, and it is 85–95% of each file's bytes.

It is inert (no rendering effect, no network request — the c2pa URL is an XML namespace
identifier, not a fetched resource), but for a favicon or an inlined icon you want it
gone. Two ways:

1. Copy the source below into your repo by hand — it is byte-identical to the artwork in
   the shipped files, with no metadata.
2. Or run `svgo` / `scour`, or delete the `<metadata>` element and the `xmlns:c2pa`
   attribute in any editor.

---

## `shoulder-mark.svg` — viewBox `0 0 24 24`

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="currentColor" role="img" aria-labelledby="shoulder-mark-title">
  <title id="shoulder-mark-title">Shoulder</title>
  <path d="M9.75 3.5H5.75A1.25 1.25 0 0 0 4.5 4.75V13.25A1.25 1.25 0 0 0 5.75 14.5H9.75V12H7V6H9.75Z M14.25 9.5H18.25A1.25 1.25 0 0 1 19.5 10.75V19.25A1.25 1.25 0 0 1 18.25 20.5H14.25V18H17V12H14.25Z"/>
</svg>
```

## `shoulder-wordmark.svg` — viewBox `0 0 70 24`

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 70 24" width="70" height="24" role="img" aria-labelledby="shoulder-lockup-title">
  <title id="shoulder-lockup-title">Shoulder</title>
  <path d="M9.75 3.5H5.75A1.25 1.25 0 0 0 4.5 4.75V13.25A1.25 1.25 0 0 0 5.75 14.5H9.75V12H7V6H9.75Z M14.25 9.5H18.25A1.25 1.25 0 0 1 19.5 10.75V19.25A1.25 1.25 0 0 1 18.25 20.5H14.25V18H17V12H14.25Z" fill="currentColor"/>
  <g transform="translate(28.5 9.52) scale(0.0437)" fill="none" stroke="currentColor" stroke-width="25" stroke-linecap="butt" stroke-linejoin="round">
    <path d="M87.5 66.5A14 14 0 0 0 73.5 52.5H26.5A14 14 0 0 0 12.5 66.5V76A14 14 0 0 0 26.5 90H73.5A14 14 0 0 1 87.5 104V113.5A14 14 0 0 1 73.5 127.5H26.5A14 14 0 0 1 12.5 113.5" transform="translate(0 0)"/>
    <path d="M12.5 3V140M12.5 68.5A16 16 0 0 1 28.5 52.5H71.5A16 16 0 0 1 87.5 68.5V140" transform="translate(121 0)"/>
    <path d="M28.5 52.5H77.5A16 16 0 0 1 93.5 68.5V111.5A16 16 0 0 1 77.5 127.5H28.5A16 16 0 0 1 12.5 111.5V68.5A16 16 0 0 1 28.5 52.5Z" transform="translate(242 0)"/>
    <path d="M12.5 40V111.5A16 16 0 0 0 28.5 127.5H71.5A16 16 0 0 0 87.5 111.5V40" transform="translate(369 0)"/>
    <path d="M12.5 3V140" transform="translate(490 0)"/>
    <path d="M93.5 3V140M93.5 68.5A16 16 0 0 0 77.5 52.5H28.5A16 16 0 0 0 12.5 68.5V111.5A16 16 0 0 0 28.5 127.5H77.5A16 16 0 0 0 93.5 111.5" transform="translate(536 0)"/>
    <path d="M87.5 90H12.5V68.5A16 16 0 0 1 28.5 52.5H71.5A16 16 0 0 1 87.5 68.5V90M12.5 90V111.5A16 16 0 0 0 28.5 127.5H71.5A16 16 0 0 0 87.5 111.5" transform="translate(663 0)"/>
    <path d="M12.5 40V140M12.5 68.5A16 16 0 0 1 28.5 52.5H50" transform="translate(784 0)"/>
  </g>
</svg>
```
