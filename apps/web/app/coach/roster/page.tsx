import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { fetchRoster, fetchTeams, type RosterPlayer } from "../../../lib/api";
import { requireCoach } from "../session";
import { PageHeader } from "../shell";
import { componentTitle, focus, metadata, sectionTitle, tertiary } from "../ui";
import { AddPlayer } from "./add-player";
import { ArchivePlayer } from "./archive-player";
import { BulkPaste } from "./bulk-paste";
import { RosterSearch } from "./search";

export const dynamic = "force-dynamic";

const cell = "px-3 py-3 align-top";
const head = "px-3 py-2 text-[13px] font-semibold";

function nextAction(player: RosterPlayer): string {
  if (!player.active_goal) return "Set a goal";
  if (!player.account_name) return "Invite";
  return "Open";
}

function Row({ player }: { player: RosterPlayer }) {
  const href = `/coach/players/${player.id}`;
  const action = nextAction(player);
  return (
    <tr
      data-player={`${player.display_name} ${player.jersey_number ?? ""} ${player.position ?? ""}`.toLowerCase()}
      className="border-b border-line last:border-b-0 hover:bg-line/30"
    >
      <td className={cell}>
        <Link href={href} className={`font-medium ${tertiary}`}>
          {player.display_name}
        </Link>
        {/* Low-priority columns become secondary row text before scrolling. */}
        <span className={`${metadata} mt-1 block md:hidden`}>
          {player.position ?? "No position"} ·{" "}
          {player.account_name ?? "Not linked"}
        </span>
      </td>
      <td className={`${cell} tabular-nums`}>{player.jersey_number ?? "—"}</td>
      <td className={`${cell} hidden md:table-cell`}>
        {player.position ?? "—"}
      </td>
      <td className={cell}>
        {player.active_goal ? (
          player.active_goal.title
        ) : (
          <span className={metadata}>Not set</span>
        )}
      </td>
      <td className={`${cell} hidden md:table-cell`}>
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className={`size-1.5 shrink-0 rounded-full border border-ink ${player.account_name ? "bg-ink" : ""}`}
          />
          {player.account_name ?? "Not linked"}
        </span>
      </td>
      <td className={cell}>
        <span className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Link
            href={href}
            aria-label={`${action} for ${player.display_name}`}
            className={tertiary}
          >
            {action}
          </Link>
          <ArchivePlayer playerId={player.id} name={player.display_name} />
        </span>
      </td>
    </tr>
  );
}

function Table({ players }: { players: RosterPlayer[] }) {
  return (
    <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-white">
      <table className="w-full border-collapse text-left text-[15px]">
        <caption className="sr-only">Roster</caption>
        <thead>
          <tr className="border-b border-line bg-white">
            <th scope="col" className={head}>
              Player
            </th>
            <th scope="col" className={head}>
              Number
            </th>
            <th scope="col" className={`${head} hidden md:table-cell`}>
              Position
            </th>
            <th scope="col" className={head}>
              Active goal
            </th>
            <th scope="col" className={`${head} hidden md:table-cell`}>
              Account
            </th>
            <th scope="col" className={head}>
              Next action
            </th>
          </tr>
        </thead>
        <tbody>
          {players.map((player) => (
            <Row key={player.id} player={player} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Body({ children }: { children: ReactNode }) {
  return <section className="px-5 py-6 md:px-6 lg:px-8">{children}</section>;
}

export default async function Roster() {
  const token = await requireCoach();
  const team = (await fetchTeams(token))[0];
  if (!team) {
    return (
      <>
        <PageHeader title="Players" />
        <Body>
          <h2 className={sectionTitle}>No team yet</h2>
          <p className="mt-3 max-w-170 text-[15px] leading-[1.5] text-muted">
            Your account is not attached to a team, so there is no roster to
            build. Ask whoever set up Shoulder for your club to add you.
          </p>
        </Body>
      </>
    );
  }
  const roster = await fetchRoster(token, team.team_id);
  if (roster === null) notFound();
  const players = roster.filter((player) => player.active);
  const archived = roster.filter((player) => !player.active);

  // One tree for both states. Every client form keeps the same slot among its
  // siblings, so saving the first player neither remounts a form nor hides it
  // behind a disclosure, and the confirmation the coach just earned survives.
  const empty = players.length === 0 && archived.length === 0;
  const table = <Table players={players} />;
  return (
    <>
      <PageHeader
        title="Players"
        description={empty ? undefined : `${players.length} on the roster`}
      />
      <Body>
        {empty ? (
          <div>
            <h2 className={sectionTitle}>Build your roster</h2>
            <p className="mt-3 max-w-170 text-[15px] leading-[1.5] text-muted">
              Paste your team list to start. You never need a player’s email
              address to add them.
            </p>
          </div>
        ) : players.length > 10 ? (
          <RosterSearch total={players.length}>{table}</RosterSearch>
        ) : (
          table
        )}
        <AddPlayer />
        <div className="mt-6 border-t border-line pt-4">
          <BulkPaste
            heading={empty ? "Add several at once" : "Add several more at once"}
          />
        </div>
        {archived.length > 0 ? (
          <details className="mt-6 border-t border-line pt-4">
            <summary
              className={`${componentTitle} cursor-pointer rounded-sm ${focus}`}
            >
              Archived players ({archived.length})
            </summary>
            <ul className="mt-3 space-y-1">
              {archived.map((player) => (
                <li key={player.id} className="text-[15px]">
                  <Link
                    href={`/coach/players/${player.id}`}
                    className={tertiary}
                  >
                    {player.display_name}
                  </Link>
                </li>
              ))}
            </ul>
            <p className={`${metadata} mt-2`}>
              Archived players stay off the roster. Nothing about them is
              deleted.
            </p>
          </details>
        ) : null}
      </Body>
    </>
  );
}
