import Link from "next/link";
import type { ReactNode } from "react";
import { initial } from "../identity";
import { savedTheme } from "../../../lib/theme";
import { requirePlayerSession } from "../session";
import { PlayerSignOutForm } from "../sign-out-form";
import { pageTitle, sectionTitle, textLink } from "../ui";
import { ShowGuideButton, ThemePicker } from "./profile-controls";

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="border-t border-line py-8">
      <h2 id={id} className={sectionTitle}>
        {title}
      </h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

const dataUse = [
  "Your coach's clips are cut from team game video. You only ever see your own clips.",
  "Practice videos are yours. Your coach can't see them. Each one is deleted 90 days after upload.",
  "Body position is worked out on this device. Only a short summary of angles and head turns is sent when you ask for training ideas.",
  "Training ideas are AI suggestions, stored with the video. They are never shown to your coach or added to your coach's clips.",
  "Notes you write on clips are read by your coach. Only you can change or delete them.",
];

export default async function ProfilePage() {
  const { me } = await requirePlayerSession("/player/profile");
  const theme = await savedTheme();

  return (
    <div className="max-w-[680px]">
      <h1 className={`${pageTitle} mb-6`}>Profile</h1>

      <Section id="account-title" title="Account">
        <div className="flex items-center gap-4">
          <span
            aria-hidden="true"
            className="flex size-14 shrink-0 items-center justify-center rounded-full bg-ink font-display text-[26px] text-paper"
          >
            {initial(me.display_name)}
          </span>
          <dl className="min-w-0">
            <dt className="sr-only">Name</dt>
            <dd className="truncate text-[17px] font-semibold">
              {me.display_name}
            </dd>
            <dt className="sr-only">Email</dt>
            <dd className="truncate text-[15px] text-ink-2">{me.email}</dd>
          </dl>
        </div>
        <div className="mt-5 w-fit rounded-lg border border-control-border">
          <PlayerSignOutForm className="pr-5 font-semibold" />
        </div>
      </Section>

      <Section id="appearance-title" title="Appearance">
        <ThemePicker initial={theme} />
        <p className="mt-3 text-[14px] leading-5 text-muted">
          System follows your phone or computer setting.
        </p>
      </Section>

      <Section id="data-title" title="How your data is used">
        <ul className="space-y-3">
          {dataUse.map((line) => (
            <li
              key={line}
              className="border-l-2 border-line-strong pl-4 text-[16px] leading-6 text-ink-2"
            >
              {line}
            </li>
          ))}
        </ul>
      </Section>

      <Section id="delete-title" title="Delete something">
        <dl className="space-y-4 text-[16px] leading-6">
          <div>
            <dt className="font-semibold">A practice video</dt>
            <dd className="text-ink-2">
              Open it and choose Delete this video. It&apos;s removed straight
              away.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">A note</dt>
            <dd className="text-ink-2">
              Go to{" "}
              <Link
                href="/player/progress#notes"
                className="font-semibold text-action underline underline-offset-4"
              >
                Progress, Your notes
              </Link>
              , and delete it.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">
              A coach clip or your whole account
            </dt>
            <dd className="text-ink-2">
              Ask your coach. They can remove clips and start account deletion.
            </dd>
          </div>
        </dl>
      </Section>

      <Section id="help-title" title="Help">
        <ul className="space-y-1">
          <li>
            <ShowGuideButton />
          </li>
          <li>
            <Link href="/player/practice/new#filming-tips" className={textLink}>
              Filming tips
            </Link>
          </li>
        </ul>
      </Section>
    </div>
  );
}
