/**
 * Phase 4 port of ui/transactions_window.py.
 *
 * Full league activity ledger: every roster move, trade leg, signing,
 * release, DL placement, etc. The same data the legacy Transactions
 * window shows, fed by services.transaction_log.record_transaction calls
 * the sidecar already makes from roster + trade endpoints.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowLeftRight,
  HeartPulse,
  Loader2,
  Scissors,
  ShieldOff,
  Trophy,
  UserPlus,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

type Scope = "team" | "all";
type Filter =
  | "all"
  | "trades"
  | "assigns"
  | "cuts"
  | "injuries"
  | "signings";

const FILTER_ACTIONS: Record<Filter, string | undefined> = {
  all: undefined,
  trades: "trade_in,trade_out",
  assigns: "assign,promote,demote",
  cuts: "cut,release",
  injuries: "dl_in,dl_out,injury",
  signings: "sign,signing",
};

const FILTER_LABEL: Record<Filter, string> = {
  all: "All",
  trades: "Trades",
  assigns: "Roster moves",
  cuts: "Cuts",
  injuries: "Injuries",
  signings: "Signings",
};

export function ActivityPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const [scope, setScope] = useState<Scope>(teamId ? "team" : "all");
  const effectiveScope: Scope = teamId ? scope : "all";
  const [filter, setFilter] = useState<Filter>("all");

  const activity = useQuery({
    queryKey: ["activity", effectiveScope, teamId, filter],
    queryFn: () =>
      api.activity({
        teamId: effectiveScope === "team" ? (teamId as string) : undefined,
        action: FILTER_ACTIONS[filter],
        limit: 500,
      }),
  });

  const grouped = useMemo(() => {
    const rows = activity.data?.transactions ?? [];
    const map = new Map<string, typeof rows>();
    for (const row of rows) {
      const day = (row.season_date || row.timestamp || "").slice(0, 10) || "—";
      const arr = map.get(day) ?? [];
      arr.push(row);
      map.set(day, arr);
    }
    return [...map.entries()];
  }, [activity.data]);

  return (
    <AppShell
      title="Transactions"
      subtitle={
        effectiveScope === "team" && teamId
          ? `Activity for ${teamId}`
          : "League-wide activity ledger"
      }
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
          <Pill
            active={effectiveScope === "team"}
            disabled={!teamId}
            onClick={() => setScope("team")}
          >
            My team
          </Pill>
          <Pill
            active={effectiveScope === "all"}
            onClick={() => setScope("all")}
          >
            All teams
          </Pill>
        </div>
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
          {(Object.keys(FILTER_LABEL) as Filter[]).map((key) => (
            <Pill
              key={key}
              active={filter === key}
              onClick={() => setFilter(key)}
            >
              {FILTER_LABEL[key]}
            </Pill>
          ))}
        </div>
      </div>

      {activity.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading activity…</span>
          </CardContent>
        </Card>
      ) : activity.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(activity.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : grouped.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Activity className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">No activity yet</h2>
            <p className="max-w-sm text-sm text-muted">
              Roster moves, trades, signings, and DL placements will show up
              here as the league makes them.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {grouped.map(([day, rows]) => (
            <Card key={day}>
              <CardHeader>
                <div>
                  <CardTitle className="text-base">{formatDay(day)}</CardTitle>
                  <CardDescription>
                    {rows.length} {rows.length === 1 ? "event" : "events"}
                  </CardDescription>
                </div>
                <Badge tone="amber">
                  <Activity className="h-3 w-3" /> {day}
                </Badge>
              </CardHeader>
              <CardContent className="p-0">
                <ul className="divide-y divide-border/60">
                  {rows.map((row, i) => (
                    <ActivityRow key={`${day}-${i}`} row={row} />
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </AppShell>
  );
}

function ActivityRow({ row }: { row: Record<string, string> }) {
  const action = (row.action || "").toLowerCase();
  const Icon = iconFor(action);
  const tone = toneFor(action);
  const teamId = row.team_id || "";
  const playerId = row.player_id || "";
  return (
    <li className="flex items-start gap-3 px-6 py-2 text-sm">
      <div
        className={cn(
          "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border",
          tone,
        )}
      >
        <Icon className="h-3 w-3" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          {teamId && (
            <Link
              to={`/team/${encodeURIComponent(teamId)}`}
              className="font-semibold hover:text-amber"
            >
              {teamId}
            </Link>
          )}
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            {row.action || "—"}
          </span>
          {playerId && (
            <Link
              to={`/player/${encodeURIComponent(playerId)}`}
              className="font-semibold hover:text-amber"
            >
              {row.player_name || playerId}
            </Link>
          )}
          {row.from_level && row.to_level && (
            <span className="text-xs text-muted">
              {row.from_level} → {row.to_level}
            </span>
          )}
          {row.counterparty && (
            <span className="text-xs text-muted">
              · w/{" "}
              <Link
                to={`/team/${encodeURIComponent(row.counterparty)}`}
                className="hover:text-amber"
              >
                {row.counterparty}
              </Link>
            </span>
          )}
        </div>
        {row.details && (
          <div className="mt-0.5 text-[11px] text-muted">{row.details}</div>
        )}
      </div>
      <div className="shrink-0 text-right text-[10px] uppercase tracking-wider text-muted">
        {row.timestamp ? row.timestamp.slice(11, 16) : ""}
      </div>
    </li>
  );
}

function Pill({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
        active
          ? "bg-amber text-espresso"
          : "text-muted hover:bg-surface hover:text-ink",
        disabled && "pointer-events-none opacity-50",
      )}
    >
      {children}
    </button>
  );
}

function iconFor(action: string) {
  if (action.startsWith("trade")) return ArrowLeftRight;
  if (action === "cut" || action === "release") return Scissors;
  if (action.startsWith("dl") || action === "injury") return HeartPulse;
  if (action === "sign" || action === "signing") return UserPlus;
  if (action === "assign" || action === "promote" || action === "demote")
    return Trophy;
  if (action === "lock" || action === "lockout") return ShieldOff;
  return Activity;
}

function toneFor(action: string): string {
  if (action === "trade_in" || action === "sign" || action === "promote")
    return "border-success/40 bg-success/10 text-success";
  if (action === "trade_out" || action === "cut" || action === "release")
    return "border-danger/40 bg-danger/10 text-danger";
  if (action.startsWith("dl") || action === "injury")
    return "border-warning/40 bg-warning/10 text-warning";
  return "border-border bg-surfaceAlt text-muted";
}

function formatDay(day: string): string {
  if (!day || day === "—") return "Unknown date";
  const d = new Date(`${day}T00:00:00`);
  if (Number.isNaN(d.getTime())) return day;
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}
