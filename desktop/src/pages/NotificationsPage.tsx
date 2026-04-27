/**
 * Per-team notification preferences.
 *
 * Each rule has three knobs (enable / notify / stop sim) plus an
 * optional numeric threshold. Settings are persisted to
 * data/notifications/<team_id>.json on the server. The notification
 * engine in services.notification_engine reads these rules during
 * /season/simulate/* and breaks the sim early when a stop_sim rule
 * fires, so the owner never silently misses an injury or trade offer.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  History,
  Loader2,
  RotateCcw,
  Save,
} from "lucide-react";

import {
  api,
  type NotificationCategory,
  type NotificationEvent,
  type NotificationRulePayload,
  type NotificationSettings,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useActiveTeamColor } from "@/lib/team-colors";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";

export function NotificationsPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const accentColor = useActiveTeamColor(teamId ?? undefined);

  if (!teamId) {
    return (
      <AppShell title="Notifications">
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <AlertTriangle className="h-5 w-5 text-warning" />
            <span className="text-sm">
              Notifications are per-team. Select a team to continue.
            </span>
          </CardContent>
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Notifications"
      subtitle={`Team ${teamId} · choose what flags + pauses the sim`}
      teamAccentColor={accentColor}
    >
      <NotificationsBody teamId={teamId} />
    </AppShell>
  );
}

function NotificationsBody({ teamId }: { teamId: string }) {
  return (
    <Tabs defaultValue="settings">
      <TabsList>
        <TabsTrigger value="settings">
          <Bell className="mr-1 h-4 w-4" /> Preferences
        </TabsTrigger>
        <TabsTrigger value="history">
          <History className="mr-1 h-4 w-4" /> Recent events
        </TabsTrigger>
      </TabsList>
      <TabsContent value="settings">
        <SettingsTab teamId={teamId} />
      </TabsContent>
      <TabsContent value="history">
        <HistoryTab teamId={teamId} />
      </TabsContent>
    </Tabs>
  );
}

function SettingsTab({ teamId }: { teamId: string }) {
  const queryClient = useQueryClient();
  const schema = useQuery({
    queryKey: ["notification-schema"],
    queryFn: () => api.notificationSchema(),
  });
  const settings = useQuery({
    queryKey: ["notification-settings", teamId],
    queryFn: () => api.notificationSettings(teamId),
  });

  const [draft, setDraft] = useState<Record<string, NotificationRulePayload>>(
    {},
  );
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settings.data) {
      setDraft({ ...settings.data.rules });
      setDirty(false);
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      api.saveNotificationSettings(teamId, { rules: draft }),
    onSuccess: (data: NotificationSettings) => {
      queryClient.setQueryData(["notification-settings", teamId], data);
      setDraft({ ...data.rules });
      setDirty(false);
    },
  });

  function update(ruleId: string, patch: Partial<NotificationRulePayload>) {
    setDraft((prev) => ({
      ...prev,
      [ruleId]: { ...prev[ruleId], ...patch } as NotificationRulePayload,
    }));
    setDirty(true);
  }

  function reset() {
    if (settings.data) {
      setDraft({ ...settings.data.rules });
      setDirty(false);
    }
  }

  if (schema.isLoading || settings.isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
          <span className="text-sm text-muted">Loading preferences…</span>
        </CardContent>
      </Card>
    );
  }
  if (schema.isError || settings.isError) {
    const err =
      (schema.error as Error)?.message ||
      (settings.error as Error)?.message ||
      "Failed to load notification settings.";
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10 text-danger">
          <AlertTriangle className="h-5 w-5" />
          <span className="text-sm">{err}</span>
        </CardContent>
      </Card>
    );
  }

  const categories = schema.data?.categories ?? [];

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">How this works</CardTitle>
          <CardDescription>
            <span className="block">
              <b>Notify</b> — show a toast/banner when this event fires
              during a sim run.
            </span>
            <span className="block">
              <b>Stop sim</b> — pause a multi-day sim (Sim Day / Week /
              Month / To Draft) the moment this event fires so you can
              review and react.
            </span>
            <span className="block">
              <b>Threshold</b> — for streak / cash / horizon rules, the
              numeric value the rule fires at.
            </span>
          </CardDescription>
        </CardHeader>
      </Card>

      <div className="flex items-center justify-end gap-2">
        {dirty && <Badge tone="warning">Unsaved</Badge>}
        <Button
          variant="ghost"
          size="sm"
          onClick={reset}
          disabled={!dirty || save.isPending}
        >
          <RotateCcw className="mr-1 h-4 w-4" /> Reset
        </Button>
        <Button
          size="sm"
          onClick={() => save.mutate()}
          disabled={!dirty || save.isPending}
        >
          {save.isPending ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-1 h-4 w-4" />
          )}
          Save
        </Button>
      </div>

      {save.isError && (
        <Card>
          <CardContent className="flex items-center gap-2 py-3 text-sm text-danger">
            <AlertTriangle className="h-4 w-4" />
            <span>{(save.error as Error).message}</span>
          </CardContent>
        </Card>
      )}

      <div className="space-y-4">
        {categories.map((cat) => (
          <CategoryCard
            key={cat.id}
            category={cat}
            draft={draft}
            update={update}
          />
        ))}
      </div>
    </div>
  );
}

function CategoryCard({
  category,
  draft,
  update,
}: {
  category: NotificationCategory;
  draft: Record<string, NotificationRulePayload>;
  update: (ruleId: string, patch: Partial<NotificationRulePayload>) => void;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{category.label}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[10px] uppercase tracking-wider text-muted">
              <th className="px-4 py-2 text-left">Rule</th>
              <th className="px-2 py-2">Enabled</th>
              <th className="px-2 py-2">Notify</th>
              <th className="px-2 py-2">Stop sim</th>
              <th className="px-3 py-2 text-left">Threshold</th>
            </tr>
          </thead>
          <tbody>
            {category.rules.map((spec) => {
              const rule =
                draft[spec.id] ??
                ({
                  enabled: true,
                  notify: spec.default_notify,
                  stop_sim: spec.default_stop,
                  threshold: spec.threshold ?? null,
                } as NotificationRulePayload);
              const hasThreshold = spec.threshold !== null && spec.threshold !== undefined;
              return (
                <tr
                  key={spec.id}
                  className="border-b border-border/30 last:border-b-0 hover:bg-surfaceAlt/30"
                >
                  <td className="px-4 py-2">
                    <div className="font-semibold">{spec.label}</div>
                  </td>
                  <td className="px-2 py-2 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber"
                      checked={rule.enabled}
                      onChange={(e) =>
                        update(spec.id, { enabled: e.target.checked })
                      }
                    />
                  </td>
                  <td className="px-2 py-2 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber"
                      checked={rule.notify}
                      disabled={!rule.enabled}
                      onChange={(e) =>
                        update(spec.id, { notify: e.target.checked })
                      }
                    />
                  </td>
                  <td className="px-2 py-2 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber"
                      checked={rule.stop_sim}
                      disabled={!rule.enabled}
                      onChange={(e) =>
                        update(spec.id, { stop_sim: e.target.checked })
                      }
                    />
                  </td>
                  <td className="px-3 py-2">
                    {hasThreshold ? (
                      <div className="flex items-center gap-2">
                        <input
                          type="number"
                          min={spec.threshold_min ?? undefined}
                          max={spec.threshold_max ?? undefined}
                          value={
                            rule.threshold == null
                              ? Number(spec.threshold ?? 0)
                              : Number(rule.threshold)
                          }
                          disabled={!rule.enabled}
                          onChange={(e) => {
                            const n = Number(e.target.value);
                            update(spec.id, {
                              threshold: Number.isFinite(n) ? n : 0,
                            });
                          }}
                          className="h-8 w-28 rounded-md border border-border bg-canvas/60 px-2 text-xs text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40 disabled:opacity-50"
                        />
                        <span className="text-[11px] text-muted">
                          {spec.threshold_label ?? ""}
                        </span>
                      </div>
                    ) : (
                      <span className="text-[11px] italic text-muted">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function HistoryTab({ teamId }: { teamId: string }) {
  const history = useQuery({
    queryKey: ["notification-history", teamId],
    queryFn: () => api.notificationHistory(teamId, 100),
    refetchOnWindowFocus: false,
  });

  if (history.isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10">
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
          <span className="text-sm text-muted">Loading recent events…</span>
        </CardContent>
      </Card>
    );
  }
  if (history.isError) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 py-10 text-danger">
          <AlertTriangle className="h-5 w-5" />
          <span className="text-sm">
            {(history.error as Error)?.message || "Failed to load history."}
          </span>
        </CardContent>
      </Card>
    );
  }

  const events: NotificationEvent[] = history.data?.events ?? [];

  if (events.length === 0) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted">
          No notification events yet — keep simming and they'll show up here.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Recent events</CardTitle>
        <CardDescription>
          Last {events.length} notification(s) generated for this team,
          newest first.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border/60 text-[10px] uppercase tracking-wider text-muted">
              <th className="px-4 py-2 text-left">When</th>
              <th className="px-3 py-2 text-left">Severity</th>
              <th className="px-3 py-2 text-left">Title</th>
              <th className="px-4 py-2 text-left">Message</th>
            </tr>
          </thead>
          <tbody>
            {events.map((ev, idx) => (
              <tr
                key={`${ev.timestamp}-${idx}`}
                className="border-b border-border/30 last:border-b-0 hover:bg-surfaceAlt/30"
              >
                <td className="px-4 py-1.5 whitespace-nowrap text-[11px] text-muted">
                  {ev.sim_date ?? ev.timestamp.replace("T", " ").replace("Z", "")}
                </td>
                <td className="px-3 py-1.5">
                  <Badge tone={severityTone(ev.severity)}>{ev.severity}</Badge>
                </td>
                <td className="px-3 py-1.5 font-semibold">{ev.title}</td>
                <td className="px-4 py-1.5">{ev.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function severityTone(
  severity: string,
): "amber" | "neutral" | "warning" | "danger" | "success" {
  if (severity === "critical") return "danger";
  if (severity === "warning") return "warning";
  return "amber";
}
