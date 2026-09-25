import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ShoulderWordmark } from "../../../components/brand";
import { fetchMe, joinDemo } from "../../../lib/api";
import { verifiedRedirectPath } from "../../../lib/auth/policy";
import { createAuthClient, verifiedToken } from "../../../lib/auth/server";
import { savedTheme, themeAttribute } from "../../../lib/theme";

export const dynamic = "force-dynamic";

export default async function Session({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const store = await cookies();
  const client = createAuthClient({ getAll: () => store.getAll() });
  const token = await verifiedToken(client);
  if (!token) redirect("/auth/sign-in");
  // A waking API can miss the first call; retry before showing any fallback.
  let me = await fetchMe(token);
  for (let attempt = 0; !me && attempt < 3; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    me = await fetchMe(token);
  }
  const next = verifiedRedirectPath((await searchParams).next);
  if (next?.startsWith("/coach/") && me?.roles.includes("coach")) {
    redirect(next);
  }
  if (
    next?.startsWith("/player/") &&
    me?.roles.includes("player") &&
    me.player
  ) {
    redirect(next);
  }
  if (me?.roles.includes("coach")) redirect("/coach/roster");
  if (me?.roles.includes("player") && me.player) redirect("/player");
  // Public demo only: a team-less account becomes a synthetic demo player.
  if (me && !me.roles.length && !me.player && (await joinDemo(token))) {
    redirect(next?.startsWith("/player/") ? next : "/player");
  }
  const button =
    "inline-flex min-h-12 items-center justify-center rounded-lg px-5 text-[16px] font-semibold transition-[background-color,transform] duration-150 active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";
  return (
    <main
      data-theme={themeAttribute(await savedTheme())}
      className="sh-themed flex min-h-dvh flex-col bg-paper px-5 pt-[max(2.5rem,env(safe-area-inset-top))] pb-8 text-ink sm:px-8"
    >
      <ShoulderWordmark className="h-auto w-36" />
      <div className="my-auto w-full max-w-md py-12">
        <h1 className="font-display text-[34px] leading-[1.05] md:text-[40px]">
          You’re signed in.
        </h1>
        <p className="mt-3 text-[16px] leading-6 text-ink-2">
          {me
            ? "Your identity is verified. Team access is not available yet."
            : "Shoulder is taking longer than usual to load your space. Try again in a moment."}
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          {me ? null : (
            <a
              href="/auth/session"
              className={`${button} bg-action text-on-action hover:bg-action-hover`}
            >
              Try again
            </a>
          )}
          <form action="/auth/sign-out" method="post">
            <button
              type="submit"
              className={`${button} border border-control-border bg-surface hover:bg-surface-subtle`}
            >
              Sign out
            </button>
          </form>
        </div>
      </div>
    </main>
  );
}
