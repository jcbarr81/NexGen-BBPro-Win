import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Search, LogOut, Trash2 } from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cloudLogout } from "@/lib/cloud-auth";
import { toast } from "@/lib/toast-store";
import { useConfirmDialog } from "@/lib/use-confirm";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { Brand } from "@/components/layout/Brand";

export function MyLeaguesPage() {
  const navigate = useNavigate();
  const setActiveLeague = useAuthStore((s) => s.setActiveLeague);
  const setLeagueIdentity = useAuthStore((s) => s.setLeagueIdentity);
  const handle = useAuthStore((s) => s.handle);
  const pkg = useAuthStore((s) => s.pkg);

  const queryClient = useQueryClient();
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  const me = useQuery({ queryKey: ["account-me"], queryFn: () => api.accountMe() });
  const leagues = me.data?.leagues ?? [];
  // Super-admins see EVERY league under "All leagues" (catalog entries with no
  // per-user team). Cross-reference their own memberships so entering a league
  // they belong to still carries their real role + claimed team (not a forced
  // claim screen).
  const myMembership = new Map(leagues.map((m) => [m.league_id, m]));

  const deleteLeague = useMutation({
    mutationFn: (leagueId: string) => api.platformDeleteLeague(leagueId),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["account-me"] });
      toast.success("League deleted", {
        description:
          res.errors.length > 0
            ? `Removed with warnings: ${res.errors.join("; ")}`
            : `${res.league_id} is gone.`,
      });
    },
    onError: (err: unknown) => {
      toast.error("Delete failed", {
        description: err instanceof Error ? err.message : "Try again.",
      });
    },
  });

  async function confirmDelete(leagueId: string, name: string) {
    const ok = await confirm({
      title: `Delete "${name}"?`,
      description:
        `Permanently deletes ${leagueId} — the league, all its teams/players/` +
        `standings, and every membership. This cannot be undone.`,
      confirmLabel: "Delete league",
      danger: true,
    });
    if (ok) deleteLeague.mutate(leagueId);
  }

  // Seed the per-league role + team before navigating. commissioner -> "admin"
  // (matches the server identity bridge); empty team = nothing claimed yet.
  function enterLeague(
    leagueId: string,
    role: string | null | undefined,
    teamId: string | null | undefined,
    to: string,
  ) {
    setActiveLeague(leagueId);
    setLeagueIdentity(role === "commissioner" ? "admin" : role ?? "owner", teamId ?? "");
    navigate(to);
  }

  function enter(leagueId: string, role?: string | null, teamId?: string | null) {
    enterLeague(leagueId, role, teamId, "/home");
  }

  async function logout() {
    await cloudLogout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="h-full overflow-auto bg-canvas">
      {confirmDialog}
      <div className="mx-auto max-w-3xl space-y-6 px-6 py-10">
        <div className="flex items-center justify-between">
          <Brand />
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut className="h-4 w-4" /> Sign out
          </Button>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <h1 className="font-display text-2xl">
              {handle ? `Hey, ${handle}` : "Your leagues"}
            </h1>
            {pkg && (
              <p className="text-sm text-muted">
                {pkg === "commissioner" ? "Commissioner account" : "Owner account"}
              </p>
            )}
          </div>
          <div className="flex gap-2">
            {pkg === "commissioner" && (
              <Button onClick={() => navigate("/leagues/new?commissioner=1")}>
                <Plus className="h-4 w-4" /> Create a league
              </Button>
            )}
            <Button variant="outline" onClick={() => navigate("/discover")}>
              <Search className="h-4 w-4" /> Find a league
            </Button>
          </div>
        </div>

        {me.isLoading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-amber" />
          </div>
        ) : leagues.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center text-muted">
              <p className="mb-1 text-base">You're not in any leagues yet.</p>
              <p className="text-sm">
                {pkg === "commissioner"
                  ? "Create one to get started, or join an existing league."
                  : "Join a public league or enter an invite code to get started."}
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {leagues.map((l) => (
              <Card key={l.league_id}>
                <CardContent className="flex items-center justify-between py-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">
                        {l.display_name || l.league_id}
                      </span>
                      <Badge tone={l.role === "commissioner" ? "amber" : "neutral"}>
                        {l.role}
                      </Badge>
                      {l.status === "pending_team" && (
                        <Badge tone="neutral">awaiting team</Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted">
                      {l.team_id ? `Team: ${l.team_id}` : "No team assigned yet"}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {l.role === "commissioner" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() =>
                          enterLeague(l.league_id, l.role, l.team_id, "/league-members")
                        }
                      >
                        Manage
                      </Button>
                    )}
                    <Button size="sm" onClick={() => enter(l.league_id, l.role, l.team_id)}>
                      Enter
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {me.data?.super_admin && (me.data.all_leagues?.length ?? 0) > 0 && (
          <div className="space-y-3 pt-4">
            <div className="flex items-center gap-2">
              <h2 className="font-display text-lg">All leagues</h2>
              <Badge tone="amber">platform admin</Badge>
            </div>
            {me.data.all_leagues!.map((l) => (
              <Card key={l.league_id}>
                <CardContent className="flex items-center justify-between py-3">
                  <div>
                    <span className="font-semibold">
                      {l.display_name || l.league_id}
                    </span>
                    <span className="ml-2 text-xs text-muted">{l.visibility}</span>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        enterLeague(
                          l.league_id,
                          myMembership.get(l.league_id)?.role ?? "admin",
                          myMembership.get(l.league_id)?.team_id ?? "",
                          "/league-members",
                        )
                      }
                    >
                      Manage
                    </Button>
                    <Button
                      size="sm"
                      onClick={() =>
                        enter(
                          l.league_id,
                          myMembership.get(l.league_id)?.role ?? "admin",
                          myMembership.get(l.league_id)?.team_id ?? "",
                        )
                      }
                    >
                      Enter
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-danger/50 text-danger hover:bg-danger/10"
                      disabled={
                        deleteLeague.isPending &&
                        deleteLeague.variables === l.league_id
                      }
                      onClick={() =>
                        confirmDelete(l.league_id, l.display_name || l.league_id)
                      }
                      title="Permanently delete this league"
                    >
                      {deleteLeague.isPending &&
                      deleteLeague.variables === l.league_id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Trash2 className="h-3 w-3" />
                      )}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
