/**
 * Phase 4 port of ui/player_profile_dialog_v2.py.
 *
 * Reads the same view-model the PyQt build composes
 * (``ui.player_profile_v2_viewmodel.build_player_profile_view_model``) and
 * lays it out as a scannable profile page: bio header with overall +
 * scouting confidence, two-column ratings cards, training focus,
 * stats table, contract details, and injury history.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowLeftRight,
  ChevronRight,
  Handshake,
  Loader2,
  Pencil,
  RefreshCw,
  ShieldCheck,
  Star,
  Stethoscope,
  Target,
  Trophy,
} from "lucide-react";

import {
  api,
  ApiError,
  type ExtensionEligibility,
  type ExtensionEvaluation,
  type ExtensionRejection,
  type PlayerProfile,
  type PlayerProfileNote,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { isCloud } from "@/lib/cloud-auth";
import { toast } from "@/lib/toast-store";
import { AppShell } from "@/components/layout/AppShell";
import { OfferImpactPanel } from "@/components/OfferImpactPanel";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { PlayerPickerDialog } from "@/components/PlayerPickerDialog";
import { PlayerTrainingDialog } from "@/components/PlayerTrainingDialog";
import { RollingStatsChart } from "@/components/RollingStatsChart";
import { SprayChart } from "@/components/SprayChart";
import { StarRating } from "@/components/StarRating";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import { useLeagueCapabilities } from "@/lib/league-capabilities";

export function PlayerProfilePage() {
  const { playerId } = useParams<{ playerId: string }>();
  const navigate = useNavigate();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [trainingOpen, setTrainingOpen] = useState(false);
  const userTeamId = useAuthStore(
    (s) => s.selectedTeamId ?? s.teamId,
  );
  const profile = useQuery({
    queryKey: ["player-profile", playerId],
    queryFn: () => api.playerProfile(playerId as string),
    enabled: !!playerId,
  });
  // "Trade for Player" only makes sense when:
  //   - the player is on a real team (not a free agent — that's a sign,
  //     not a trade), and
  //   - the user has a team of their own to trade from, and
  //   - it's somebody else's team.
  const canTradeFor = !!(
    profile.data?.team_id &&
    userTeamId &&
    profile.data.team_id !== userTeamId
  );

  return (
    <AppShell
      title={profile.data?.full_name ?? "Player"}
      subtitle={
        profile.data
          ? `${profile.data.team_id || "Free Agent"} · ${profile.data.positions_text}`
          : "Loading…"
      }
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        <div className="flex items-center gap-2">
          {canTradeFor && profile.data && playerId && userTeamId && (
            <Button
              onClick={() =>
                navigate("/trades", {
                  state: {
                    proposeTrade: {
                      fromTeam: userTeamId,
                      toTeam: profile.data?.team_id ?? "",
                      receivePlayers: [playerId],
                    },
                  },
                })
              }
              title={`Open Propose Trade with ${profile.data.full_name} from ${profile.data.team_id} pre-loaded`}
            >
              <Handshake className="h-4 w-4" /> Trade for Player
            </Button>
          )}
          {profile.data && (
            <Button variant="outline" onClick={() => setPickerOpen(true)}>
              <ArrowLeftRight className="h-4 w-4" /> Compare
            </Button>
          )}
        </div>
      </div>

      {playerId && (
        <PlayerPickerDialog
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          excludeId={playerId}
          title="Pick a player to compare"
          description={`Compare side-by-side with ${profile.data?.full_name ?? "this player"}.`}
          onPick={(pid) =>
            navigate(
              `/compare/${encodeURIComponent(playerId)}/${encodeURIComponent(pid)}`,
            )
          }
        />
      )}
      {playerId && profile.data && (
        <PlayerTrainingDialog
          open={trainingOpen}
          onOpenChange={setTrainingOpen}
          playerId={playerId}
          playerName={profile.data.full_name}
          teamId={profile.data.team_id || null}
        />
      )}

      {profile.isLoading ? (
        <LoadingCard />
      ) : profile.isError ? (
        <ErrorCard message={(profile.error as Error).message} />
      ) : profile.data ? (
        <div className="space-y-6 animate-fade-in">
          <HeroCard profile={profile.data} />
          <RatingsRow profile={profile.data} />
          <StatsCard profile={profile.data} />
          <CareerLedgerCard profile={profile.data} />
          {profile.data.training_focus && (
            <TrainingCard
              focus={profile.data.training_focus}
              onEdit={() => setTrainingOpen(true)}
            />
          )}
          {!profile.data.is_pitcher && (
            <SprayChartCard profile={profile.data} />
          )}
          <RollingStatsCard profile={profile.data} />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <DetailsCard
              title="Overall"
              icon={<Star className="h-3 w-3" />}
              rows={profile.data.overall_details}
            />
            <ContractCard
              rows={profile.data.contract_details}
              contractMeta={profile.data.contract_meta}
              playerId={playerId ?? null}
              playerName={profile.data.full_name}
              ownsPlayer={
                !!profile.data.team_id &&
                !!userTeamId &&
                profile.data.team_id === userTeamId
              }
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

/** Backend ``overall_stars_text`` is a pre-formatted 1-5 string like
 *  ``"4"`` or ``"4.5"``. Parse it back to a float for the star renderer;
 *  fall back to 0 so the row stays visually stable. */
function parseStarValue(raw: string | null | undefined): number {
  if (!raw) return 0;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

function HeroCard({ profile }: { profile: PlayerProfile }) {
  // Per-player AI avatar regenerate — SUPER-ADMIN ONLY (platform owner). Lets the
  // admin spot-check avatar look/colors cheaply before a full-league regenerate.
  const [avatarVersion, setAvatarVersion] = useState(0);
  const me = useQuery({
    queryKey: ["account-me"],
    queryFn: () => api.accountMe(),
    enabled: isCloud(),
    staleTime: 5 * 60_000,
  });
  const isSuperAdmin = isCloud() && !!me.data?.super_admin;
  const regen = useMutation({
    mutationFn: () => api.regeneratePlayerAvatar(profile.player_id),
    onSuccess: () => {
      setAvatarVersion((v) => v + 1);
      toast.success("Avatar regenerated");
    },
    onError: (err: unknown) =>
      toast.error("Couldn't regenerate avatar", {
        description: err instanceof Error ? err.message : "Try again.",
      }),
  });

  return (
    <Card className="p-6">
      <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-5">
          <div className="relative shrink-0">
            <PlayerAvatar
              playerId={profile.player_id}
              initials={profile.initials}
              version={avatarVersion}
              className="h-32 w-32 shrink-0 overflow-hidden rounded-2xl text-5xl shadow-panel"
            />
            {isSuperAdmin && (
              <button
                type="button"
                onClick={() => regen.mutate()}
                disabled={regen.isPending}
                title="Regenerate this player's AI avatar (super-admin)"
                aria-label="Regenerate avatar"
                className="absolute -bottom-1 -right-1 rounded-full border border-border bg-surface p-1.5 text-muted shadow-panel transition hover:text-amber disabled:opacity-60"
              >
                {regen.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
              </button>
            )}
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
            <div className="mt-1 flex justify-end">
              <StarRating
                value={parseStarValue(profile.overall_stars_text)}
                size="h-3.5 w-3.5"
              />
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

function SprayChartCard({ profile }: { profile: PlayerProfile }) {
  // First stats row is the most-relevant season (typically the current
  // year). Look up raw hit counts by key; the view-model stores both
  // ``b2`` and ``2b`` aliases so we fall back across both.
  const row = profile.stats_rows[0];
  if (!row) return null;
  const [label, data] = row;

  const num = (key: string, alt?: string): number => {
    const raw = data[key] ?? (alt ? data[alt] : undefined);
    const n = Number(raw);
    return Number.isFinite(n) ? n : 0;
  };
  const singles = num("b1", "1b");
  const doubles = num("b2", "2b");
  const triples = num("b3", "3b");
  const homers = num("hr");
  if (singles + doubles + triples + homers <= 0) return null;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Spray chart</CardTitle>
          <CardDescription>
            {label} · dots placed from hit totals + handedness (synthetic, not
            batted-ball coordinates)
          </CardDescription>
        </div>
        <Badge tone="amber">
          <Target className="h-3 w-3" /> {singles + doubles + triples + homers} hits
        </Badge>
      </CardHeader>
      <CardContent>
        <SprayChart
          playerId={profile.player_id}
          bats={profile.bats_text}
          singles={singles}
          doubles={doubles}
          triples={triples}
          homers={homers}
        />
      </CardContent>
    </Card>
  );
}

function TrainingCard({
  focus,
  onEdit,
}: {
  focus: NonNullable<PlayerProfile["training_focus"]>;
  onEdit?: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Training focus</CardTitle>
          <CardDescription>{focus.source_text}</CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="amber">
            <Target className="h-3 w-3" /> Active
          </Badge>
          {onEdit && (
            <Button variant="outline" size="sm" onClick={onEdit}>
              Edit for player
            </Button>
          )}
        </div>
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

function RollingStatsCard({ profile }: { profile: PlayerProfile }) {
  const rolling = profile.rolling_stats;
  if (!rolling || rolling.dates.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Rolling metrics</CardTitle>
          <CardDescription>
            {profile.is_pitcher
              ? "ERA and WHIP across the most recent season-history snapshots."
              : "AVG and OPS across the most recent season-history snapshots."}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <RollingStatsChart dates={rolling.dates} series={rolling.series} />
      </CardContent>
    </Card>
  );
}

function CareerLedgerCard({ profile }: { profile: PlayerProfile }) {
  const ratings = profile.ratings_history ?? [];
  const awards = profile.awards_history ?? [];
  const transactions = profile.transactions_log ?? [];
  const trades = profile.trade_log ?? [];
  const springGains = profile.spring_training_gains ?? null;

  if (
    ratings.length === 0 &&
    awards.length === 0 &&
    transactions.length === 0 &&
    trades.length === 0
  ) {
    return null;
  }

  // Keep the PyQt tab order so the muscle memory lines up.
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Career ledger</CardTitle>
          <CardDescription>
            Year-by-year ratings, awards, and transaction history.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <Tabs defaultValue="ratings" className="px-3 pb-3">
          <TabsList>
            <TabsTrigger value="ratings">Ratings</TabsTrigger>
            <TabsTrigger value="awards">Awards</TabsTrigger>
            <TabsTrigger value="transactions">Transactions</TabsTrigger>
            <TabsTrigger value="trades">Trades</TabsTrigger>
          </TabsList>
          <TabsContent value="ratings">
            <RatingsHistoryTable
              rows={ratings}
              isPitcher={profile.is_pitcher}
              springGains={springGains}
            />
          </TabsContent>
          <TabsContent value="awards">
            <AwardsTable rows={awards} />
          </TabsContent>
          <TabsContent value="transactions">
            <TransactionsTable rows={transactions} />
          </TabsContent>
          <TabsContent value="trades">
            <TransactionsTable rows={trades} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function RatingsHistoryTable({
  rows,
  isPitcher,
  springGains,
}: {
  rows: NonNullable<PlayerProfile["ratings_history"]>;
  isPitcher: boolean;
  springGains?: PlayerProfile["spring_training_gains"] | null;
}) {
  const columns = isPitcher
    ? [
        { key: "endurance", label: "END" },
        { key: "control", label: "CTRL" },
        { key: "movement", label: "MOV" },
        { key: "arm", label: "AS" },
        { key: "fa", label: "FA" },
      ]
    : [
        { key: "ch", label: "CH" },
        { key: "ph", label: "PH" },
        { key: "sp", label: "SP" },
        { key: "eye", label: "EYE" },
        { key: "fa", label: "FA" },
        { key: "arm", label: "ARM" },
      ];
  if (rows.length === 0) {
    return <EmptyPanel message="No historical ratings recorded yet." />;
  }

  // Spring-training gains apply to the most recent row only; the older
  // year snapshots already capture their own deltas as part of the
  // year-to-year arc.
  const lastIdx = rows.length - 1;
  const gainsByStat: Record<string, number> = {};
  if (springGains?.changes) {
    for (const [k, v] of Object.entries(springGains.changes)) {
      const n = Number(v);
      if (Number.isFinite(n) && n !== 0) {
        gainsByStat[k] = n;
      }
    }
  }
  const hasAnyGain = Object.keys(gainsByStat).length > 0;

  return (
    <div className="overflow-x-auto">
      {hasAnyGain && (
        <div className="px-4 pt-2 pb-1 text-[11px] text-muted">
          Green <span className="text-success font-semibold">(+x)</span> tags
          show this season's spring-training gains
          {springGains?.focus ? ` · focus: ${springGains.focus}` : ""}.
        </div>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
            <th className="px-4 py-2 text-left font-semibold">Year</th>
            {columns.map((c) => (
              <th key={c.key} className="px-3 py-2 text-right font-semibold">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr
              key={row.label}
              className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
            >
              <td className="px-4 py-2 font-mono text-xs">{row.label}</td>
              {columns.map((c) => {
                const v = row.ratings[c.key];
                const gain =
                  idx === lastIdx ? gainsByStat[c.key] ?? 0 : 0;
                return (
                  <td
                    key={c.key}
                    className="px-3 py-2 text-right tabular-nums"
                  >
                    {v == null ? (
                      <span className="text-subtle">—</span>
                    ) : (
                      <span className="inline-flex items-baseline gap-1 justify-end">
                        <span>{Math.round(v)}</span>
                        {gain !== 0 && (
                          <span
                            className={
                              gain > 0
                                ? "text-[10px] font-semibold text-success"
                                : "text-[10px] font-semibold text-danger"
                            }
                            title={`Spring training change: ${gain > 0 ? "+" : ""}${gain}`}
                          >
                            ({gain > 0 ? "+" : ""}
                            {gain})
                          </span>
                        )}
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AwardsTable({
  rows,
}: {
  rows: NonNullable<PlayerProfile["awards_history"]>;
}) {
  if (rows.length === 0) {
    return <EmptyPanel message="No awards recorded yet." />;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
            <th className="px-4 py-2 text-left font-semibold">Year</th>
            <th className="px-3 py-2 text-left font-semibold">Award</th>
            <th className="px-3 py-2 text-left font-semibold">Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={`${row.year}-${row.award}-${i}`}
              className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
            >
              <td className="px-4 py-2 font-mono text-xs">{row.year || "—"}</td>
              <td className="px-3 py-2 font-semibold">{row.award}</td>
              <td className="px-3 py-2 text-muted">{row.description || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TransactionsTable({
  rows,
}: {
  rows: NonNullable<PlayerProfile["transactions_log"]>;
}) {
  if (rows.length === 0) {
    return <EmptyPanel message="No transactions recorded yet." />;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
            <th className="px-4 py-2 text-left font-semibold">Date</th>
            <th className="px-3 py-2 text-left font-semibold">Description</th>
            <th className="px-3 py-2 text-right font-semibold">From</th>
            <th className="px-3 py-2 text-right font-semibold">To</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={`${row.date}-${i}`}
              className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
            >
              <td className="px-4 py-2 font-mono text-xs">{row.date || "—"}</td>
              <td className="px-3 py-2">{row.description || "—"}</td>
              <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                {row.from_team || "—"}
              </td>
              <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                {row.to_team || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmptyPanel({ message }: { message: string }) {
  return (
    <div className="px-4 py-6 text-sm text-muted">{message}</div>
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

type ContractMeta = {
  team_id: string;
  annual_salary: number;
  service_time_days: number;
  arb_eligible: boolean;
  options: Array<{
    type?: string;
    label?: string;
    salary?: number;
    decision?: string;
    buyout?: number;
  }>;
};

function ContractCard({
  rows,
  contractMeta,
  playerId,
  playerName,
  ownsPlayer,
}: {
  rows: Array<[string, string]>;
  contractMeta?: ContractMeta;
  playerId: string | null;
  playerName: string;
  ownsPlayer: boolean;
}) {
  const queryClient = useQueryClient();
  const capabilities = useLeagueCapabilities();
  const advancedContracts =
    (capabilities.modules?.gm_contracts ?? "off") === "advanced";
  const [open, setOpen] = useState(false);
  const [years, setYears] = useState("1");
  const [salary, setSalary] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<ExtensionEvaluation | null>(null);
  const [ineligibility, setIneligibility] = useState<ExtensionEligibility | null>(
    null,
  );

  // Pull initial fair-market estimate (with the existing salary as the
  // implied offer) the moment the dialog opens. Re-runs whenever the
  // user edits the form.
  const previewQ = useQuery({
    queryKey: [
      "extension-preview",
      playerId,
      years,
      salary,
    ],
    queryFn: () =>
      api.evaluateExtension(playerId!, {
        years: Number(years) || 1,
        annual_salary: salary ? Number(salary) : undefined,
      }),
    enabled: open && !!playerId,
  });

  // Surface ineligibility from the preview so the form gates BEFORE
  // the user wastes time crafting an offer.
  const eligibilityFromPreview = previewQ.data?.eligibility ?? null;
  const isIneligible =
    !!eligibilityFromPreview && eligibilityFromPreview.eligible === false;

  const extendMut = useMutation({
    mutationFn: () =>
      api.extendContract(playerId!, {
        additional_years: Number(years) || 1,
        annual_salary: salary ? Number(salary) : undefined,
      }),
    onSuccess: (data) => {
      // Confirm the acceptance — an accepted extension used to close silently.
      const agreedYears = Number(years) || 1;
      const agreedSalary = salary ? Number(salary) : undefined;
      setOpen(false);
      setError(null);
      setSalary("");
      setYears("1");
      setResponse(null);
      setIneligibility(null);
      queryClient.invalidateQueries({ queryKey: ["player-profile", playerId] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      queryClient.invalidateQueries({ queryKey: ["team-roster"] });
      toast.success(`${playerName} accepted the extension`, {
        description: `+${agreedYears} year${agreedYears === 1 ? "" : "s"}${
          agreedSalary ? ` at $${agreedSalary.toLocaleString()}/yr` : " at market value"
        }.`,
      });
      void data;
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as { detail?: ExtensionRejection } | undefined;
        const detail = body?.detail;
        // Server returns one of: countered/rejected (negotiation result)
        // OR an eligibility code (phase_blocked, fa_year_lockout, etc.)
        if (detail?.eligibility) {
          setIneligibility(detail.eligibility);
          setResponse(null);
          setError(null);
          return;
        }
        if (detail?.negotiation) {
          setResponse(detail.negotiation);
          setIneligibility(null);
          setError(null);
          return;
        }
      }
      setResponse(null);
      setIneligibility(null);
      setError((err as Error).message);
    },
  });

  function acceptCounter() {
    if (!response) return;
    if (response.counter_salary != null) {
      setSalary(String(response.counter_salary));
    }
    if (response.counter_years != null) {
      setYears(String(response.counter_years));
    }
    setResponse(null);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Contract</CardTitle>
        <div className="flex items-center gap-2">
          {ownsPlayer && playerId && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setOpen(true);
                setError(null);
                setResponse(null);
              }}
              title="Negotiate an extension with this player"
            >
              <Pencil className="mr-1 h-3 w-3" /> Negotiate
            </Button>
          )}
          <Badge tone="neutral">
            <Trophy className="h-3 w-3" />
          </Badge>
        </div>
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
        {ownsPlayer && playerId && advancedContracts && contractMeta ? (
          <OwnerContractActions playerId={playerId} meta={contractMeta} />
        ) : null}
      </CardContent>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <Card className="w-full max-w-lg">
            <CardHeader>
              <div>
                <CardTitle>Negotiate extension · {playerName}</CardTitle>
                <CardDescription>
                  Make the player an offer. They'll evaluate based on
                  market value, age, and service time.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* Ineligibility banner — render first so the user
                  immediately understands why the form is disabled. */}
              {(ineligibility || (isIneligible && eligibilityFromPreview)) && (
                <div className="rounded-md border border-warning/50 bg-warning/10 px-3 py-2 text-xs text-warning">
                  <div className="font-semibold uppercase tracking-wider">
                    Cannot negotiate right now
                  </div>
                  <div className="mt-1 leading-snug">
                    {(ineligibility ?? eligibilityFromPreview!).reason}
                  </div>
                </div>
              )}

              {/* Fair-market hint — refreshes as user types. */}
              {previewQ.data && (
                <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs">
                  <div className="font-semibold text-muted uppercase tracking-wider">
                    Market estimate
                  </div>
                  <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1">
                    <span className="text-muted">Fair salary</span>
                    <span className="text-right tabular-nums font-semibold">
                      ${previewQ.data.fair_market_salary.toLocaleString()}/yr
                    </span>
                    <span className="text-muted">Fair length</span>
                    <span className="text-right tabular-nums font-semibold">
                      {previewQ.data.fair_market_years} yrs
                    </span>
                    <span className="text-muted">Service tier</span>
                    <span className="text-right text-xs uppercase">
                      {previewQ.data.service_tier.replace("_", " ")}
                    </span>
                    {previewQ.data.current_annual_salary != null && (
                      <>
                        <span className="text-muted">Current salary</span>
                        <span className="text-right tabular-nums">
                          ${previewQ.data.current_annual_salary.toLocaleString()}/yr
                        </span>
                      </>
                    )}
                  </div>
                </div>
              )}

              {previewQ.data?.payroll_impact &&
                (previewQ.data.payroll_impact.active ||
                  previewQ.data.payroll_impact.info) && (
                  <OfferImpactPanel impact={previewQ.data.payroll_impact} />
                )}

              <label className="block space-y-1">
                <span className="text-xs font-semibold uppercase tracking-wider text-muted">
                  Additional years
                </span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={years}
                  onChange={(e) => setYears(e.target.value)}
                  className="h-9 w-full rounded-md border border-border bg-canvas/60 px-2 text-sm"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-semibold uppercase tracking-wider text-muted">
                  Annual salary
                </span>
                <input
                  type="number"
                  min={0}
                  step={50000}
                  value={salary}
                  onChange={(e) => setSalary(e.target.value)}
                  placeholder={
                    previewQ.data
                      ? `Defaults to current ($${previewQ.data.current_annual_salary?.toLocaleString() ?? ""})`
                      : "Annual salary $"
                  }
                  className="h-9 w-full rounded-md border border-border bg-canvas/60 px-2 text-sm"
                />
              </label>

              {/* Player's response on rejection / counter-offer */}
              {response && (
                <div
                  className={cn(
                    "rounded-md border px-3 py-2 text-xs",
                    response.decision === "rejected"
                      ? "border-danger/40 bg-danger/10 text-danger"
                      : "border-amber/60 bg-amber/10 text-amber-text",
                  )}
                >
                  <div className="font-semibold uppercase tracking-wider">
                    {response.decision === "rejected"
                      ? "Player rejected the offer"
                      : "Player countered"}
                  </div>
                  <div className="mt-1 leading-snug">{response.reason}</div>
                  {response.decision === "countered" && response.counter_salary && (
                    <button
                      type="button"
                      onClick={acceptCounter}
                      className="mt-2 inline-flex items-center gap-1 rounded border border-amber/60 bg-amber/20 px-2 py-1 text-xs font-semibold uppercase tracking-wider text-amber-text hover:bg-amber/30"
                    >
                      Use ${response.counter_salary.toLocaleString()}/yr ×{" "}
                      {response.counter_years} yrs
                    </button>
                  )}
                </div>
              )}

              {error && (
                <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger">
                  {error}
                </div>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setOpen(false)}
                  disabled={extendMut.isPending}
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => {
                    setResponse(null);
                    setIneligibility(null);
                    extendMut.mutate();
                  }}
                  disabled={extendMut.isPending || isIneligible || !!ineligibility}
                  title={
                    isIneligible || ineligibility
                      ? "Player isn't open to extension talks right now"
                      : ""
                  }
                >
                  {extendMut.isPending ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : null}
                  Submit offer
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </Card>
  );
}

function OwnerContractActions({
  playerId,
  meta,
}: {
  playerId: string;
  meta: ContractMeta;
}) {
  const queryClient = useQueryClient();
  const [renewSalary, setRenewSalary] = useState("");
  const fmt = (n: number) => "$" + Math.round(n || 0).toLocaleString();
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["player-profile", playerId] });

  const optionMut = useMutation({
    mutationFn: (vars: { index: number; decision: "exercised" | "declined" }) =>
      api.decideContractOption(playerId, vars.decision, vars.index),
    onSuccess: invalidate,
  });
  const renewMut = useMutation({
    mutationFn: () => api.renewContract(playerId, Number(renewSalary) || 0),
    onSuccess: () => {
      const amt = Number(renewSalary) || 0;
      setRenewSalary("");
      invalidate();
      toast.success("Contract renewed", {
        description: amt
          ? `Renewed at $${amt.toLocaleString()}/yr.`
          : "Renewed at the pre-arbitration figure.",
      });
    },
  });

  const pendingOptions = (meta.options ?? [])
    .map((o, i) => ({ ...o, index: i }))
    .filter((o) => (o.decision ?? "pending") === "pending");
  const preArb = !meta.arb_eligible && meta.service_time_days < 3 * 162;

  if (pendingOptions.length === 0 && !preArb) return null;

  return (
    <div className="space-y-3 border-t border-border/60 px-6 py-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        Owner actions
      </div>

      {pendingOptions.map((o) => (
        <div
          key={o.index}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surfaceAlt/40 px-3 py-2 text-sm"
        >
          <span>
            {(o.type ?? "team")} option
            {o.salary ? ` · ${fmt(o.salary)}` : ""}
            {o.buyout ? ` · buyout ${fmt(o.buyout)}` : ""}
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={optionMut.isPending}
              onClick={() => optionMut.mutate({ index: o.index, decision: "exercised" })}
            >
              Exercise
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={optionMut.isPending}
              onClick={() => optionMut.mutate({ index: o.index, decision: "declined" })}
            >
              Decline
            </Button>
          </div>
        </div>
      ))}

      {preArb ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surfaceAlt/40 px-3 py-2 text-sm">
          <span>Renew (pre-arb) · current {fmt(meta.annual_salary)}</span>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={0}
              placeholder="New salary"
              className="w-32"
              value={renewSalary}
              onChange={(e) => setRenewSalary(e.target.value)}
            />
            <Button
              size="sm"
              disabled={renewMut.isPending || !renewSalary}
              onClick={() => renewMut.mutate()}
            >
              Renew
            </Button>
          </div>
        </div>
      ) : null}

      {optionMut.isError || renewMut.isError ? (
        <div className="text-xs text-danger">
          {((optionMut.error || renewMut.error) as Error)?.message ?? "Action failed."}
        </div>
      ) : null}
    </div>
  );
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
