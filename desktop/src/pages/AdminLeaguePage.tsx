/**
 * Admin League Settings — port of the destructive commissioner actions in
 * ui/admin_dashboard/actions/league.py. Regenerate schedule, reset stats,
 * clear results, clone league. Each card confirms before running.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Copy,
  Eraser,
  History,
  Loader2,
  RefreshCcw,
  Settings2,
  Trash2,
  Wrench,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useConfirmDialog } from "@/lib/use-confirm";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@/components/ui";

export function AdminLeaguePage() {
  return (
    <AppShell
      title="League Admin"
      subtitle="Commissioner: schedule regeneration, stat resets, clone"
    >
      <AdminLeagueBody />
    </AppShell>
  );
}

function AdminLeagueBody() {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <RegenerateScheduleCard />
      <ResetStatsCard />
      <ResetResultsCard />
      <RepairLineupsCard />
      <ResetToOpeningDayCard />
      <CloneLeagueCard />
      <DeleteLeagueCard />
    </div>
  );
}

function ResetToOpeningDayCard() {
  const [purgeBoxscores, setPurgeBoxscores] = useState(false);
  const [clearNews, setClearNews] = useState(false);
  const [clearTransactions, setClearTransactions] = useState(false);
  const mut = useMutation({
    mutationFn: () =>
      api.adminResetToOpeningDay({
        purge_boxscores: purgeBoxscores,
        clear_news: clearNews,
        clear_transactions: clearTransactions,
      }),
  });
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="h-4 w-4 text-amber" /> Reset to Opening Day
        </CardTitle>
        <CardDescription>
          Rewinds the current season — clears results, standings, stats,
          history, draft + playoff artifacts, injuries, and pitcher recovery;
          phase returns to Regular Season.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5 text-xs">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={purgeBoxscores}
              onChange={(e) => setPurgeBoxscores(e.target.checked)}
            />
            Also delete saved season boxscores
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={clearNews}
              onChange={(e) => setClearNews(e.target.checked)}
            />
            Also purge league news feed
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={clearTransactions}
              onChange={(e) => setClearTransactions(e.target.checked)}
            />
            Also clear transactions log
          </label>
        </div>
        <ConfirmButton
          label="Reset to Opening Day"
          icon={<History className="h-4 w-4" />}
          confirmText="Rewind the season to Opening Day? All played results, standings, stats, season history, draft results, and playoff brackets for the current year will be cleared."
          pending={mut.isPending}
          onConfirm={() => mut.mutate()}
        />
        <ResultLine
          ok={mut.isSuccess}
          err={mut.isError}
          okText={
            mut.data
              ? `Reset to Opening Day${mut.data.opening_day_year ? ` ${mut.data.opening_day_year}` : ""}.${mut.data.boxscores_cleared ? " Boxscores purged." : ""}${mut.data.news_cleared ? " News cleared." : ""}${mut.data.transactions_cleared ? " Transactions cleared." : ""}${mut.data.notes.length ? ` Notes: ${mut.data.notes.join("; ")}` : ""}`
              : ""
          }
          errText={(mut.error as Error | undefined)?.message}
        />
      </CardContent>
    </Card>
  );
}

function RepairLineupsCard() {
  const mut = useMutation({ mutationFn: () => api.adminRepairLineups() });
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Wrench className="h-4 w-4 text-amber" /> Repair lineups
        </CardTitle>
        <CardDescription>
          Runs lineup autofill for every team that fails validation. Useful
          after a roster import or mid-season cleanup.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ConfirmButton
          label="Repair lineups"
          icon={<Wrench className="h-4 w-4" />}
          confirmText="Autofill lineups for every team that currently fails validation?"
          pending={mut.isPending}
          onConfirm={() => mut.mutate()}
        />
        <ResultLine
          ok={mut.isSuccess}
          err={mut.isError}
          okText={
            mut.data
              ? `Repaired ${mut.data.fixed.length} teams${mut.data.failed.length ? ` · ${mut.data.failed.length} still failed` : ""}.`
              : ""
          }
          errText={(mut.error as Error | undefined)?.message}
        />
      </CardContent>
    </Card>
  );
}

function RegenerateScheduleCard() {
  const templates = useQuery({
    queryKey: ["admin-schedule-templates"],
    queryFn: () => api.adminLeagueScheduleTemplates(),
  });
  const [template, setTemplate] = useState("mlb_162");
  const mut = useMutation({
    mutationFn: (id: string) => api.adminRegenerateSchedule(id),
  });

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarClock className="h-4 w-4 text-amber" /> Regenerate schedule
        </CardTitle>
        <CardDescription>
          Overwrites <code>schedule.csv</code> with a fresh template. All
          previously-played results are discarded.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Label htmlFor="tpl">Schedule template</Label>
        <select
          id="tpl"
          className="w-full rounded-md border border-border bg-surface px-2 py-1 text-sm"
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
        >
          {(templates.data?.templates ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} ({t.games_per_team} games/team)
            </option>
          ))}
        </select>
        <ConfirmButton
          label="Regenerate"
          icon={<RefreshCcw className="h-4 w-4" />}
          confirmText="Regenerate the schedule? All played results will be cleared."
          pending={mut.isPending}
          onConfirm={() => mut.mutate(template)}
        />
        <ResultLine
          ok={mut.isSuccess}
          err={mut.isError}
          okText={
            mut.data
              ? `Wrote ${mut.data.games} games (${mut.data.template_id}).`
              : ""
          }
          errText={(mut.error as Error | undefined)?.message}
        />
      </CardContent>
    </Card>
  );
}

function ResetStatsCard() {
  const mut = useMutation({ mutationFn: () => api.adminResetStats() });
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Eraser className="h-4 w-4 text-amber" /> Reset season stats
        </CardTitle>
        <CardDescription>
          Wipes <code>season_stats.json</code>. Schedule and rosters are
          untouched.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ConfirmButton
          label="Reset stats"
          icon={<Eraser className="h-4 w-4" />}
          confirmText="Clear every team + player stat line for the current season? This cannot be undone."
          pending={mut.isPending}
          onConfirm={() => mut.mutate()}
        />
        <ResultLine
          ok={mut.isSuccess}
          err={mut.isError}
          okText="Season stats cleared."
          errText={(mut.error as Error | undefined)?.message}
        />
      </CardContent>
    </Card>
  );
}

function ResetResultsCard() {
  const mut = useMutation({ mutationFn: () => api.adminResetResults() });
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <RefreshCcw className="h-4 w-4 text-amber" /> Clear played results
        </CardTitle>
        <CardDescription>
          Marks every scheduled game as unplayed — useful for re-running a
          season without a full schedule regen.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ConfirmButton
          label="Clear results"
          icon={<RefreshCcw className="h-4 w-4" />}
          confirmText="Clear results for every scheduled game? The matchups stay; this only clears the played flag + boxscore links."
          pending={mut.isPending}
          onConfirm={() => mut.mutate()}
        />
        <ResultLine
          ok={mut.isSuccess}
          err={mut.isError}
          okText={mut.data ? `Cleared ${mut.data.games} games.` : ""}
          errText={(mut.error as Error | undefined)?.message}
        />
      </CardContent>
    </Card>
  );
}

function CloneLeagueCard() {
  const [leagueId, setLeagueId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const mut = useMutation({
    mutationFn: () => api.adminCloneLeague(leagueId.trim(), displayName.trim()),
  });
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Copy className="h-4 w-4 text-amber" /> Clone this league
        </CardTitle>
        <CardDescription>
          Deep-copies the active league into a new registry entry. Use this
          before risky experiments.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div>
            <Label htmlFor="clone-id">New league id</Label>
            <Input
              id="clone-id"
              value={leagueId}
              onChange={(e) => setLeagueId(e.target.value)}
              placeholder="alpha, sandbox-2027, …"
            />
          </div>
          <div>
            <Label htmlFor="clone-name">Display name</Label>
            <Input
              id="clone-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Sandbox 2027"
            />
          </div>
        </div>
        <ConfirmButton
          label="Clone"
          icon={<Copy className="h-4 w-4" />}
          confirmText={`Clone the active league into "${leagueId}"? Depending on league size this can take a minute.`}
          pending={mut.isPending}
          disabled={!leagueId.trim() || !displayName.trim()}
          onConfirm={() => mut.mutate()}
        />
        <ResultLine
          ok={mut.isSuccess}
          err={mut.isError}
          okText={mut.data ? `Cloned to ${mut.data.path}` : ""}
          errText={(mut.error as Error | undefined)?.message}
        />
      </CardContent>
    </Card>
  );
}

function ConfirmButton({
  label,
  icon,
  confirmText,
  pending,
  disabled,
  onConfirm,
}: {
  label: string;
  icon: React.ReactNode;
  confirmText: string;
  pending: boolean;
  disabled?: boolean;
  onConfirm: () => void;
}) {
  const { confirm, dialog } = useConfirmDialog();
  return (
    <>
      <Button
        size="sm"
        onClick={async () => {
          if (
            await confirm({
              title: "Confirm action",
              description: confirmText,
              danger: true,
            })
          ) {
            onConfirm();
          }
        }}
        disabled={pending || disabled}
      >
        {pending ? (
          <Loader2 className="mr-1 h-4 w-4 animate-spin" />
        ) : (
          <span className="mr-1">{icon}</span>
        )}
        {label}
      </Button>
      {dialog}
    </>
  );
}

function ResultLine({
  ok,
  err,
  okText,
  errText,
}: {
  ok: boolean;
  err: boolean;
  okText?: string;
  errText?: string;
}) {
  if (ok && okText) {
    return (
      <div className="mt-2 flex items-center gap-2 text-xs text-success">
        <CheckCircle2 className="h-3 w-3" /> {okText}
      </div>
    );
  }
  if (err && errText) {
    return (
      <div className="mt-2 flex items-start gap-2 text-xs text-danger">
        <AlertTriangle className="mt-0.5 h-3 w-3" />
        <span className="whitespace-pre-line">{errText}</span>
      </div>
    );
  }
  return null;
}

/**
 * Permanently delete a registered league. Lists every league with a delete
 * button; the chosen one is removed after a double-confirm. The backend
 * (``DELETE /leagues/:id``) wipes the registry entry and on-disk data dir;
 * deleting the active league auto-promotes a sibling.
 */
function DeleteLeagueCard() {
  const queryClient = useQueryClient();
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const setActiveLeague = useAuthStore((s) => s.setActiveLeague);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const leagues = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api.listLeagues(),
  });
  const active = useQuery({
    queryKey: ["active-league"],
    queryFn: () => api.getActiveLeague(),
  });

  const remove = useMutation({
    mutationFn: (leagueId: string) => api.deleteLeague(leagueId),
    onSuccess: (res) => {
      setError(null);
      setSuccess(`Deleted league: ${res.league_id}`);
      setActiveLeague(res.active_league ?? null);
      queryClient.invalidateQueries({ queryKey: ["leagues"] });
      queryClient.invalidateQueries({ queryKey: ["active-league"] });
    },
    onError: (err) => {
      setSuccess(null);
      setError(err instanceof Error ? err.message : String(err));
    },
  });

  async function handleDelete(leagueId: string, displayName: string) {
    const ok = await confirm({
      title: `Delete "${displayName}"?`,
      description:
        "This permanently removes the league from the registry and wipes its data directory (rosters, lineups, stats, schedule, news, everything). This cannot be undone.",
      confirmLabel: "Delete league",
      danger: true,
    });
    if (!ok) return;
    remove.mutate(leagueId);
  }

  const rows = leagues.data ?? [];
  const activeId = active.data?.league_id ?? null;

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Trash2 className="h-4 w-4 text-danger" /> Delete a league
          </CardTitle>
          <CardDescription>
            Permanently removes a league + all of its on-disk data. There's no
            archive — gone is gone. Active league deletion is allowed; a
            sibling is auto-promoted.
          </CardDescription>
        </div>
        <Badge tone="danger">
          <AlertTriangle className="h-3 w-3" /> Destructive
        </Badge>
      </CardHeader>
      <CardContent>
        {leagues.isLoading ? (
          <div className="flex items-center gap-2 py-3 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading leagues…
          </div>
        ) : leagues.isError ? (
          <div className="flex items-center gap-2 py-3 text-sm text-danger">
            <AlertTriangle className="h-4 w-4" />
            {(leagues.error as Error).message}
          </div>
        ) : rows.length === 0 ? (
          <div className="py-3 text-sm text-muted">
            No leagues are registered.
          </div>
        ) : (
          <div className="space-y-2">
            {rows.map((row) => {
              const isActive = activeId === row.id;
              return (
                <div
                  key={row.id}
                  className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{row.display_name}</span>
                      {isActive && (
                        <Badge tone="amber" className="text-[10px]">
                          active
                        </Badge>
                      )}
                      {row.status && row.status !== "active" && (
                        <Badge tone="neutral" className="text-[10px]">
                          {row.status}
                        </Badge>
                      )}
                    </div>
                    <div className="text-[11px] text-muted">
                      {row.id} · {row.mode || "—"} · created {row.created_at}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(row.id, row.display_name)}
                    disabled={remove.isPending}
                    className="text-danger hover:bg-danger/10 hover:text-danger"
                  >
                    {remove.isPending ? (
                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="mr-1 h-3 w-3" />
                    )}
                    Delete
                  </Button>
                </div>
              );
            })}
          </div>
        )}
        {error && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
            <AlertTriangle className="h-4 w-4" />
            {error}
          </div>
        )}
        {success && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-success/40 bg-success/10 p-2 text-xs text-success">
            <CheckCircle2 className="h-4 w-4" />
            {success}
          </div>
        )}
      </CardContent>
      {confirmDialog}
    </Card>
  );
}
