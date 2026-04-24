/**
 * Side-by-side player comparison — ports the comparison panel from
 * ``ui/player_profile_dialog.py`` (opened via ``_prompt_comparison_player``).
 * Both profiles come from the existing ``/players/{id}/profile`` endpoint
 * and render as two HeroCard-style panels with a ratings diff between them.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowLeftRight,
  Loader2,
  Star,
} from "lucide-react";

import { api, type PlayerProfile } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { PlayerAvatar } from "@/components/PlayerAvatar";
import { PlayerPickerDialog } from "@/components/PlayerPickerDialog";
import { StarRating } from "@/components/StarRating";
import { cn } from "@/lib/cn";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui";

export function ComparePage() {
  const { playerA, playerB } = useParams<{ playerA: string; playerB: string }>();
  const navigate = useNavigate();
  const [swapOpen, setSwapOpen] = useState(false);

  const aQuery = useQuery({
    queryKey: ["player-profile", playerA],
    queryFn: () => api.playerProfile(playerA as string),
    enabled: !!playerA,
  });
  const bQuery = useQuery({
    queryKey: ["player-profile", playerB],
    queryFn: () => api.playerProfile(playerB as string),
    enabled: !!playerB,
  });

  const a = aQuery.data ?? null;
  const b = bQuery.data ?? null;
  const loading = aQuery.isLoading || bQuery.isLoading;
  const errored = aQuery.isError || bQuery.isError;

  return (
    <AppShell
      title="Compare"
      subtitle={
        a && b ? `${a.full_name} vs ${b.full_name}` : "Side-by-side player compare"
      }
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <Button variant="ghost" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" /> Back
        </Button>
        {a && (
          <Button variant="outline" onClick={() => setSwapOpen(true)}>
            <ArrowLeftRight className="h-4 w-4" /> Swap opponent
          </Button>
        )}
      </div>

      {loading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading both players…</span>
          </CardContent>
        </Card>
      ) : errored ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">
              {(aQuery.error as Error | null)?.message ||
                (bQuery.error as Error | null)?.message ||
                "Failed to load player profiles."}
            </span>
          </CardContent>
        </Card>
      ) : a && b ? (
        <div className="space-y-6 animate-fade-in">
          <HeroCompare a={a} b={b} />
          <RatingsCompare
            title="Overall ratings"
            a={a}
            b={b}
            pick={(p) => p.overview_ratings}
          />
          <RatingsCompare
            title="Defense"
            a={a}
            b={b}
            pick={(p) => p.defense_ratings}
          />
          <StatsCompare a={a} b={b} />
        </div>
      ) : null}

      {playerA && (
        <PlayerPickerDialog
          open={swapOpen}
          onOpenChange={setSwapOpen}
          excludeId={playerA}
          title="Pick a player to compare"
          description="Replaces the right-hand player on this page."
          onPick={(pid) =>
            navigate(
              `/compare/${encodeURIComponent(playerA)}/${encodeURIComponent(pid)}`,
              { replace: true },
            )
          }
        />
      )}
    </AppShell>
  );
}

function HeroCompare({ a, b }: { a: PlayerProfile; b: PlayerProfile }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <PlayerHero profile={a} />
      <PlayerHero profile={b} />
    </div>
  );
}

function PlayerHero({ profile }: { profile: PlayerProfile }) {
  const stars = parseFloat(profile.overall_stars_text ?? "");
  return (
    <Card className="p-5">
      <div className="flex items-center gap-4">
        <PlayerAvatar
          playerId={profile.player_id}
          initials={profile.initials}
          className="h-16 w-16 shrink-0 overflow-hidden rounded-xl text-2xl shadow-panel"
        />
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
            {profile.team_id || "FREE AGENT"}
          </div>
          <h2 className="truncate font-display text-xl font-bold">
            {profile.full_name}
          </h2>
          <div className="text-xs text-muted">
            {profile.positions_text} · {profile.bats_text}/{profile.throws_text} ·{" "}
            {profile.age_text} yrs
          </div>
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-border/60 pt-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
            Overall
          </div>
          <div className="font-display text-2xl font-bold leading-none text-amber-text">
            {profile.overall_display != null
              ? Math.round(profile.overall_display)
              : "—"}
          </div>
        </div>
        {Number.isFinite(stars) && stars > 0 && (
          <StarRating value={stars} size="h-4 w-4" />
        )}
      </div>
    </Card>
  );
}

function RatingsCompare({
  title,
  a,
  b,
  pick,
}: {
  title: string;
  a: PlayerProfile;
  b: PlayerProfile;
  pick: (p: PlayerProfile) => Array<[string, string]>;
}) {
  const rows = useMemo(() => {
    const aRows = pick(a);
    const bRows = pick(b);
    const byLabel = new Map<string, { a?: string; b?: string }>();
    for (const [label, value] of aRows) {
      byLabel.set(label, { ...(byLabel.get(label) ?? {}), a: value });
    }
    for (const [label, value] of bRows) {
      byLabel.set(label, { ...(byLabel.get(label) ?? {}), b: value });
    }
    return Array.from(byLabel, ([label, values]) => ({ label, ...values }));
  }, [a, b, pick]);

  if (rows.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
        </div>
        <Badge tone="amber">
          <Star className="h-3 w-3" /> Diff
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
              <th className="px-6 py-2 text-left">Metric</th>
              <th className="px-3 py-2 text-right">{a.initials || "A"}</th>
              <th className="px-3 py-2 text-center">Δ</th>
              <th className="px-3 py-2 text-right">{b.initials || "B"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <DiffRow key={row.label} label={row.label} a={row.a} b={row.b} />
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function DiffRow({
  label,
  a,
  b,
}: {
  label: string;
  a?: string;
  b?: string;
}) {
  const aNum = parseNumeric(a);
  const bNum = parseNumeric(b);
  let delta = "";
  let tone = "text-muted";
  if (aNum != null && bNum != null) {
    const diff = aNum - bNum;
    if (diff === 0) {
      delta = "0";
    } else if (diff > 0) {
      delta = `+${diff}`;
      tone = "text-success";
    } else {
      delta = String(diff);
      tone = "text-danger";
    }
  }
  return (
    <tr className="border-b border-border/40 last:border-b-0">
      <td className="px-6 py-2 text-left font-semibold">{label}</td>
      <td className="px-3 py-2 text-right tabular-nums">{a ?? "—"}</td>
      <td className={cn("px-3 py-2 text-center tabular-nums", tone)}>{delta || "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{b ?? "—"}</td>
    </tr>
  );
}

function parseNumeric(value: string | undefined): number | null {
  if (value == null || value === "" || value === "--") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function StatsCompare({ a, b }: { a: PlayerProfile; b: PlayerProfile }) {
  // Stats rows come keyed by time window ("Career", "2025 season", etc.).
  // Find the row that appears in BOTH so the side-by-side line up; prefer
  // the first overlapping pair.
  const aRow = a.stats_rows[0];
  const bRow = b.stats_rows[0];
  if (!aRow || !bRow) return null;
  const aLabel = aRow[0];
  const aData = aRow[1];
  const bLabel = bRow[0];
  const bData = bRow[1];
  const columns = a.stats_columns.length ? a.stats_columns : b.stats_columns;
  if (columns.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Stats comparison</CardTitle>
          <div className="mt-1 text-xs text-muted">
            {aLabel} vs {bLabel}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                <th className="px-6 py-2 text-left">Stat</th>
                <th className="px-3 py-2 text-right">{a.initials || "A"}</th>
                <th className="px-3 py-2 text-center">Δ</th>
                <th className="px-3 py-2 text-right">{b.initials || "B"}</th>
              </tr>
            </thead>
            <tbody>
              {columns.map((col) => (
                <DiffRow
                  key={col}
                  label={col}
                  a={formatStatCell(aData[col])}
                  b={formatStatCell(bData[col])}
                />
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function formatStatCell(value: unknown): string | undefined {
  if (value == null || value === "") return undefined;
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(3);
  }
  return String(value);
}
