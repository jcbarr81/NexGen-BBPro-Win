/**
 * Phase 4 port of ui/player_profile_dialog_v2.py.
 *
 * Reads the same view-model the PyQt build composes
 * (``ui.player_profile_v2_viewmodel.build_player_profile_view_model``) and
 * lays it out as a scannable profile page: bio header with overall +
 * scouting confidence, two-column ratings cards, training focus,
 * stats table, contract details, and injury history.
 */

import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  Loader2,
  ShieldCheck,
  Star,
  Stethoscope,
  Target,
  Trophy,
  User,
} from "lucide-react";

import {
  api,
  type PlayerProfile,
  type PlayerProfileNote,
} from "@/lib/api";
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
import { cn } from "@/lib/cn";

export function PlayerProfilePage() {
  const { playerId } = useParams<{ playerId: string }>();
  const navigate = useNavigate();
  const profile = useQuery({
    queryKey: ["player-profile", playerId],
    queryFn: () => api.playerProfile(playerId as string),
    enabled: !!playerId,
  });

  return (
    <AppShell
      title={profile.data?.full_name ?? "Player"}
      subtitle={
        profile.data
          ? `${profile.data.team_id || "Free Agent"} · ${profile.data.positions_text}`
          : "Loading…"
      }
    >
      <div className="mb-4">
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
      </div>

      {profile.isLoading ? (
        <LoadingCard />
      ) : profile.isError ? (
        <ErrorCard message={(profile.error as Error).message} />
      ) : profile.data ? (
        <div className="space-y-6 animate-fade-in">
          <HeroCard profile={profile.data} />
          <RatingsRow profile={profile.data} />
          {profile.data.training_focus && (
            <TrainingCard focus={profile.data.training_focus} />
          )}
          <StatsCard profile={profile.data} />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <DetailsCard
              title="Overall"
              icon={<Star className="h-3 w-3" />}
              rows={profile.data.overall_details}
            />
            <DetailsCard
              title="Contract"
              icon={<Trophy className="h-3 w-3" />}
              rows={profile.data.contract_details}
            />
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <NotesCard
              title="Recent Training"
              icon={<Target className="h-3 w-3" />}
              entries={profile.data.recent_training_entries}
              empty="No training notes recorded."
            />
            <NotesCard
              title="Injury History"
              icon={<Stethoscope className="h-3 w-3" />}
              entries={profile.data.injury_history}
              empty="No injuries on record."
            />
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}

function HeroCard({ profile }: { profile: PlayerProfile }) {
  return (
    <Card className="p-6">
      <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-5">
          <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl border border-border bg-surfaceAlt font-display text-3xl font-bold text-amber-text shadow-panel">
            {profile.initials || <User className="h-8 w-8" />}
          </div>
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
              {profile.team_id ? (
                <Link
                  to="/roster"
                  className="hover:text-amber"
                >
                  {profile.team_id} ROSTER
                </Link>
              ) : (
                "FREE AGENT"
              )}
            </div>
            <h2 className="font-display text-3xl font-bold">
              {profile.full_name}
            </h2>
            <div className="text-sm text-muted">
              {profile.positions_text} · {profile.bats_text}/{profile.throws_text}{" "}
              · {profile.age_text} yrs · {profile.height_text} ·{" "}
              {profile.weight_text}
              {profile.role_text ? ` · ${profile.role_text}` : ""}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-right">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
              Overall
            </div>
            <div className="font-display text-3xl font-bold leading-none text-amber-text">
              {profile.overall_display != null
                ? Math.round(profile.overall_display)
                : "—"}
            </div>
            <div className="mt-1 text-xs text-amber">
              {profile.overall_stars_text}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
              Health
            </div>
            <div className="text-sm font-semibold">{profile.health_status}</div>
            <div className="mt-1 flex items-center justify-end gap-1 text-xs text-muted">
              <ShieldCheck className="h-3 w-3" />
              {profile.scouting_confidence_text}
            </div>
          </div>
        </div>
      </div>

      {profile.scouting_summary && (
        <p className="relative mt-4 border-t border-border/60 pt-4 text-sm leading-relaxed text-muted">
          {profile.scouting_summary}
        </p>
      )}
    </Card>
  );
}

function RatingsRow({ profile }: { profile: PlayerProfile }) {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      <RatingsCard
        title="Headline"
        rows={profile.header_metrics}
        emphasize
      />
      <RatingsCard
        title={profile.is_pitcher ? "Pitching" : "Hitting"}
        rows={profile.overview_ratings}
      />
      <RatingsCard title="Defense" rows={profile.defense_ratings} />
    </div>
  );
}

function RatingsCard({
  title,
  rows,
  emphasize = false,
}: {
  title: string;
  rows: Array<[string, string]>;
  emphasize?: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">No data.</div>
        ) : (
          // Definition list so screen readers read each row as
          // "<label>: <value>". Visual layout is the same as the old <ul>.
          <dl className="divide-y divide-border/60">
            {rows.map(([label, value], i) => (
              <div
                key={`${label}-${i}`}
                className="flex items-center justify-between px-6 py-2 text-sm"
              >
                <dt className="text-muted">{label}</dt>
                <dd
                  className={cn(
                    "tabular-nums",
                    emphasize ? "font-display text-base text-amber-text" : "font-semibold",
                  )}
                  aria-label={`${label}: ${value || "not set"}`}
                >
                  {value || "—"}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function TrainingCard({
  focus,
}: {
  focus: NonNullable<PlayerProfile["training_focus"]>;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Training focus</CardTitle>
          <CardDescription>{focus.source_text}</CardDescription>
        </div>
        <Badge tone="amber">
          <Target className="h-3 w-3" /> Active
        </Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <FocusBlock label="Hitters" body={focus.hitters_text} />
        <FocusBlock label="Pitchers" body={focus.pitchers_text} />
      </CardContent>
    </Card>
  );
}

function FocusBlock({ label, body }: { label: string; body: string }) {
  return (
    <div className="rounded-xl border border-border bg-surfaceAlt/40 p-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        {label}
      </div>
      <p className="mt-1 text-sm">{body || "—"}</p>
    </div>
  );
}

function StatsCard({ profile }: { profile: PlayerProfile }) {
  if (profile.stats_rows.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Statistics</CardTitle>
          <CardDescription>
            {profile.is_pitcher ? "Pitching lines" : "Batting lines"} by season
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <th className="px-6 py-2 text-left font-semibold">Season</th>
              {profile.stats_columns.map((col) => (
                <th
                  key={col}
                  className="px-2 py-2 text-right font-semibold tabular-nums"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {profile.stats_rows.map(([label, row], i) => (
              <tr
                key={`${label}-${i}`}
                className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
              >
                <td className="px-6 py-2 font-semibold">{label}</td>
                {profile.stats_columns.map((col) => (
                  <td
                    key={col}
                    className="px-2 py-2 text-right tabular-nums"
                  >
                    {formatStat(row[col])}
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

function formatStat(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(3).replace(/^0/, "");
  }
  return String(value);
}

function DetailsCard({
  title,
  icon,
  rows,
}: {
  title: string;
  icon: React.ReactNode;
  rows: Array<[string, string]>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <Badge tone="neutral">{icon}</Badge>
      </CardHeader>
      <CardContent className="p-0">
        {rows.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">No details.</div>
        ) : (
          <ul className="divide-y divide-border/60">
            {rows.map(([label, value], i) => (
              <li
                key={`${label}-${i}`}
                className="flex items-center justify-between px-6 py-2 text-sm"
              >
                <span className="text-muted">{label}</span>
                <span className="font-semibold">{value || "—"}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function NotesCard({
  title,
  icon,
  entries,
  empty,
}: {
  title: string;
  icon: React.ReactNode;
  entries: PlayerProfileNote[];
  empty: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <Badge tone="neutral">
          {icon} {entries.length}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {entries.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">{empty}</div>
        ) : (
          <ul className="divide-y divide-border/60">
            {entries.map((entry, i) => (
              <li
                key={`${entry.title}-${i}`}
                className="flex items-start gap-3 px-6 py-3 text-sm"
              >
                <ChevronRight className="mt-0.5 h-3 w-3 text-amber" />
                <div>
                  <div className="font-semibold">{entry.title}</div>
                  {entry.detail && (
                    <div className="mt-0.5 text-xs text-muted">
                      {entry.detail}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading profile…</span>
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
