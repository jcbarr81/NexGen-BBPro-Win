/**
 * League + team record book.
 *
 * Tabs: League / Team (scoped to the active team). Each row shows the
 * record label, the holder(s), the record value, and -- when known -- the
 * season label + a link to the player/team detail.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, Award, BookOpen, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { AppShell } from "@/components/layout/AppShell";
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

export function RecordsPage() {
  const [tab, setTab] = useState<"league" | "team">("league");
  const teamId = useAuthStore(
    (s) => s.selectedTeamId ?? s.teamId ?? null,
  );

  const league = useQuery({
    queryKey: ["league-records"],
    queryFn: () => api.leagueRecords(),
    enabled: tab === "league",
  });
  const team = useQuery({
    queryKey: ["team-records", teamId],
    queryFn: () => api.teamRecords(teamId as string),
    enabled: tab === "team" && !!teamId,
  });

  return (
    <AppShell
      title="Records"
      subtitle="All-time league and team record book"
    >
      <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
        <TabsList>
          <TabsTrigger value="league">League</TabsTrigger>
          <TabsTrigger value="team" disabled={!teamId}>
            Team ({teamId ?? "—"})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="league">
          {league.isLoading ? (
            <LoadingCard />
          ) : league.isError ? (
            <ErrorCard message={(league.error as Error).message} />
          ) : league.data ? (
            <LeagueRecordsView
              records={league.data.records as Record<string, Array<Record<string, unknown>>>}
            />
          ) : null}
        </TabsContent>

        <TabsContent value="team">
          {!teamId ? (
            <Card>
              <CardContent className="py-10 text-sm text-muted">
                Select a team to view its records.
              </CardContent>
            </Card>
          ) : team.isLoading ? (
            <LoadingCard />
          ) : team.isError ? (
            <ErrorCard message={(team.error as Error).message} />
          ) : team.data ? (
            <RecordList rows={team.data.records} />
          ) : null}
        </TabsContent>
      </Tabs>
    </AppShell>
  );
}

function LeagueRecordsView({
  records,
}: {
  records: Record<string, Array<Record<string, unknown>>>;
}) {
  const sections = useMemo(() => {
    // Prefer batting / pitching / team groupings; fall through to whatever keys come back.
    const order = ["batting", "pitching", "team"];
    const keys = [...new Set([...order, ...Object.keys(records ?? {})])].filter(
      (k) => Array.isArray(records?.[k]),
    );
    return keys;
  }, [records]);

  if (sections.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-sm text-muted">
          No records yet.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {sections.map((key) => (
        <Card key={key}>
          <CardHeader>
            <div>
              <CardTitle className="capitalize">{key}</CardTitle>
              <CardDescription>
                {(records[key] ?? []).length} records
              </CardDescription>
            </div>
            <Badge tone="amber">
              <BookOpen className="h-3 w-3" />
            </Badge>
          </CardHeader>
          <CardContent className="p-0">
            <RecordList rows={records[key] ?? []} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function RecordList({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows || rows.length === 0) {
    return <div className="px-6 py-6 text-sm text-muted">—</div>;
  }
  return (
    <ul className="divide-y divide-border/60">
      {rows.map((row, i) => {
        const holders = Array.isArray(row.holders) ? row.holders : [];
        const label = String(row.label ?? row.key ?? "—");
        const valueText = String(row.value_text ?? row.value ?? "—");
        return (
          <li
            key={`${label}-${i}`}
            className="flex items-start justify-between gap-3 px-6 py-2 text-sm"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Award className="h-3 w-3 text-amber" />
                <span className="font-semibold">{label}</span>
              </div>
              <div className="mt-0.5 text-xs text-muted">
                {holders.length === 0 ? (
                  "—"
                ) : (
                  holders.map((holder: Record<string, unknown>, idx: number) => (
                    <HolderChip key={idx} holder={holder} />
                  ))
                )}
              </div>
            </div>
            <div className="shrink-0 font-mono text-sm font-semibold text-amber-text">
              {valueText}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function HolderChip({ holder }: { holder: Record<string, unknown> }) {
  const name = String(
    holder.name ??
      holder.team_name ??
      holder.player_id ??
      holder.team_id ??
      "",
  );
  const season = String(holder.season_label ?? holder.season_id ?? "");
  const playerId = holder.player_id ? String(holder.player_id) : "";
  const teamId = holder.team_id ? String(holder.team_id) : "";
  const body = playerId ? (
    <Link
      to={`/player/${encodeURIComponent(playerId)}`}
      className="hover:text-amber"
    >
      {name}
    </Link>
  ) : teamId ? (
    <Link
      to={`/team/${encodeURIComponent(teamId)}`}
      className="hover:text-amber"
    >
      {name}
    </Link>
  ) : (
    <span>{name}</span>
  );
  return (
    <span className="inline-flex items-center gap-1 pr-3">
      {body}
      {season && <span className="text-[11px] text-subtle">({season})</span>}
    </span>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading records…</span>
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
