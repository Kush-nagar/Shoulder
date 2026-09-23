"use client";

// On-device pose via @mediapipe/tasks-vision (ADR 0021): the browser cannot
// estimate pose natively, and landmarks must never leave the device.
// Model and wasm are self-hosted (public/models, public/mediapipe).
import { createAccumulator, type PracticeFeatures } from "./features";

export type { PracticeFeatures } from "./features";

const MAX_FPS = 15;
const MAX_FRAMES = 1800; // ponytail: caps seek count; long clips sample sparser.
const MAX_SECONDS = 600;
const MODEL = "/models/pose_landmarker_lite.task";
const WASM = {
  wasmLoaderPath: "/mediapipe/vision_wasm_internal.js",
  wasmBinaryPath: "/mediapipe/vision_wasm_internal.wasm",
};

function once(video: HTMLVideoElement, event: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const ok = () => {
      video.removeEventListener("error", fail);
      resolve();
    };
    const fail = () => {
      video.removeEventListener(event, ok);
      reject(new Error("Video could not be read."));
    };
    video.addEventListener(event, ok, { once: true });
    video.addEventListener("error", fail, { once: true });
  });
}

async function seek(video: HTMLVideoElement, t: number): Promise<void> {
  const done = once(video, "seeked");
  video.currentTime = t;
  await done;
}

/**
 * Samples the video, optionally draws the skeleton on `canvas`, and returns
 * only aggregate features. Landmarks stay inside this function.
 */
export async function analyzePractice(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement | null,
  onProgress?: (fraction: number) => void,
): Promise<PracticeFeatures> {
  if (video.readyState < HTMLMediaElement.HAVE_METADATA) {
    await once(video, "loadedmetadata");
  }
  const seconds = Math.min(video.duration, MAX_SECONDS);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    throw new Error("Video has no readable duration.");
  }
  const { PoseLandmarker, DrawingUtils } = await import(
    "@mediapipe/tasks-vision"
  );
  const options = (delegate: "GPU" | "CPU") => ({
    baseOptions: { modelAssetPath: MODEL, delegate },
    runningMode: "VIDEO" as const,
    numPoses: 1,
  });
  const landmarker = await PoseLandmarker.createFromOptions(
    WASM,
    options("GPU"),
  ).catch(() => PoseLandmarker.createFromOptions(WASM, options("CPU")));

  const ctx = canvas?.getContext("2d") ?? null;
  if (canvas && ctx) {
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
  }
  const draw = ctx ? new DrawingUtils(ctx) : null;
  const acc = createAccumulator(
    video.videoHeight > 0 ? video.videoWidth / video.videoHeight : 1,
  );
  const fps = Math.min(MAX_FPS, MAX_FRAMES / seconds);
  const total = Math.max(1, Math.floor(seconds * fps));
  const wasPaused = video.paused;
  video.pause();
  try {
    for (let i = 0; i < total; i++) {
      const t = i / fps;
      await seek(video, t);
      // VIDEO mode needs strictly increasing timestamps; steps are >= 66 ms.
      const result = landmarker.detectForVideo(video, Math.round(t * 1000));
      const pose = result.landmarks[0] ?? null;
      acc.add(pose);
      if (draw && ctx && canvas) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (pose) {
          draw.drawConnectors(pose, PoseLandmarker.POSE_CONNECTIONS, {
            color: "#ffffff",
            lineWidth: 3,
          });
          draw.drawLandmarks(pose, { color: "#22c55e", radius: 3 });
        }
      }
      onProgress?.((i + 1) / total);
    }
  } finally {
    landmarker.close();
    if (!wasPaused) void video.play().catch(() => {});
  }
  return acc.finish(seconds * 1000, fps);
}
