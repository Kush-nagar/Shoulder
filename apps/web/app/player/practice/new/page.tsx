import { ArrowLeft, Check, Info } from "lucide-react";
import Link from "next/link";
import { requirePlayerSession } from "../../session";
import { backLink, pageTitle } from "../../ui";
import { UploadForm } from "./upload-form";

const tips = [
  "Hold the phone sideways.",
  "Keep your whole body in the frame, head to feet.",
  "10 to 60 seconds is plenty.",
  "Film in daylight or a bright hall.",
  "No one else in the shot.",
];

export default async function NewPracticePage({
  searchParams,
}: {
  searchParams: Promise<{ title?: string }>;
}) {
  await requirePlayerSession("/player/practice/new");
  const prefill = (await searchParams).title?.slice(0, 80) ?? "";
  return (
    <div>
      <Link href="/player/practice" className={backLink}>
        <ArrowLeft size={20} strokeWidth={2} aria-hidden="true" />
        Practice
      </Link>
      <div className="mt-4 grid gap-10 lg:grid-cols-12 lg:gap-8">
        <div className="max-w-[680px] lg:col-span-7">
          <h1 className={pageTitle}>Film practice</h1>
          <p className="mt-3 text-[16px] leading-6 text-ink-2">
            Only you can see this video. It is removed 90 days after upload.
          </p>
          <p className="mt-5 flex gap-3 rounded-xl border border-line bg-surface p-4 text-[16px] leading-6">
            <Info
              size={20}
              strokeWidth={2}
              aria-hidden="true"
              className="mt-0.5 shrink-0 text-ink-2"
            />
            <span>
              Film only yourself. If teammates are in the shot, crop or re-film.
            </span>
          </p>
          <UploadForm initialTitle={prefill} />
        </div>
        <aside
          id="filming-tips"
          aria-labelledby="tips-title"
          className="scroll-mt-20 border-t border-line pt-6 lg:col-span-5 lg:mt-2 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-8"
        >
          <h2
            id="tips-title"
            className="text-[20px] font-semibold leading-[1.25]"
          >
            Filming tips
          </h2>
          <ul className="mt-4 space-y-3">
            {tips.map((tip) => (
              <li
                key={tip}
                className="flex gap-3 text-[16px] leading-6 text-ink-2"
              >
                <Check
                  size={20}
                  strokeWidth={2}
                  aria-hidden="true"
                  className="mt-0.5 shrink-0 text-brand"
                />
                {tip}
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}
