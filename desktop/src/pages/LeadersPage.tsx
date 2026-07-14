/**
 * Phase 4 port of ui/league_leaders_window.py.
 *
 * Two tabs (Batting / Pitching). Each tab is a grid of leaderboard cards,
 * one per category, with the top N players ranked. Player names link to
 * profiles; team chips link to the team page.
 */

import { useQuery } from "@tanstack/react-query";

import { usePersistedState } from "@/lib/use-persisted-state";
import { useTeams } from "@/lib/use-teams";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Award,
  Loader2,
  Trophy,
} from "lucide-react";

import { api, type LeaderBoard, type LeaderRow } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { ReorderableCards } from "@/components/layout/ReorderableCards";
import {
  useLayoutEditStore,
  useRegisterLayoutPage,
} from "@/lib/layout-edit-store";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { TeamLogo } from "@/components/TeamLogo";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

export function LeadersPage() {
  const [limit, setLimit] = usePersistedState("leaders:limit", 5);
  const [tab, setTab] = usePersistedState<"batting" | "pitching">(
    "leaders:tab",
    "batting",
  );
  const leaders = useQuery({
    queryKey: ["league-leaders", limit],
    queryFn: () => api.leaders(limit),
  });

  useRegisterLayoutPage("leaders");
  const editingLayout = useLayoutEditStore((s) => s.editing);

  return (
    <AppShell
      title="League Leaders"
      subtitle={
        leaders.data
          ? `Qualifier: ${leaders.data.qualifiers.min_pa} PA / ${leaders.data.qualifiers.min_ip} IP`
          : "Top performers across the league"
      }
    >
      <Tabs value={tab} onValueChange={(v) => setTab(v as "batting" | "pitching")}>
        <div className="mb-4 flex items-center gap-3">
          <TabsList>
            <TabsTrigger value="batting">Batting</TabsTrigger>
            <TabsTrigger value="pitching">Pitching</TabsTrigger>
          </TabsList>
          <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
            {[5, 10, 15].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setLimit(n)}
                className={
                  limit === n
                    ? "rounded-md bg-amber px-3 py-1 text-xs font-semibold uppercase tracking-wider text-espresso"
                    : "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider text-muted hover:bg-surface hover:text-ink"
                }
              >
                Top {n}
              </button>
            ))}
          </div>
        </div>

        <TabsContent value="batting">
          <Body
            isLoading={leaders.isLoading}
            isError={leaders.isError}
            error={leaders.error}
            boards={leaders.data?.batting ?? []}
            pageKey="leaders-batting"
            editing={editingLayout}
          />
        </TabsContent>
        <TabsContent value="pitching">
          <Body
            isLoading={leaders.isLoading}
            isError={leaders.isError}
            error={leaders.error}
            boards={leaders.data?.pitching ?? []}
            pageKey="leaders-pitching"
            editing={editingLayout}
          />
        </TabsContent>
      </Tabs>
    </AppShell>
  );
}

function Body({
  isLoading,
  isError,
  error,
  boards,
  pageKey,
  editing,
}: {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  boards: LeaderBoard[];
  pageKey: string;
  editing: boolean;
}) {
  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
          <span className="text-sm text-muted">Loading leaderboards…</span>
        </CardContent>
      </Card>
    );
  }
  if (isError) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10 text-danger">
          <AlertTriangle className="h-5 w-5" />
          <span className="text-sm">{(error as Error).message}</span>
        </CardContent>
      </Card>
    );
  }
  if (boards.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-sm text-muted">
          No leaderboard data yet — sim some games to populate stats.
        </CardContent>
      </Card>
    );
  }
  return (
    <ReorderableCards
      pageKey={pageKey}
      variant="grid"
      className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3"
      editing={editing}
      items={boards.map((board) => ({
        id: board.key,
        label: board.label,
        node: <BoardCard board={board} />,
      }))}
    />
  );
}

function BoardCard({ board }: { board: LeaderBoard }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{board.label}</CardTitle>
          <CardDescription>
            {board.descending ? "Higher is better" : "Lower is better"}
          </CardDescription>
        </div>
        <Badge tone="amber">
          <Trophy className="h-3 w-3" /> {board.leaders.length}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {board.leaders.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">
            No qualified leaders yet.
          </div>
        ) : (
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                <th className="px-6 py-2 text-left font-semibold">#</th>
                <th className="px-3 py-2 text-left font-semibold">Player</th>
                <th className="px-3 py-2 text-left font-semibold">Tm</th>
                <th className="px-6 py-2 text-right font-semibold">
                  {board.label}
                </th>
              </tr>
            </thead>
            <tbody>
              {board.leaders.map((row) => (
                <Row key={row.rank} row={row} decimals={board.decimals} />
              ))}
            </tbody>
          </table></div>
        )}
      </CardContent>
    </Card>
  );
}

function Row({ row, decimals }: { row: LeaderRow; decimals: number }) {
  // Reuse the app-wide ["teams"] cache (populated by many other pages);
  // React Query dedupes this fetch so it doesn't hit the sidecar again
  // when teams are already hydrated.
  const teamsQ = useTeams();
  const team = row.player.team_id
    ? teamsQ.data?.find((t) => t.team_id === row.player.team_id)
    : undefined;
  return (
    <tr className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40">
      <td className="px-6 py-2 text-xs font-mono text-muted">
        {row.rank === 1 ? (
          <Award className="h-4 w-4 text-amber" />
        ) : (
          row.rank
        )}
      </td>
      <td className="px-3 py-2">
        <Link
          to={`/player/${encodeURIComponent(row.player.player_id)}`}
          className="flex items-center gap-2 hover:text-amber"
        >
          <PlayerAvatar
            playerId={row.player.player_id}
            initials={`${row.player.first_name?.[0] ?? ""}${row.player.last_name?.[0] ?? ""}`}
            className="h-6 w-6 shrink-0 overflow-hidden rounded-md text-[9px]"
          />
          <span className="font-semibold">
            {row.player.last_name}, {row.player.first_name}
          </span>
        </Link>
      </td>
      <td className="px-3 py-2">
        {row.player.team_id ? (
          <Link
            to={`/team/${encodeURIComponent(row.player.team_id)}`}
            className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wider text-muted hover:text-amber"
          >
            <TeamLogo
              teamId={row.player.team_id}
              abbreviation={team?.abbreviation || row.player.team_id}
              primaryColor={team?.primary_color}
              secondaryColor={team?.secondary_color}
              className="h-5 w-5 shrink-0 rounded text-[9px]"
            />
            {row.player.team_id}
          </Link>
        ) : (
          <span className="text-xs uppercase text-muted">—</span>
        )}
      </td>
      <td className="px-6 py-2 text-right tabular-nums font-semibold text-amber-text">
        {formatVal(row.value, decimals)}
      </td>
    </tr>
  );
}

function formatVal(value: number | string, decimals: number): string {
  if (typeof value === "number") {
    if (decimals > 0) {
      const fixed = value.toFixed(decimals);
      // Drop leading zero for ratios like .312 / .987
      return fixed.startsWith("0") ? fixed.slice(1) : fixed;
    }
    return String(Math.round(value));
  }
  return String(value);
}
