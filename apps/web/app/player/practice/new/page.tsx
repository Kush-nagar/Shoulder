import Link from "next/link";
import { requirePlayerSession } from "../../session";
import { focus } from "../format";
import { UploadForm } from "./upload-form";

export default async function NewPracticePage() {
  await requirePlayerSession("/player/practice/new");
  return (
    <div>
      <Link
        href="/player/practice"
        className={`inline-flex min-h-11 items-center text-[16px] underline underline-offset-4 ${focus}`}
      >
        Back to practice
      </Link>
      <h1 className="mt-4 text-[32px] font-semibold leading-[1.08] tracking-[-0.01em]">
        Upload practice
      </h1>
      <p className="mt-3 max-w-[48ch] text-[16px] leading-6 text-ink-2">
        Film from the side, with your whole body in the frame. Only you can see
        this video.
      </p>
      <p className="mt-2 max-w-[48ch] text-[16px] leading-6 text-ink-2">
        Only film yourself. Don't upload videos of other people.
      </p>
      <UploadForm />
    </div>
  );
}
