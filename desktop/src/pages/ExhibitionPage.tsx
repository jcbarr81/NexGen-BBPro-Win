/**
 * Exhibition Game Simulator — port of ui/exhibition_game_dialog.py.
 *
 * Admin picks two teams and runs a single game outside the schedule.
 * The box score renders inline plus a link to the full HTML boxscore
 * saved under data/exhibition_boxscores/.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ExternalLink,
  Loader2,
  Play,
  Swords,
  Trophy,
} from "lucide-react";

import { api } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

export function ExhibitionPage() {
  return (
    <AppShell
      title="Exhibition Game"
      subtitle="Admin: one-off simulation outside the schedule"
    >
      <ExhibitionBody />
    </AppShell>
  );
}

function ExhibitionBody() {
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.listTeams() });
  const [home, setHome] = useState("");
  const [away, setAway] = useState("");

  const sim = useMutation({
    mutationFn: () => api.simulateExhibition(home, away),
  });

  const canRun =
    !!home && !!away && home !== away && !sim.isPending;

  const teamLabel = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of teams.data ?? []) m.set(t.team_id, `${t.city} ${t.name}`);
    return m;
  }, [teams.data]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Swords className="h-4 w-4 text-amber" /> Matchup
          </CardTitle>
          <CardDescription>
            Uses each team's saved rosters and lineups. No schedule or stats
            are updated by this sim.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto]">
          <label className="flex flex-col gap-1 text-xs">
            <span className="uppercase tracking-wide text-muted">Away</span>
            <select
              className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
              value={away}
              onChange={(e) => setAway(e.target.value)}
            >
              <option value="">Select team…</option>
              {(teams.data ?? []).map((t) => (
                <option key={t.team_id} value={t.team_id}>
                  {t.city} {t.name} ({t.team_id})
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-end pb-1 text-xs uppercase text-muted">
            at
          </div>
          <label className="flex flex-col gap-1 text-xs">
            <span className="uppercase tracking-wide text-muted">Home</span>
            <select
              className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
              value={home}
              onChange={(e) => setHome(e.target.value)}
            >
              <option value="">Select team…</option>
              {(teams.data ?? []).map((t) => (
                <option key={t.team_id} value={t.team_id}>
                  {t.city} {t.name} ({t.team_id})
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-end">
            <Button onClick={() => sim.mutate()} disabled={!canRun} size="sm">
              {sim.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Play className="mr-1 h-4 w-4" />
              )}
              Simulate
            </Button>
          </div>
        </CardContent>
      </Card>

      {sim.isError && (
        <Card>
          <CardContent className="flex items-start gap-2 py-3 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-warning" />
            <span className="whitespace-pre-line">
              {(sim.error as Error).message}
            </span>
          </CardContent>
        </Card>
      )}

      {sim.data && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base">
              <Trophy className="h-4 w-4 text-amber" /> Final
            </CardTitle>
            <CardDescription>
              {teamLabel.get(sim.data.away_team) ?? sim.data.away_team}{" "}
              <span className="scoreboard-digits">{sim.data.away.score}</span> @{" "}
              {teamLabel.get(sim.data.home_team) ?? sim.data.home_team}{" "}
              <span className="scoreboard-digits">{sim.data.home.score}</span>
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {sim.data.boxscore_path && (
              <div className="flex items-center justify-between rounded-md border border-border bg-surface p-2 text-xs">
                <span className="font-mono text-muted">
                  {sim.data.boxscore_path}
                </span>
                <Badge tone="amber">
                  <ExternalLink className="h-3 w-3" /> Full HTML saved
                </Badge>
              </div>
            )}

            <SideBoxScore
              title={`Away — ${teamLabel.get(sim.data.away_team) ?? sim.data.away_team}`}
              side={sim.data.away}
            />
            <SideBoxScore
              title={`Home — ${teamLabel.get(sim.data.home_team) ?? sim.data.home_team}`}
              side={sim.data.home}
            />

            {sim.data.debug_log.length > 0 && (
              <DetailsBlock title="Strategy log">
                <pre className="whitespace-pre-wrap text-[11px] text-muted">
                  {sim.data.debug_log.join("\n")}
                </pre>
              </DetailsBlock>
            )}
            {Object.keys(sim.data.field_positions).length > 0 && (
              <DetailsBlock title="Field positions">
                <ul className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] text-muted md:grid-cols-3">
                  {Object.entries(sim.data.field_positions).map(([k, v]) => (
                    <li key={k}>
                      <span className="font-semibold">{k}:</span> {v}
                    </li>
                  ))}
                </ul>
              </DetailsBlock>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SideBoxScore({
  title,
  side,
}: {
  title: string;
  side: {
    score: number;
    batting: Array<{
      player_id: string;
      name: string;
      ab: number;
      h: number;
      bb: number;
      so: number;
      sb: number;
    }>;
    pitching: Array<{
      player_id: string;
      name: string;
      pitches: number;
      bb: number;
      so: number;
    }>;
  };
}) {
  return (
    <div className="rounded-md border border-border bg-surface p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-semibold">{title}</div>
        <div className="scoreboard-digits text-xl">{side.score}</div>
      </div>
      <div className="space-y-2 text-xs">
        <div>
          <div className="mb-1 font-semibold uppercase tracking-wide text-muted">
            Batting
          </div>
          <div className="overflow-x-auto"><table className="w-full">
            <thead>
              <tr className="text-muted">
                <th className="text-left font-medium">Player</th>
                <th className="text-right font-medium">AB</th>
                <th className="text-right font-medium">H</th>
                <th className="text-right font-medium">BB</th>
                <th className="text-right font-medium">SO</th>
                <th className="text-right font-medium">SB</th>
              </tr>
            </thead>
            <tbody>
              {side.batting.map((b, i) => (
                <tr key={`${b.player_id}-${i}`} className="border-t border-border/30">
                  <td>{b.name || b.player_id}</td>
                  <td className="text-right tabular-nums">{b.ab}</td>
                  <td className="text-right tabular-nums">{b.h}</td>
                  <td className="text-right tabular-nums">{b.bb}</td>
                  <td className="text-right tabular-nums">{b.so}</td>
                  <td className="text-right tabular-nums">{b.sb}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
        {side.pitching.length > 0 && (
          <div>
            <div className="mb-1 mt-2 font-semibold uppercase tracking-wide text-muted">
              Pitching
            </div>
            <div className="overflow-x-auto"><table className="w-full">
              <thead>
                <tr className="text-muted">
                  <th className="text-left font-medium">Player</th>
                  <th className="text-right font-medium">Pitches</th>
                  <th className="text-right font-medium">BB</th>
                  <th className="text-right font-medium">SO</th>
                </tr>
              </thead>
              <tbody>
                {side.pitching.map((p, i) => (
                  <tr key={`${p.player_id}-${i}`} className="border-t border-border/30">
                    <td>{p.name || p.player_id}</td>
                    <td className="text-right tabular-nums">{p.pitches}</td>
                    <td className="text-right tabular-nums">{p.bb}</td>
                    <td className="text-right tabular-nums">{p.so}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          </div>
        )}
      </div>
    </div>
  );
}

function DetailsBlock({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <details className="rounded-md border border-border bg-surface p-2 text-xs">
      <summary className="cursor-pointer font-semibold text-muted">
        {title}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}
