/**
 * Phase 4 port of ui/league_stats_window.py.
 *
 * Three tabs: Batters / Pitchers / Teams. Each table is searchable + sortable
 * by any column. Player + team cells link to their detail pages.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Search,
} from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Card,
  CardContent,
  Input,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

type SortDir = "asc" | "desc";

const RATE_COLS = new Set(["avg", "obp", "slg", "era", "whip", "ip"]);

export function StatsPage() {
  const stats = useQuery({
    queryKey: ["league-stats"],
    queryFn: () => api.leagueStats(),
  });

  return (
    <AppShell title="League Stats" subtitle="Per-player + team season totals">
      {stats.isLoading ? (
        <LoadingCard />
      ) : stats.isError ? (
        <ErrorCard message={(stats.error as Error).message} />
      ) : stats.data ? (
        <Tabs defaultValue="batters">
          <TabsList>
            <TabsTrigger value="batters">
              Batters · {stats.data.batters.length}
            </TabsTrigger>
            <TabsTrigger value="pitchers">
              Pitchers · {stats.data.pitchers.length}
            </TabsTrigger>
            <TabsTrigger value="teams">
              Teams · {stats.data.teams.length}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="batters">
            <PlayerStatsTable
              rows={stats.data.batters}
              columns={stats.data.columns.batters}
              defaultSort="hr"
            />
          </TabsContent>
          <TabsContent value="pitchers">
            <PlayerStatsTable
              rows={stats.data.pitchers}
              columns={stats.data.columns.pitchers}
              defaultSort="era"
              defaultSortDir="asc"
            />
          </TabsContent>
          <TabsContent value="teams">
            <TeamStatsTable
              rows={stats.data.teams}
              columns={stats.data.columns.teams}
            />
          </TabsContent>
        </Tabs>
      ) : null}
    </AppShell>
  );
}

interface PlayerRow {
  player_id: string;
  first_name: string;
  last_name: string;
  primary_position: string;
  is_pitcher: boolean;
  stats: Record<string, number | string | null>;
}

function PlayerStatsTable({
  rows,
  columns,
  defaultSort,
  defaultSortDir = "desc",
}: {
  rows: PlayerRow[];
  columns: string[];
  defaultSort: string;
  defaultSortDir?: SortDir;
}) {
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<string>(defaultSort);
  const [sortDir, setSortDir] = useState<SortDir>(defaultSortDir);

  const filtered = useMemo(() => {
    let r = rows;
    if (search.trim()) {
      const needle = search.trim().toLowerCase();
      r = r.filter((row) =>
        `${row.first_name} ${row.last_name} ${row.player_id} ${row.primary_position}`
          .toLowerCase()
          .includes(needle),
      );
    }
    const sorted = [...r];
    sorted.sort((a, b) => {
      const av = sortKey === "name" ? `${a.last_name}, ${a.first_name}` : a.stats[sortKey];
      const bv = sortKey === "name" ? `${b.last_name}, ${b.first_name}` : b.stats[sortKey];
      return cmp(av, bv, sortDir);
    });
    return sorted;
  }, [rows, search, sortKey, sortDir]);

  function toggle(key: string) {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDir(key === "name" ? "asc" : "desc");
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input
            className="pl-9"
            placeholder="Search players…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <span className="text-xs text-muted">{filtered.length} shown</span>
      </div>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <SortHeader
                label="Player"
                keyId="name"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={toggle}
                align="left"
              />
              <th className="px-3 py-2 text-left font-semibold">Pos</th>
              {columns.map((col) => (
                <SortHeader
                  key={col}
                  label={col.toUpperCase()}
                  keyId={col}
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggle}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => (
              <tr
                key={row.player_id}
                className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
              >
                <td className="px-6 py-2">
                  <Link
                    to={`/player/${encodeURIComponent(row.player_id)}`}
                    className="font-semibold hover:text-amber"
                  >
                    {row.last_name}, {row.first_name}
                  </Link>
                </td>
                <td className="px-3 py-2 text-xs uppercase tracking-wider text-muted">
                  {row.primary_position || (row.is_pitcher ? "PIT" : "POS")}
                </td>
                {columns.map((col) => (
                  <td key={col} className="px-3 py-2 text-right tabular-nums">
                    {formatStat(col, row.stats[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function TeamStatsTable({
  rows,
  columns,
}: {
  rows: Array<{ team_id: string; stats: Record<string, number | string | null> }>;
  columns: string[];
}) {
  const [sortKey, setSortKey] = useState<string>("w");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const arr = [...rows];
    arr.sort((a, b) =>
      cmp(
        sortKey === "team" ? a.team_id : a.stats[sortKey],
        sortKey === "team" ? b.team_id : b.stats[sortKey],
        sortDir,
      ),
    );
    return arr;
  }, [rows, sortKey, sortDir]);

  function toggle(key: string) {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDir(key === "team" ? "asc" : "desc");
    }
  }

  return (
    <Card>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <SortHeader
                label="Team"
                keyId="team"
                sortKey={sortKey}
                sortDir={sortDir}
                onClick={toggle}
                align="left"
              />
              {columns.map((col) => (
                <SortHeader
                  key={col}
                  label={col.toUpperCase()}
                  keyId={col}
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onClick={toggle}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr
                key={row.team_id}
                className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
              >
                <td className="px-6 py-2">
                  <Link
                    to={`/team/${encodeURIComponent(row.team_id)}`}
                    className="font-semibold hover:text-amber"
                  >
                    {row.team_id}
                  </Link>
                </td>
                {columns.map((col) => (
                  <td key={col} className="px-3 py-2 text-right tabular-nums">
                    {formatStat(col, row.stats[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function SortHeader({
  label,
  keyId,
  sortKey,
  sortDir,
  onClick,
  align = "right",
}: {
  label: string;
  keyId: string;
  sortKey: string;
  sortDir: SortDir;
  onClick: (k: string) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === keyId;
  const Arrow = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      className={cn(
        "select-none px-3 py-2 font-semibold",
        align === "left" ? "pl-6 text-left" : "text-right",
      )}
    >
      <button
        type="button"
        onClick={() => onClick(keyId)}
        className={cn(
          "inline-flex items-center gap-1 hover:text-ink",
          active ? "text-ink" : "text-muted",
          align === "right" && "flex-row-reverse",
        )}
      >
        <Arrow className="h-3 w-3" />
        {label}
      </button>
    </th>
  );
}

function cmp(
  a: number | string | null | undefined,
  b: number | string | null | undefined,
  dir: SortDir,
): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  if (typeof a === "number" && typeof b === "number") {
    return dir === "asc" ? a - b : b - a;
  }
  const as = String(a).toLowerCase();
  const bs = String(b).toLowerCase();
  if (as < bs) return dir === "asc" ? -1 : 1;
  if (as > bs) return dir === "asc" ? 1 : -1;
  return 0;
}

function formatStat(col: string, value: number | string | null): string {
  if (value == null || value === "") return "—";
  if (typeof value === "string") return value;
  if (RATE_COLS.has(col)) {
    if (col === "ip") return value.toFixed(1);
    if (col === "era" || col === "whip") return value.toFixed(2);
    return value.toFixed(3).replace(/^0/, "");
  }
  return String(Math.round(value));
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading stats…</span>
      </CardContent>
    </Card>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10 text-danger">
        <AlertTriangle className="h-5 w-5" />
        <span className="text-sm">{message}</span>
      </CardContent>
    </Card>
  );
}
