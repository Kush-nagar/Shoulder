"use client";

import { useActionState, useEffect, useId, useState } from "react";
import { parseRoster } from "../../../lib/roster";
import { componentTitle, focus, label, metadata, primary } from "../ui";
import { saveRoster } from "./actions";

export function BulkPaste({ heading }: { heading: string }) {
  const [text, setText] = useState("");
  const [state, submit, pending] = useActionState(saveRoster, { message: "" });
  const fieldId = useId();
  const helpId = useId();
  const rows = text.trim() === "" ? [] : parseRoster(text);
  const invalid = rows.filter((row) => row.errors.length > 0).length;
  const ready = rows.length > 0 && invalid === 0 && rows.length <= 40;

  useEffect(() => {
    if (state.ok) setText("");
  }, [state]);

  return (
    <form action={submit} className="max-w-170">
      <h2 className={componentTitle}>{heading}</h2>
      <label htmlFor={fieldId} className={`${label} mt-4`}>
        Paste your roster
      </label>
      <p id={helpId} className={`${metadata} mt-1`}>
        One player per line, as name, number, position. Number and position are
        optional. Up to 40 rows at a time.
      </p>
      <textarea
        id={fieldId}
        name="paste"
        rows={6}
        value={text}
        aria-describedby={helpId}
        onChange={(event) => setText(event.target.value)}
        className={`mt-2 w-full rounded-lg border border-line bg-surface p-3 text-[15px] leading-[1.5] text-ink hover:border-muted ${focus}`}
      />

      {/* Reserve the preview geometry so nothing below moves when rows appear. */}
      <div className="mt-4 min-h-64">
        <h3 className={`${componentTitle} text-[15px]`}>Preview</h3>
        <p aria-live="polite" className={`${metadata} mt-1`}>
          {rows.length === 0
            ? "Nothing pasted yet."
            : invalid === 0
              ? `${rows.length} ${rows.length === 1 ? "row" : "rows"} ready to add.`
              : `${invalid} of ${rows.length} ${rows.length === 1 ? "row needs" : "rows need"} a fix. Nothing is saved until every row is valid.`}
        </p>
        {rows.length > 0 ? (
          <div className="mt-2 overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full border-collapse text-left text-[15px]">
              <caption className="sr-only">Pasted roster preview</caption>
              <thead>
                <tr className="border-b border-line">
                  <th
                    scope="col"
                    className="px-3 py-2 text-[13px] font-semibold"
                  >
                    Line
                  </th>
                  <th
                    scope="col"
                    className="px-3 py-2 text-[13px] font-semibold"
                  >
                    Player
                  </th>
                  <th
                    scope="col"
                    className="px-3 py-2 text-[13px] font-semibold"
                  >
                    Number
                  </th>
                  <th
                    scope="col"
                    className="px-3 py-2 text-[13px] font-semibold"
                  >
                    Position
                  </th>
                  <th
                    scope="col"
                    className="px-3 py-2 text-[13px] font-semibold"
                  >
                    Result
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr
                    // biome-ignore lint/suspicious/noArrayIndexKey: a preview row is its line.
                    key={index}
                    className="border-b border-line last:border-b-0"
                  >
                    <td className="px-3 py-2 tabular-nums">{index + 1}</td>
                    <td className="px-3 py-2">{row.display_name || "—"}</td>
                    <td className="px-3 py-2 tabular-nums">
                      {row.jersey_number ?? "—"}
                    </td>
                    <td className="px-3 py-2">{row.position ?? "—"}</td>
                    <td className="px-3 py-2">
                      {row.errors.length === 0 ? (
                        <span className={metadata}>Ready</span>
                      ) : (
                        <span className="font-medium">
                          {row.errors.join(" ")}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button type="submit" disabled={!ready || pending} className={primary}>
          {pending
            ? "Adding…"
            : `Add ${rows.length} ${rows.length === 1 ? "player" : "players"}`}
        </button>
        <p className={metadata}>
          All rows are added together, or none of them are.
        </p>
      </div>
      {state.message ? (
        <p
          role={state.ok ? "status" : "alert"}
          className="mt-3 text-[15px] font-medium"
        >
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
