/**
 * Phase 4 port of ui/league_history_window.py.
 *
 * Lists every archived season with champion, runner-up, series result,
 * MVP, and Cy Young. Each row expands to show artifact links (champions
 * file, playoffs bracket, record book, etc.) for deeper inspection.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Archive,
  ChevronDown,
  ChevronRight,
  Crown,
  Loader2,
  Medal,
  Trophy,
} from "lucide-react";

import { api } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { cn } from "@/lib/cn";

export function LeagueHistoryPage() {
  const history = useQuery({
    queryKey: ["league-history"],
    queryFn: () => api.leagueHistory(),
  });

  return (
    <AppShell
      title="League History"
      subtitle="Past champions, MVPs, and archived season artifacts"
    >
      {history.isLoading ? (
        <LoadingCard />
      ) : history.isError ? (
        <ErrorCard message={(history.error as Error).message} />
      ) : !history.data || history.data.count === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Archive className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">No archived seasons</h2>
            <p className="max-w-sm text-sm text-muted">
              Finish a season to populate the league history.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {history.data.seasons.map((season) => (
            <SeasonRow key={season.season_id} season={season} />
          ))}
        </div>
      )}
    </AppShell>
  );
}

type Season = NonNullable<
  Awaited<ReturnType<typeof api.leagueHistory>>
>["seasons"][number];

function SeasonRow({ season }: { season: Season }) {
  const [open, setOpen] = useState(false);
  const artifacts = Object.entries(season.artifacts ?? {}).filter(
    ([, v]) => v,
  );
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface text-muted hover:bg-surfaceAlt hover:text-ink"
          >
            {open ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
          <div className="min-w-0">
            <CardTitle className="text-base">
              {season.league_year || season.season_id}
            </CardTitle>
            <CardDescription className="font-mono text-xs">
              {season.season_id}
              {season.ended_on ? ` · ended ${season.ended_on}` : ""}
              {season.archived_on ? ` · archived ${season.archived_on}` : ""}
            </CardDescription>
          </div>
        </div>
        <Badge tone={season.champion ? "amber" : "neutral"}>
          <Crown className="h-3 w-3" />{" "}
          {season.champion || "—"}
        </Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
        <Fact
          label="Champion"
          value={season.champion}
          Icon={Crown}
          tone="amber"
        />
        <Fact
          label="Runner-up"
          value={season.runner_up}
          Icon={Medal}
          tone="neutral"
        />
        <Fact
          label="Series"
          value={season.series_result}
          Icon={Trophy}
          tone="neutral"
        />
        <Fact label="MVP" value={season.mvp} Icon={Medal} tone="success" />
      </CardContent>
      {open && (
        <div className="border-t border-border/60 bg-surfaceAlt/40 px-6 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            Season artifacts
          </div>
          <div className="mt-2 grid grid-cols-1 gap-2 text-xs md:grid-cols-2">
            <Pair label="Cy Young" value={season.cy_young} />
            {artifacts.length > 0 ? (
              artifacts.map(([key, path]) => (
                <Pair key={key} label={key} value={path} mono />
              ))
            ) : (
              <Pair label="artifacts" value="—" />
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function Fact({
  label,
  value,
  Icon,
  tone,
}: {
  label: string;
  value: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  tone: "amber" | "success" | "neutral";
}) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-border bg-surfaceAlt/40 p-3">
      <div
        className={cn(
          "rounded-lg border border-border p-2",
          tone === "amber" && "text-amber",
          tone === "success" && "text-success",
        )}
      >
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
          {label}
        </div>
        <div className="truncate text-sm font-semibold" title={value || "—"}>
          {value || "—"}
        </div>
      </div>
    </div>
  );
}

function Pair({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start gap-2">
      <span className="w-24 shrink-0 text-[11px] font-semibold uppercase tracking-wider text-muted">
        {label}
      </span>
      <span
        className={cn(
          "truncate",
          mono && "font-mono text-[11px] text-muted",
        )}
        title={value}
      >
        {value || "—"}
      </span>
    </div>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading history…</span>
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
