/**
 * League-wide contract tracker.
 *
 * Sortable, filterable table of every active contract — owner uses it
 * to plan ahead (who's expiring, who's arb-eligible, who has pending
 * options, what's the team payroll situation). Mirrors the spirit of
 * the offseason "Contracts Review" stage but accessible mid-season so
 * the user isn't surprised at year-end.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  FileText,
  Filter,
  Loader2,
} from "lucide-react";

import { api, type ContractListRow } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { formatMoneyCompact, formatServiceTime } from "@/lib/format";
import { AppShell } from "@/components/layout/AppShell";
import { TeamLogo } from "@/components/TeamLogo";
import { usePersistedState } from "@/lib/use-persisted-state";
import { useTeams } from "@/lib/use-teams";
import { useVirtualRows } from "@/lib/use-virtual-rows";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  InfoTip,
  Input,
} from "@/components/ui";

/** Plain-language glossary for the contract status badges. */
const BADGE_TIPS = {
  expiring:
    "Final year of the current deal. Decide on an extension or qualifying offer before the player hits free agency.",
  arb:
    "Enough service time to demand a raise through arbitration instead of playing at team-set pay. Expect the salary to jump.",
  options:
    "Team/player option year(s) awaiting a decision. Declining a team option can trigger a buyout paid in cash.",
  nonGtd:
    "Not guaranteed — the team can release this player without owing the rest of the deal.",
  service:
    "Big-league service time (162 days = 1 season). Drives arbitration and free-agency eligibility.",
} as const;

type SortKey =
  | "name"
  | "team"
  | "pos"
  | "age"
  | "overall"
  | "salary"
  | "years_left"
  | "fa_year"
  | "service_time_days";
type SortDir = "asc" | "desc";

export function ContractsPage() {
  const userTeamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId);
  // Independent toggles so "my team" and "expiring" can be combined — the
  // common "which of MY players are about to expire?" question.
  const [mineOnly, setMineOnly] = usePersistedState<boolean>(
    "contracts:mineOnly",
    false,
  );
  const [expiringOnly, setExpiringOnly] = usePersistedState<boolean>(
    "contracts:expiringOnly",
    false,
  );
  const [search, setSearch] = usePersistedState("contracts:search", "");
  const [sortKey, setSortKey] = usePersistedState<SortKey>(
    "contracts:sortKey",
    "salary",
  );
  const [sortDir, setSortDir] = usePersistedState<SortDir>(
    "contracts:sortDir",
    "desc",
  );

  const teamFilter = mineOnly && userTeamId ? userTeamId : undefined;
  const expiringFilter = expiringOnly;

  const contractsQ = useQuery({
    queryKey: ["contracts", { team: teamFilter, expiring: expiringFilter }],
    queryFn: () =>
      api.listContracts({
        team_id: teamFilter,
        expiring_only: expiringFilter,
      }),
  });
  const teamsQ = useTeams();
  const teamById = useMemo(() => {
    const m = new Map<string, NonNullable<typeof teamsQ.data>[number]>();
    for (const t of teamsQ.data ?? []) m.set(t.team_id, t);
    return m;
  }, [teamsQ.data]);

  const filteredSorted = useMemo(() => {
    const rows = contractsQ.data?.contracts ?? [];
    const needle = search.trim().toLowerCase();
    let working = rows;
    if (needle) {
      working = rows.filter((r) =>
        `${r.first_name} ${r.last_name} ${r.team_id} ${r.primary_position} ${r.player_id}`
          .toLowerCase()
          .includes(needle),
      );
    }
    const sorted = [...working].sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      const as = String(av).toLowerCase();
      const bs = String(bv).toLowerCase();
      if (as < bs) return sortDir === "asc" ? -1 : 1;
      if (as > bs) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [contractsQ.data, search, sortKey, sortDir]);

  // Virtualize the league-wide table: only the visible rows (and their
  // InfoTip badges) mount instead of every contract in the league.
  const rowVirtual = useVirtualRows({
    count: filteredSorted.length,
    estimateRowHeight: 42,
  });

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" || key === "team" || key === "pos" ? "asc" : "desc");
    }
  }

  return (
    <AppShell
      title="Contracts"
      subtitle={
        contractsQ.data
          ? `${contractsQ.data.count} active contracts · current year ${contractsQ.data.current_year}`
          : "League-wide contract tracker"
      }
    >
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileText className="h-4 w-4 text-amber" /> Contracts
            </CardTitle>
            <CardDescription>
              Years remaining, salary, FA year, arbitration eligibility,
              and pending options across the league.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-[220px] flex-1">
              <Input
                placeholder="Filter by name, team, position, id…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
              {(
                [
                  {
                    key: "mine",
                    label: "My team",
                    active: mineOnly,
                    toggle: () => setMineOnly((v) => !v),
                    disabled: !userTeamId,
                    icon: false,
                  },
                  {
                    key: "expiring",
                    label: "Expiring",
                    active: expiringOnly,
                    toggle: () => setExpiringOnly((v) => !v),
                    disabled: false,
                    icon: true,
                  },
                ] as Array<{
                  key: string;
                  label: string;
                  active: boolean;
                  toggle: () => void;
                  disabled: boolean;
                  icon: boolean;
                }>
              ).map(({ key, label, active, toggle, disabled, icon }) => (
                <button
                  key={key}
                  type="button"
                  onClick={toggle}
                  disabled={disabled}
                  aria-pressed={active}
                  className={cn(
                    "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition disabled:opacity-40",
                    active
                      ? "bg-amber text-espresso"
                      : "text-muted hover:bg-surface hover:text-ink",
                  )}
                >
                  <span className="inline-flex items-center gap-1">
                    {icon && <Filter className="h-3 w-3 opacity-80" />}
                    {label}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {contractsQ.isLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading contracts…
            </div>
          ) : contractsQ.isError ? (
            <div className="flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              <AlertTriangle className="h-4 w-4" />
              {(contractsQ.error as Error).message}
            </div>
          ) : filteredSorted.length === 0 ? (
            <div className="rounded-md border border-border bg-surfaceAlt/40 px-4 py-6 text-sm text-muted">
              No contracts match. Try clearing the search or the My team /
              Expiring filters.
            </div>
          ) : (
            <div
              ref={rowVirtual.scrollRef}
              className="max-h-[640px] overflow-auto rounded-md border border-border"
            >
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-10 bg-surface">
                  <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                    <ContractHeader
                      label="Player"
                      keyId="name"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                      align="left"
                    />
                    <ContractHeader
                      label="Team"
                      keyId="team"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                      align="left"
                    />
                    <ContractHeader
                      label="Pos"
                      keyId="pos"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                    <ContractHeader
                      label="Age"
                      keyId="age"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                    <ContractHeader
                      label="Ovr"
                      keyId="overall"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                    <ContractHeader
                      label="Salary"
                      keyId="salary"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                    <ContractHeader
                      label="Yrs Left"
                      keyId="years_left"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                    <ContractHeader
                      label="FA Year"
                      keyId="fa_year"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                    <th className="select-none px-3 py-2 text-right font-semibold">
                      <span className="inline-flex items-center gap-1">
                        <ContractHeaderButton
                          label="Service"
                          keyId="service_time_days"
                          sortKey={sortKey}
                          sortDir={sortDir}
                          onClick={toggleSort}
                        />
                        <InfoTip tip={BADGE_TIPS.service} />
                      </span>
                    </th>
                    <th className="px-3 py-2 text-left font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rowVirtual.paddingTop > 0 && (
                    <tr aria-hidden="true">
                      <td
                        colSpan={10}
                        style={{ height: rowVirtual.paddingTop, padding: 0 }}
                      />
                    </tr>
                  )}
                  {rowVirtual.items.map((vi) => {
                    const row = filteredSorted[vi.index];
                    if (!row) return null;
                    const team = teamById.get(row.team_id);
                    return (
                      <tr
                        key={row.player_id}
                        data-index={vi.index}
                        ref={rowVirtual.measureRow}
                        className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
                      >
                        <td className="px-3 py-2">
                          <Link
                            to={`/player/${encodeURIComponent(row.player_id)}`}
                            className="font-semibold hover:text-amber"
                          >
                            {row.last_name}, {row.first_name}
                          </Link>
                        </td>
                        <td className="px-3 py-2">
                          {row.team_id ? (
                            <Link
                              to={`/team/${encodeURIComponent(row.team_id)}`}
                              className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider text-muted hover:text-amber"
                            >
                              <TeamLogo
                                teamId={row.team_id}
                                abbreviation={
                                  (team as { abbreviation?: string } | undefined)
                                    ?.abbreviation || row.team_id
                                }
                                primaryColor={
                                  (team as { primary_color?: string } | undefined)
                                    ?.primary_color
                                }
                                secondaryColor={
                                  (team as { secondary_color?: string } | undefined)
                                    ?.secondary_color
                                }
                                className="h-5 w-5 shrink-0 rounded text-[9px]"
                              />
                              {row.team_id}
                            </Link>
                          ) : (
                            <span className="text-xs uppercase text-muted">FA</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                          {row.primary_position || "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-muted">
                          {row.age ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums font-medium">
                          {row.overall ?? "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          <div>{formatMoneyCompact(row.annual_salary)}/yr</div>
                          {row.years_left > 1 && (
                            <div className="text-[11px] text-muted">
                              {formatMoneyCompact(
                                row.annual_salary * row.years_left,
                              )}{" "}
                              over {row.years_left} yrs
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {row.years_left}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-muted">
                          {row.fa_year || "—"}
                        </td>
                        <td
                          className="px-3 py-2 text-right tabular-nums text-muted"
                          title={`${row.service_time_days.toLocaleString()} service days`}
                        >
                          {formatServiceTime(
                            Math.floor(row.service_time_days / 162),
                            row.service_time_days % 162,
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1">
                            {row.expiring_this_year && (
                              <InfoTip tip={BADGE_TIPS.expiring}>
                                <Badge tone="warning" className="text-[10px]">
                                  Expiring
                                </Badge>
                              </InfoTip>
                            )}
                            {row.arb_eligible && (
                              <InfoTip tip={BADGE_TIPS.arb}>
                                <Badge tone="amber" className="text-[10px]">
                                  Arb-eligible
                                </Badge>
                              </InfoTip>
                            )}
                            {row.pending_options > 0 && (
                              <InfoTip tip={BADGE_TIPS.options}>
                                <Badge tone="neutral" className="text-[10px]">
                                  {row.pending_options} option
                                  {row.pending_options === 1 ? "" : "s"}
                                </Badge>
                              </InfoTip>
                            )}
                            {!row.guaranteed && (
                              <InfoTip tip={BADGE_TIPS.nonGtd}>
                                <Badge tone="neutral" className="text-[10px]">
                                  Non-gtd
                                </Badge>
                              </InfoTip>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {rowVirtual.paddingBottom > 0 && (
                    <tr aria-hidden="true">
                      <td
                        colSpan={10}
                        style={{ height: rowVirtual.paddingBottom, padding: 0 }}
                      />
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </AppShell>
  );
}

function sortValue(row: ContractListRow, key: SortKey): string | number {
  switch (key) {
    case "name":
      return `${row.last_name}, ${row.first_name}`;
    case "team":
      return row.team_id;
    case "pos":
      return row.primary_position;
    // Missing age/overall sort to the bottom either way rather than reading
    // as the league's worst player.
    case "age":
      return row.age ?? Number.MAX_SAFE_INTEGER;
    case "overall":
      return row.overall ?? -1;
    case "salary":
      return row.annual_salary;
    case "years_left":
      return row.years_left;
    case "fa_year":
      return row.fa_year;
    case "service_time_days":
      return row.service_time_days;
    default:
      return "";
  }
}

function ContractHeaderButton({
  label,
  keyId,
  sortKey,
  sortDir,
  onClick,
}: {
  label: string;
  keyId: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: (key: SortKey) => void;
}) {
  const active = sortKey === keyId;
  const Arrow = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={() => onClick(keyId)}
      className={cn(
        "inline-flex items-center gap-1 transition",
        active ? "text-ink" : "hover:text-ink",
      )}
    >
      {label}
      <Arrow className="h-3 w-3 opacity-60" />
    </button>
  );
}

function ContractHeader({
  label,
  keyId,
  sortKey,
  sortDir,
  onClick,
  align = "right",
}: {
  label: string;
  keyId: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: (key: SortKey) => void;
  align?: "left" | "right";
}) {
  return (
    <th
      className={cn(
        "select-none px-3 py-2 font-semibold",
        align === "left" ? "text-left" : "text-right",
      )}
    >
      <ContractHeaderButton
        label={label}
        keyId={keyId}
        sortKey={sortKey}
        sortDir={sortDir}
        onClick={onClick}
      />
    </th>
  );
}
