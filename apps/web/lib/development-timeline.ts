export type EvidenceDotVerdict = "applied" | "opportunity";

export type TimelineReflection = {
  judgmentId: string;
  text: string;
};

export type TimelineGame = {
  publicationId: string;
  gameLabel: string;
  publishedAt: string;
  dots: Array<{
    judgmentId: string;
    verdict: EvidenceDotVerdict;
    href: string;
  }>;
  reflections: TimelineReflection[];
};

export type TimelineGoal = {
  id: string;
  title: string;
  active: boolean;
  games: TimelineGame[];
};

export function verdictText(verdict: EvidenceDotVerdict): string {
  return verdict === "applied" ? "You did this." : "Chance to do this.";
}

export function evidenceDotLabel(
  verdict: EvidenceDotVerdict,
  gameLabel: string,
  position: number,
  gameSize: number,
): string {
  return `${verdictText(verdict)} ${gameLabel}, clip ${position} of ${gameSize}.`;
}

export function sharedDate(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(value));
}
