import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

// The dashboard is Block 03 work. Keep /coach reachable without inventing content.
export default function Coach() {
  redirect("/coach/roster");
}
