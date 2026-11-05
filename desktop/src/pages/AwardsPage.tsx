/**
 * League awards browser.
 *
 * Lists every archived season's award winners (MVP, Cy Young, Gold Gloves
 * and Silver Sluggers, one set per league in a split league), chosen at
 * the offseason rollover. Newest year first.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, Award, Loader2, Trophy } from "lucide-react";

import { api, type AwardSeason, type AwardWinner } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { usePersistedState } from "@/lib/use-persisted-state";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

export function AwardsPage() {
  const awardsQ = useQuery({
    queryKey: ["awards"],
    queryFn: () => api.listAwards(),
  });

  const seasons = awardsQ.data?.seasons ?? [];
  const yearOptions = useMemo(
    () =>
      seasons
        .map((s) => s.league_year)
        .filter((y): y is number => typeof y === "number"),
    [seasons],
  );

  // Default to the most-recent season; persist selection so back-nav
  // returns to the same year.
  const [selectedYear, setSelectedYear] = usePersistedState<string>(
    "awards:year",
    "",
  );

  const activeYear =
    selectedYear && yearOptions.includes(Number(selectedYear))
      ? Number(selectedYear)
      : yearOptions[0] ?? null;

  const visibleSeason: AwardSeason | undefined =
    activeYear != null
      ? seasons.find((s) => s.league_year === activeYear)
      : undefined;

  return (
    <AppShell
      title="Awards"
      subtitle={
        seasons.length > 0
          ? `${seasons.length} season${seasons.length === 1 ? "" : "s"} of award history`
          : "League award history"
      }
    >
      {awardsQ.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading awards…</span>
          </CardContent>
        </Card>
      ) : awardsQ.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(awardsQ.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : seasons.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Trophy className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">No awards yet</h2>
            <p className="max-w-sm text-sm text-muted">
              Award winners are computed automatically when a season rolls
              over to the offseason. Finish a season to see results here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {yearOptions.length > 1 && (
            <Tabs
              value={String(activeYear ?? "")}
              onValueChange={(v) => setSelectedYear(v)}
            >
              <TabsList>
                {yearOptions.map((y) => (
                  <TabsTrigger key={y} value={String(y)}>
                    {y}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          )}

          {visibleSeason ? (
            <SeasonAwardCard season={visibleSeason} />
          ) : (
            <Card>
              <CardContent className="py-6 text-sm text-muted">
                Pick a year above to view its winners.
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </AppShell>
  );
}

const MAJOR = new Set(["MVP", "CY_YOUNG"]);
const GLOVE_POSITIONS = ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"];
const SLUGGER_POSITIONS = ["C", "1B", "2B", "3B", "SS", "OF", "DH"];

function awardType(w: AwardWinner): string {
  return (w.type || w.award.split(":")[0] || "").toUpperCase();
}

function SeasonAwardCard({ season }: { season: AwardSeason }) {
  const major = season.awards.filter((w) => MAJOR.has(awardType(w)));
  const gloves = season.awards.filter((w) => awardType(w) === "GOLD_GLOVE");
  const sluggers = season.awards.filter((w) => awardType(w) === "SILVER_SLUGGER");
  const other = season.awards.filter(
    (w) => !MAJOR.has(awardType(w)) && awardType(w) !== "GOLD_GLOVE" && awardType(w) !== "SILVER_SLUGGER",
  );
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <Trophy className="h-4 w-4 text-amber" />
              {season.league_year ?? "Unknown year"} — Season Awards
            </CardTitle>
            <CardDescription>
              Chosen from the regular season when it ends: MVP by OPS and Cy
              Young by ERA among qualified players, one of each per league.
            </CardDescription>
          </div>
          <Badge tone="amber">{season.awards.length}</Badge>
        </CardHeader>
        <CardContent className="p-0">
          <div className="grid grid-cols-1 gap-px bg-border md:grid-cols-2">
            {[...major, ...other].map((winner) => (
              <div key={winner.award} className="flex items-start gap-3 bg-surface p-4">
                <Award className="mt-0.5 h-5 w-5 shrink-0 text-amber" />
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted">
                    {winner.label || winner.award}
                  </div>
                  <WinnerLink winner={winner} className="mt-0.5 block font-display text-lg font-bold leading-tight hover:text-amber" />
                  <div className="mt-0.5 text-xs text-muted">
                    {[winner.team_id, winner.metric].filter(Boolean).join(" · ")}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      {gloves.length > 0 && (
        <PositionAwardsCard
          title="Gold Gloves"
          description="The best fielder at each position: mostly his fielding ratings, adjusted by his season's fielding numbers."
          winners={gloves}
          positions={GLOVE_POSITIONS}
        />
      )}
      {sluggers.length > 0 && (
        <PositionAwardsCard
          title="Silver Sluggers"
          description="The best hitter at each position by OPS (three outfielders), with 2 plate appearances per team game."
          winners={sluggers}
          positions={SLUGGER_POSITIONS}
        />
      )}
    </div>
  );
}

function WinnerLink({ winner, className }: { winner: AwardWinner; className?: string }) {
  if (!winner.player_id) return <span className={className}>{winner.player_name || "—"}</span>;
  return (
    <Link to={`/player/${encodeURIComponent(winner.player_id)}`} className={className}>
      {winner.player_name || "—"}
    </Link>
  );
}

/** Gold Gloves / Silver Sluggers: a row per position, a column per league. */
function PositionAwardsCard({
  title,
  description,
  winners,
  positions,
}: {
  title: string;
  description: string;
  winners: AwardWinner[];
  positions: string[];
}) {
  const leagues = Array.from(new Set(winners.map((w) => w.league || ""))).sort();
  const rows = positions.filter((pos) => winners.some((w) => (w.position || "") === pos));
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Award className="h-4 w-4 text-amber" />
            {title}
          </CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <th className="px-4 py-2 text-left font-semibold">Pos</th>
              {leagues.map((league) => (
                <th key={league} className="px-3 py-2 text-left font-semibold">
                  {league || "Winner"}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((pos) => (
              <tr key={pos} className="border-b border-border/40 align-top last:border-b-0">
                <td className="px-4 py-2 font-mono text-xs font-semibold">{pos}</td>
                {leagues.map((league) => {
                  const cell = winners.filter(
                    (w) => (w.position || "") === pos && (w.league || "") === league,
                  );
                  return (
                    <td key={league} className="px-3 py-2">
                      {cell.length === 0 ? (
                        <span className="text-muted">—</span>
                      ) : (
                        cell.map((w) => (
                          <div key={w.award} className="py-0.5">
                            <WinnerLink winner={w} className="font-semibold hover:text-amber" />
                            {w.team_id && <span className="ml-1 text-xs text-muted">{w.team_id}</span>}
                            {w.metric && <div className="text-xs text-muted">{w.metric}</div>}
                          </div>
                        ))
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
