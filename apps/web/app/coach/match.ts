import type { Tone } from "../../components/status";
import type { Game, VideoSummary } from "../../lib/api";

const dateLabel = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export function matchDate(game: Pick<Game, "played_at">) {
  return dateLabel.format(new Date(game.played_at));
}

export function gameLabel(game: {
  opponent: string | null;
  played_at: string;
  kind: string;
}) {
  const who = game.opponent ? `vs ${game.opponent}` : "No opponent recorded";
  return `${who} · ${matchDate(game)}${game.kind === "scrimmage" ? " · Scrimmage" : ""}`;
}

/**
 * Plain stages, never an animated percentage the worker cannot measure
 * (`docs/05-ui.md`).
 */
export function videoState(video: VideoSummary): string {
  switch (video.status) {
    case "uploading":
      return `Upload unfinished — ${video.uploaded_parts} of ${video.part_count} parts stored`;
    case "uploaded":
      return "Uploaded · preparing video";
    case "processing":
      return "Preparing video";
    case "ready":
      return "Ready";
    case "failed":
      return "This upload did not finish. Upload the file again.";
    default:
      return "Not available";
  }
}

export function videoTone(video: VideoSummary | undefined): Tone {
  if (!video) return "neutral";
  if (video.status === "ready") return "ready";
  if (video.status === "failed") return "error";
  if (video.status === "deleted" || video.status === "deletion_pending")
    return "neutral";
  return "pending";
}

/** The video a match is best represented by: ready first, else the newest. */
export function mainVideo(game: Pick<Game, "videos">) {
  return (
    game.videos.find((video) => video.status === "ready") ?? game.videos.at(-1)
  );
}
