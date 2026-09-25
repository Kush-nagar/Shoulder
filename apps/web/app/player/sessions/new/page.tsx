import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { requirePlayerSession } from "../../session";
import { backLink, pageTitle } from "../../ui";
import { SessionTracker } from "./tracker";

export default async function NewSessionPage() {
  await requirePlayerSession("/player/sessions/new");
  return (
    <div>
      <Link href="/player/sessions" className={backLink}>
        <ArrowLeft size={20} strokeWidth={2} aria-hidden="true" />
        Sessions
      </Link>
      <h1 className={`${pageTitle} mt-3`}>Record a session</h1>
      <SessionTracker />
    </div>
  );
}
