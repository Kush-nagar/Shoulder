// Self-hosts the MediaPipe wasm runtime from the pinned package, so no CDN is
// contacted and the files always match the installed version. SIMD build only:
// every browser that can run the rest of the app supports wasm SIMD.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = join(web, "node_modules/@mediapipe/tasks-vision/wasm");
const to = join(web, "public/mediapipe");
mkdirSync(to, { recursive: true });
for (const file of ["vision_wasm_internal.js", "vision_wasm_internal.wasm"]) {
  copyFileSync(join(from, file), join(to, file));
}
