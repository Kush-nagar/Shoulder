import {
  CircleUser,
  LifeBuoy,
  type LucideIcon,
  Palette,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";
import { marketplaceEnabled } from "../../../lib/marketplace";
import { savedTheme } from "../../../lib/theme";
import { SectionHeading } from "../heading";
import { initial } from "../identity";
import { requirePlayerSession } from "../session";
import { PlayerSignOutForm } from "../sign-out-form";
import { pageTitle, textLink } from "../ui";
import { ShowGuideButton, ThemePicker } from "./profile-controls";

function Section({
  id,
  title,
  Icon,
  index,
  children,
}: {
  id: string;
  title: string;
  Icon: LucideIcon;
  index: number;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      style={{ "--i": index } as CSSProperties}
      className="sh-rise border-t border-line py-8"
    >
      <SectionHeading id={id} Icon={Icon}>
        {title}
      </SectionHeading>
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
  "The team board is off unless you join. It shows your session totals under a nickname, to your teammates and coach only.",
];

export default async function ProfilePage() {
  const { me } = await requirePlayerSession("/player/profile");
  const theme = await savedTheme();

  return (
    <div className="max-w-[680px]">
      <h1 className={`${pageTitle} mb-6`}>Profile</h1>

      <Section id="account-title" title="Account" Icon={CircleUser} index={0}>
        <div className="flex items-center gap-4">
          <span
            aria-hidden="true"
            className="flex size-14 shrink-0 items-center justify-center rounded-full bg-surface-subtle font-display text-[26px] text-ink ring-1 ring-line-strong"
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

      <Section
        id="appearance-title"
        title="Appearance"
        Icon={Palette}
        index={1}
      >
        <ThemePicker initial={theme} />
        <p className="mt-3 text-[14px] leading-5 text-muted">
          System follows your device.
        </p>
      </Section>

      <Section
        id="data-title"
        title="How your data is used"
        Icon={ShieldCheck}
        index={2}
      >
        <ul className="space-y-3">
          {dataUse.map((line) => (
            <li
              key={line}
              className="border-l-2 border-line-strong pl-4 text-[16px] leading-6 text-ink-2 transition-colors duration-150 hover:border-brand"
            >
              {line}
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id="delete-title"
        title="Delete something"
        Icon={Trash2}
        index={3}
      >
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

      <Section id="help-title" title="Help" Icon={LifeBuoy} index={4}>
        <ul className="space-y-1">
          {marketplaceEnabled() ? (
            <li>
              <Link href="/coaching" className={textLink}>
                Train with a coach (18+ pilot)
              </Link>
            </li>
          ) : null}
          <li>
            <ShowGuideButton />
          </li>
          <li>
            <Link href="/player/team" className={textLink}>
              Team board: join, change nickname or leave
            </Link>
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
