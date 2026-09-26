import type { MetadataRoute } from "next";

// Installable shell only. No service worker: practice video and clips are
// never cached on the device beyond the browser's ordinary media handling.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Shoulder",
    short_name: "Shoulder",
    description: "Your clips from your coach, and your own practice.",
    start_url: "/player",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0a0a09",
    theme_color: "#0a0a09",
    icons: [
      { src: "/pwa-192.png", sizes: "192x192", type: "image/png" },
      { src: "/pwa-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "/pwa-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
