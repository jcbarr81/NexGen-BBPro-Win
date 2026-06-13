/**
 * Phase 4 port of ui/injury_center_window.py.
 *
 * Concentrates a team's injured players: DL (15/45-day), 60-day IR, and
 * day-to-day ACT-roster guys. Each row shows the injury, list type, days
 * remaining and rehab status. Player names link straight to the profile.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CalendarCheck,
  ClipboardList,
  HeartPulse,
  Loader2,
  Stethoscope,
  Timer,
} from "lucide-react";

import { api, type TeamInjuryEntry } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { useActiveTeamColor } from "@/lib/team-colors";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard } from "@/components/StatCard";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

export function InjuryPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    enabled: !teamId,
  });
  const activeTeamId = teamId ?? teams.data?.[0]?.team_id ?? null;
  const teamAccentColor = useActiveTeamColor(activeTeamId ?? undefined);

  const injuries = useQuery({
    queryKey: ["team-injuries", activeTeamId],
    queryFn: () => api.teamInjuries(activeTeamId as string),
    enabled: !!activeTeamId,
  });

  if (!activeTeamId) {
    return (
      <AppShell title="Injury Center">
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            {teams.isLoading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin text-amber" />
                <span className="text-sm text-muted">Loading teams…</span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-5 w-5 text-warning" />
                <span className="text-sm">No team available.</span>
              </>
            )}
          </CardContent>
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Injury Center"
      subtitle={`${activeTeamId} · DL, IR, and day-to-day status`}
      teamAccentColor={teamAccentColor}
    >
      {injuries.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading injuries…</span>
          </CardContent>
        </Card>
      ) : injuries.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(injuries.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : injuries.data ? (
        <div className="space-y-6 animate-fade-in">
          <section className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <StatCard
              label="On Disabled List"
              value={injuries.data.counts.dl}
              Icon={HeartPulse}
              tone={injuries.data.counts.dl > 0 ? "danger" : "neutral"}
            />
            <StatCard
              label="On 60-day IR"
              value={injuries.data.counts.ir}
              Icon={ClipboardList}
              tone={injuries.data.counts.ir > 0 ? "danger" : "neutral"}
            />
            <StatCard
              label="Day-to-day"
              value={injuries.data.counts.day_to_day}
              Icon={Stethoscope}
              tone="amber"
            />
            <StatCard
              label="Activation Eligible"
              value={injuries.data.counts.eligible_to_activate}
              Icon={CalendarCheck}
              tone={
                injuries.data.counts.eligible_to_activate > 0
                  ? "success"
                  : "neutral"
              }
            />
          </section>

          <InjuryTable
            title="Disabled List"
            description="DL15 + DL45 — eligible activations highlighted"
            entries={injuries.data.dl}
            emptyText="Nobody on the DL."
          />
          <InjuryTable
            title="60-day Injured Reserve"
            description="Roster spot opened up; counts toward 40-man only"
            entries={injuries.data.ir}
            emptyText="Nobody on the 60-day IR."
          />
          <InjuryTable
            title="Day-to-day"
            description="Active roster, flagged as banged up"
            entries={injuries.data.day_to_day}
            emptyText="No day-to-day injuries flagged."
          />
        </div>
      ) : null}
    </AppShell>
  );
}

function InjuryTable({
  title,
  description,
  entries,
  emptyText,
}: {
  title: string;
  description: string;
  entries: TeamInjuryEntry[];
  emptyText: string;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <Badge tone="amber">{entries.length}</Badge>
      </CardHeader>
      <CardContent className="p-0">
        {entries.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">{emptyText}</div>
        ) : (
          <div className="overflow-x-auto"><table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                <th className="px-6 py-2 text-left font-semibold">Player</th>
                <th className="px-3 py-2 text-left font-semibold">Pos</th>
                <th className="px-3 py-2 text-left font-semibold">List</th>
                <th className="px-3 py-2 text-left font-semibold">Injury</th>
                <th className="px-3 py-2 text-right font-semibold">
                  Days Left
                </th>
                <th className="px-6 py-2 text-right font-semibold">
                  Eligible
                </th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <InjuryRow key={entry.player_id} entry={entry} />
              ))}
            </tbody>
          </table></div>
        )}
      </CardContent>
    </Card>
  );
}

function InjuryRow({ entry }: { entry: TeamInjuryEntry }) {
  const eligibleSoon = entry.dl_eligible || entry.days_remaining === 0;
  return (
    <tr
      className={cn(
        "border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40",
        eligibleSoon && "bg-success/5",
      )}
    >
      <td className="px-6 py-2">
        <Link
          to={`/player/${encodeURIComponent(entry.player_id)}`}
          className="font-semibold hover:text-amber"
        >
          {entry.last_name}
          {entry.first_name ? `, ${entry.first_name}` : ""}
        </Link>
        {entry.rehab_assignment && (
          <Badge tone="amber" className="ml-2">
            Rehab · {entry.rehab_days}d
          </Badge>
        )}
      </td>
      <td className="px-3 py-2 text-xs uppercase tracking-wider text-muted">
        {entry.primary_position || (entry.is_pitcher ? "PIT" : "POS")}
      </td>
      <td className="px-3 py-2">
        <Badge tone={listTone(entry.level)}>
          {entry.list_label || entry.level}
        </Badge>
      </td>
      <td className="px-3 py-2 text-sm">
        {entry.injury_description || "—"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        <DaysCell entry={entry} />
      </td>
      <td className="px-6 py-2 text-right">
        {entry.dl_eligible ? (
          <Badge tone="success">
            <CalendarCheck className="h-3 w-3" /> Now
          </Badge>
        ) : entry.return_date ? (
          <span className="text-xs text-muted">{entry.return_date}</span>
        ) : entry.injury_eligible_date ? (
          <span className="text-xs text-muted">
            {entry.injury_eligible_date}
          </span>
        ) : (
          <span className="text-subtle">—</span>
        )}
      </td>
    </tr>
  );
}

function DaysCell({ entry }: { entry: TeamInjuryEntry }) {
  if (entry.days_remaining == null) return <span className="text-subtle">—</span>;
  if (entry.days_remaining <= 0) {
    return (
      <span className="inline-flex items-center gap-1 text-success">
        <Timer className="h-3 w-3" /> 0
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-amber-text">
      <Timer className="h-3 w-3" /> {entry.days_remaining}
    </span>
  );
}

function listTone(
  level: TeamInjuryEntry["level"],
): "danger" | "warning" | "amber" | "neutral" {
  if (level === "IR") return "danger";
  if (level === "DL") return "warning";
  if (level === "ACT") return "amber";
  return "neutral";
}
