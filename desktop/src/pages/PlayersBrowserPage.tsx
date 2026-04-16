/**
 * Phase 4 port of ui/player_browser_dialog.py.
 *
 * League-wide player explorer: filter by name / team / position / role
 * and toggle "free agents only". Player + team cells link to detail
 * pages; level chip shows where on the org chart they sit.
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
  Badge,
  Card,
  CardContent,
  Input,
} from "@/components/ui";

type SortKey = "name" | "team" | "pos" | "level" | "role" | string;
type SortDir = "asc" | "desc";
type RoleFilter = "All" | "Hitters" | "Pitchers";

const RATING_COLS = ["ch", "ph", "sp", "eye", "fa", "arm"];
const PITCHER_RATING_COLS = ["fb", "control", "movement", "endurance"];

export function PlayersBrowserPage() {
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("");
  const [team, setTeam] = useState("");
  const [role, setRole] = useState<RoleFilter>("All");
  const [freeOnly, setFreeOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });

  const players = useQuery({
    queryKey: [
      "players-browse",
      search,
      team,
      position,
      role,
      freeOnly,
    ],
    queryFn: () =>
      api.browsePlayers({
        q: search || undefined,
        teamId: team || undefined,
        position: position || undefined,
        role,
        freeAgentsOnly: freeOnly,
        limit: 5000,
      }),
  });

  const positions = useMemo(() => {
    const s = new Set<string>();
    for (const p of players.data?.players ?? []) {
      if (p.primary_position) s.add(p.primary_position);
    }
    return [...s].sort();
  }, [players.data]);

  const showPitcherCols =
    role === "Pitchers" ||
    (role === "All" &&
      (players.data?.players ?? []).filter((p) => p.is_pitcher).length /
        Math.max(1, players.data?.players.length ?? 0) >
        0.5);
  const ratingCols = showPitcherCols ? PITCHER_RATING_COLS : RATING_COLS;

  const sorted = useMemo(() => {
    const arr = [...(players.data?.players ?? [])];
    arr.sort((a, b) => {
      const av =
        sortKey === "name"
          ? `${a.last_name}, ${a.first_name}`
          : sortKey === "team"
            ? a.team_id
            : sortKey === "pos"
              ? a.primary_position
              : sortKey === "level"
                ? a.level
                : sortKey === "role"
                  ? a.role
                  : a.ratings[sortKey];
      const bv =
        sortKey === "name"
          ? `${b.last_name}, ${b.first_name}`
          : sortKey === "team"
            ? b.team_id
            : sortKey === "pos"
              ? b.primary_position
              : sortKey === "level"
                ? b.level
                : sortKey === "role"
                  ? b.role
                  : b.ratings[sortKey];
      return cmp(av, bv, sortDir);
    });
    return arr;
  }, [players.data, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDir(
        key === "name" || key === "team" || key === "pos" || key === "level" || key === "role"
          ? "asc"
          : "desc",
      );
    }
  }

  return (
    <AppShell
      title="Players"
      subtitle="League-wide directory · search, filter, drill in"
    >
      <Card className="mb-4">
        <CardContent className="grid grid-cols-1 gap-3 p-4 md:grid-cols-[1fr_auto_auto_auto_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-9"
              placeholder="Search by name or id…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select
            value={team}
            onChange={(e) => setTeam(e.target.value)}
            className="h-10 rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
          >
            <option value="">All teams</option>
            {teams.data?.map((t) => (
              <option key={t.team_id} value={t.team_id}>
                {t.team_id} · {t.city} {t.name}
              </option>
            ))}
          </select>
          <select
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            className="h-10 rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
          >
            <option value="">All positions</option>
            {positions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
            {(["All", "Hitters", "Pitchers"] as const).map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRole(r)}
                className={cn(
                  "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                  role === r
                    ? "bg-amber text-espresso"
                    : "text-muted hover:bg-surface hover:text-ink",
                )}
              >
                {r}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={freeOnly}
              onChange={(e) => setFreeOnly(e.target.checked)}
              className="h-4 w-4 accent-amber"
            />
            Free agents only
          </label>
        </CardContent>
      </Card>

      {players.isLoading ? (
        <LoadingCard />
      ) : players.isError ? (
        <ErrorCard message={(players.error as Error).message} />
      ) : !players.data || sorted.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-sm text-muted">
            No players match.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <div className="flex items-center justify-between border-b border-border/60 px-4 py-3">
            <Badge tone="amber">{sorted.length} players</Badge>
          </div>
          <CardContent className="overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                  <Header label="Player" keyId="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} align="left" />
                  <Header label="Tm" keyId="team" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} align="left" />
                  <Header label="Lvl" keyId="level" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                  <Header label="Pos" keyId="pos" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                  <Header label="Role" keyId="role" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                  {ratingCols.map((c) => (
                    <Header
                      key={c}
                      label={c.toUpperCase()}
                      keyId={c}
                      sortKey={sortKey}
                      sortDir={sortDir}
                      onClick={toggleSort}
                    />
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((p) => (
                  <tr
                    key={p.player_id}
                    className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
                  >
                    <td className="px-6 py-2">
                      <Link
                        to={`/player/${encodeURIComponent(p.player_id)}`}
                        className="font-semibold hover:text-amber"
                      >
                        {p.last_name}, {p.first_name}
                      </Link>
                    </td>
                    <td className="px-3 py-2">
                      {p.team_id ? (
                        <Link
                          to={`/team/${encodeURIComponent(p.team_id)}`}
                          className="text-xs font-semibold uppercase tracking-wider hover:text-amber"
                        >
                          {p.team_id}
                        </Link>
                      ) : (
                        <span className="text-xs text-muted">FA</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <Badge tone={levelTone(p.level)}>{p.level}</Badge>
                    </td>
                    <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                      {p.primary_position || "—"}
                    </td>
                    <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                      {p.role || (p.is_pitcher ? "PIT" : "POS")}
                    </td>
                    {ratingCols.map((c) => (
                      <td key={c} className="px-3 py-2 text-right tabular-nums">
                        <RatingCell value={p.ratings[c]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </AppShell>
  );
}

function levelTone(
  level: string,
): "amber" | "neutral" | "success" | "warning" | "danger" {
  if (level === "ACT") return "success";
  if (level === "AAA" || level === "LOW") return "neutral";
  if (level === "DL") return "warning";
  if (level === "IR") return "danger";
  return "amber";
}

function Header({
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
  onClick: (k: SortKey) => void;
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

function RatingCell({ value }: { value: number | string | null | undefined }) {
  if (value == null || value === "") return <span className="text-subtle">—</span>;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return <>{String(value)}</>;
  const tone =
    n >= 85 ? "text-success" : n >= 70 ? "text-amber-text" : n >= 50 ? "text-ink" : "text-subtle";
  return <span className={tone}>{Math.round(n)}</span>;
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

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading players…</span>
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
