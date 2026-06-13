/**
 * League-wide contract tracker.
 *
 * Sortable, filterable table of every active contract — owner uses it
 * to plan ahead (who's expiring, who's arb-eligible, who has pending
 * options, what's the team payroll situation). Mirrors the spirit of
 * the offseason "Contracts Review" stage but accessible mid-season so
 * the user isn't surprised at year-end.
 */

import { useMemo, useState } from "react";
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
import { AppShell } from "@/components/layout/AppShell";
import { TeamLogo } from "@/components/TeamLogo";
import { usePersistedState } from "@/lib/use-persisted-state";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
} from "@/components/ui";

type Scope = "all" | "mine" | "expiring";
type SortKey =
  | "name"
  | "team"
  | "pos"
  | "salary"
  | "years_left"
  | "fa_year"
  | "service_time_days";
type SortDir = "asc" | "desc";

export function ContractsPage() {
  const userTeamId = useAuthStore((s) => s.selectedTeamId ?? s.teamId);
  const [scope, setScope] = usePersistedState<Scope>(
    "contracts:scope",
    "all",
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

  const teamFilter = scope === "mine" && userTeamId ? userTeamId : undefined;
  const expiringFilter = scope === "expiring";

  const contractsQ = useQuery({
    queryKey: ["contracts", { team: teamFilter, expiring: expiringFilter }],
    queryFn: () =>
      api.listContracts({
        team_id: teamFilter,
        expiring_only: expiringFilter,
      }),
  });
  const teamsQ = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });
  const teamById = useMemo(() => {
    const m = new Map<string, ReturnType<typeof teamsQ.data extends undefined ? never : (typeof teamsQ.data)[number] | undefined>>();
    for (const t of teamsQ.data ?? []) m.set(t.team_id, t as never);
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
                  { key: "all", label: "All" },
                  { key: "mine", label: "My team" },
                  { key: "expiring", label: "Expiring" },
                ] as Array<{ key: Scope; label: string }>
              ).map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setScope(key)}
                  disabled={key === "mine" && !userTeamId}
                  className={cn(
                    "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition disabled:opacity-40",
                    scope === key
                      ? "bg-amber text-espresso"
                      : "text-muted hover:bg-surface hover:text-ink",
                  )}
                >
                  <span className="inline-flex items-center gap-1">
                    {key === "expiring" && (
                      <Filter className="h-3 w-3 opacity-80" />
                    )}
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
              No contracts match. Try clearing the filter or switching scope.
            </div>
          ) : (
            <div className="max-h-[640px] overflow-auto rounded-md border border-border">
              <div className="overflow-x-auto"><table className="w-full text-sm">
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
                    <ContractHeader
                      label="Service"
                      keyId="service_time_days"
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                    <th className="px-3 py-2 text-left font-semibold">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSorted.map((row) => {
                    const team = teamById.get(row.team_id);
                    return (
                      <tr
                        key={row.player_id}
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
                        <td className="px-3 py-2 text-right tabular-nums">
                          ${row.annual_salary.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {row.years_left}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-muted">
                          {row.fa_year || "—"}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums text-muted">
                          {Math.floor(row.service_time_days / 162)}.
                          {String(row.service_time_days % 162).padStart(3, "0")}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1">
                            {row.expiring_this_year && (
                              <Badge tone="warning" className="text-[10px]">
                                Expiring
                              </Badge>
                            )}
                            {row.arb_eligible && (
                              <Badge tone="amber" className="text-[10px]">
                                Arb-eligible
                              </Badge>
                            )}
                            {row.pending_options > 0 && (
                              <Badge tone="neutral" className="text-[10px]">
                                {row.pending_options} option
                                {row.pending_options === 1 ? "" : "s"}
                              </Badge>
                            )}
                            {!row.guaranteed && (
                              <Badge tone="neutral" className="text-[10px]">
                                Non-gtd
                              </Badge>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table></div>
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
  const active = sortKey === keyId;
  const Arrow = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      className={cn(
        "select-none px-3 py-2 font-semibold",
        align === "left" ? "text-left" : "text-right",
      )}
    >
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
    </th>
  );
}
