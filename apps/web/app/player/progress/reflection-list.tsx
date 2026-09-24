"use client";

import { useState } from "react";
import type { PlayerReflection } from "../../../lib/api";
import { ReflectionEditor } from "../reflection-editor";

export function ReflectionList({
  playerId,
  initialReflections,
}: {
  playerId: string;
  initialReflections: PlayerReflection[];
}) {
  const [reflections, setReflections] = useState(initialReflections);
  if (reflections.length === 0) {
    return (
      <p className="mt-5 text-[16px] leading-6 text-muted">
        Notes you write on a clip show up here. They&apos;re optional.
      </p>
    );
  }
  return (
    <div className="mt-5 space-y-6">
      {reflections.map((reflection) => (
        <article key={reflection.id}>
          <p className="text-[14px] text-muted">
            Updated{" "}
            {new Date(reflection.updated_at).toLocaleDateString("en-US")}
          </p>
          <ReflectionEditor
            playerId={playerId}
            judgmentId={reflection.judgment_id}
            initialReflection={reflection}
            evidenceAvailable={reflection.evidence_available}
            onDelete={() =>
              setReflections((current) =>
                current.filter((item) => item.id !== reflection.id),
              )
            }
          />
        </article>
      ))}
    </div>
  );
}
