/**
 * League awards browser.
 *
 * Lists every archived season's award winners (MVP, Cy Young, ROY,
 * Manager of the Year, etc.) — these are computed during the offseason
 * rollover and previously had no surface in the UI. Newest year first.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, Award, Loader2, Trophy } from "lucide-react";

import { api, type AwardSeason } from "@/lib/api";
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

function SeasonAwardCard({ season }: { season: AwardSeason }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Trophy className="h-4 w-4 text-amber" />
            {season.league_year ?? "Unknown year"} — Season Awards
          </CardTitle>
          <CardDescription>
            Final standings + statistical leaders are crowned at the end of
            the regular season.
          </CardDescription>
        </div>
        <Badge tone="amber">{season.awards.length}</Badge>
      </CardHeader>
      <CardContent className="p-0">
        <div className="grid grid-cols-1 gap-px bg-border md:grid-cols-2">
          {season.awards.map((winner) => (
            <div
              key={winner.award}
              className="flex items-start gap-3 bg-surface p-4"
            >
              <Award className="mt-0.5 h-5 w-5 shrink-0 text-amber" />
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold uppercase tracking-wider text-muted">
                  {winner.award}
                </div>
                <Link
                  to={
                    winner.player_id
                      ? `/player/${encodeURIComponent(winner.player_id)}`
                      : "#"
                  }
                  className="mt-0.5 block font-display text-lg font-bold leading-tight hover:text-amber"
                >
                  {winner.player_name || "—"}
                </Link>
                {winner.metric && (
                  <div className="mt-0.5 text-xs text-muted">
                    {winner.metric}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
