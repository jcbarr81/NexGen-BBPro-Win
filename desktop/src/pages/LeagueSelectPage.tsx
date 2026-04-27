/**
 * League picker -- step 2 of the sign-in flow.
 *
 * Ports ui/league_manager_dialog.py: list every registered league, highlight
 * the active one, and let the user switch the sidecar's active league via
 * POST /leagues/active/{id}. The owner dashboard in the following route
 * depends on this being set.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  ArrowRight,
  CheckCircle2,
  Loader2,
  PlusCircle,
  Trash2,
  Trophy,
} from "lucide-react";

import { api, type League } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { Brand } from "@/components/layout/Brand";

export function LeagueSelectPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const setActiveLeague = useAuthStore((s) => s.setActiveLeague);
  const role = useAuthStore((s) => s.role);
  const token = useAuthStore((s) => s.token);
  // Pre-login the user has no role; we still need a Create button so the
  // first-run flow (which bootstraps the admin password) is reachable.
  const isAdmin = role === "admin";
  const canCreate = isAdmin || !token;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<League | null>(null);

  const leagues = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api.listLeagues(),
  });
  const active = useQuery({
    queryKey: ["active-league"],
    queryFn: () => api.getActiveLeague(),
  });

  useEffect(() => {
    if (active.data?.league_id && !selectedId) {
      setSelectedId(active.data.league_id);
    }
  }, [active.data, selectedId]);

  // First-run: no leagues registered yet → bounce to the setup wizard,
  // which handles admin-password bootstrap in addition to league creation.
  useEffect(() => {
    if (leagues.data && leagues.data.length === 0) {
      navigate("/leagues/new?first-run=1", { replace: true });
    }
  }, [leagues.data, navigate]);

  useEffect(() => {
    if (active.data?.league_id) {
      setActiveLeague(active.data.league_id);
    }
  }, [active.data, setActiveLeague]);

  const activate = useMutation({
    mutationFn: (id: string) => api.setActiveLeague(id),
    onSuccess: (res) => {
      setActiveLeague(res.league_id);
      queryClient.invalidateQueries({ queryKey: ["active-league"] });
      // Pre-login: head to sign-in. Already-signed-in users go straight home.
      navigate(token ? "/home" : "/login", { replace: true });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteLeague(id),
    onSuccess: (res) => {
      if (selectedId === res.league_id) setSelectedId(null);
      setActiveLeague(res.active_league ?? null);
      queryClient.invalidateQueries({ queryKey: ["leagues"] });
      queryClient.invalidateQueries({ queryKey: ["active-league"] });
    },
  });

  const archive = useMutation({
    mutationFn: (id: string) => api.archiveLeague(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leagues"] });
    },
  });
  const unarchive = useMutation({
    mutationFn: (id: string) => api.unarchiveLeague(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leagues"] });
    },
  });

  async function handleContinue() {
    if (!selectedId) return;
    if (selectedId === active.data?.league_id) {
      setActiveLeague(selectedId);
      navigate(token ? "/home" : "/login", { replace: true });
      return;
    }
    activate.mutate(selectedId);
  }

  return (
    <div className="relative z-10 flex min-h-full items-center justify-center bg-canvas px-6 py-10">
      <div className="w-full max-w-3xl animate-fade-in space-y-6">
        <div className="flex items-center justify-between">
          <Brand />
          <Badge tone="amber">
            <Trophy className="h-3 w-3" /> League picker
          </Badge>
        </div>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Choose a league</CardTitle>
              <CardDescription>
                {canCreate
                  ? "Pick an existing league or create a new one. After you choose, sign in to continue."
                  : "Select the league to load. You can switch leagues at any time from the sidebar."}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {leagues.isLoading ? (
              <div className="flex items-center gap-2 px-6 py-8 text-sm text-muted">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading leagues…
              </div>
            ) : leagues.isError ? (
              <div className="px-6 py-6 text-sm text-danger">
                {(leagues.error as Error).message}
              </div>
            ) : !leagues.data || leagues.data.length === 0 ? (
              <div className="px-6 py-8 text-sm text-muted">
                No leagues registered yet.
                {canCreate
                  ? " Use the Create button below to set one up."
                  : " Ask an admin to create one."}
              </div>
            ) : (
              <ul className="divide-y divide-border/60">
                {leagues.data.map((league) => (
                  <LeagueRow
                    key={league.id}
                    league={league}
                    isActive={active.data?.league_id === league.id}
                    isSelected={selectedId === league.id}
                    onSelect={() => setSelectedId(league.id)}
                    canDelete={isAdmin && (leagues.data?.length ?? 0) > 1}
                    onDelete={() => setConfirmDelete(league)}
                    isDeleting={remove.isPending && remove.variables === league.id}
                    canArchive={isAdmin && active.data?.league_id !== league.id}
                    onToggleArchive={() => {
                      if (league.status === "archived") {
                        unarchive.mutate(league.id);
                      } else {
                        archive.mutate(league.id);
                      }
                    }}
                    isTogglingArchive={
                      (archive.isPending && archive.variables === league.id) ||
                      (unarchive.isPending && unarchive.variables === league.id)
                    }
                  />
                ))}
              </ul>
            )}
          </CardContent>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 bg-surfaceAlt/40 px-6 py-3">
            <div className="text-xs text-muted">
              {active.data?.league_id ? (
                <>Active: <span className="font-semibold text-ink">{active.data.league_id}</span></>
              ) : (
                "No league currently active"
              )}
            </div>
            <div className="flex items-center gap-2">
              {canCreate && (
                <Button
                  variant="outline"
                  onClick={() => {
                    // Pre-login or non-admin: route through /login with a
                    // hard requirement on the admin role, then resume to
                    // the create wizard. Already-signed-in admins go
                    // directly.
                    if (isAdmin) {
                      navigate("/leagues/new");
                    } else {
                      navigate("/login?require=admin&next=/leagues/new");
                    }
                  }}
                >
                  <PlusCircle className="h-4 w-4" />
                  Create new league
                </Button>
              )}
              <Button
                onClick={handleContinue}
                disabled={!selectedId || activate.isPending}
              >
                {activate.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                {token ? "Continue" : "Sign in"}
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </Card>

        {activate.isError && (
          <p className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            {(activate.error as Error).message}
          </p>
        )}
        {remove.isError && (
          <p className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            {(remove.error as Error).message}
          </p>
        )}
      </div>

      {/* React-based confirm instead of window.confirm. The native confirm
          dialog leaves Electron's BrowserWindow in a state where keyboard
          input doesn't reach focused inputs anymore (reported on 6.10.8-9
          after delete-then-add-user). */}
      <Dialog
        open={!!confirmDelete}
        onOpenChange={(next) => !next && setConfirmDelete(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete league?</DialogTitle>
            <DialogDescription>
              Permanently delete{" "}
              <span className="font-semibold text-ink">
                {confirmDelete?.display_name ?? ""}
              </span>{" "}
              and all of its data. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (confirmDelete) remove.mutate(confirmDelete.id);
                setConfirmDelete(null);
              }}
            >
              <Trash2 className="h-4 w-4" /> Delete league
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

interface LeagueRowProps {
  league: League;
  isActive: boolean;
  isSelected: boolean;
  onSelect: () => void;
  canDelete: boolean;
  onDelete: () => void;
  isDeleting: boolean;
  canArchive: boolean;
  onToggleArchive: () => void;
  isTogglingArchive: boolean;
}

function LeagueRow({
  league,
  isActive,
  isSelected,
  onSelect,
  canDelete,
  onDelete,
  isDeleting,
  canArchive,
  onToggleArchive,
  isTogglingArchive,
}: LeagueRowProps) {
  return (
    <li
      className={cn(
        "flex items-center gap-2 pr-3 transition",
        isSelected ? "bg-amber/10" : "hover:bg-surfaceAlt/40",
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        className="flex flex-1 items-center justify-between gap-4 px-6 py-4 text-left"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold">{league.display_name}</span>
            {isActive && (
              <Badge tone="success">
                <CheckCircle2 className="h-3 w-3" /> Active
              </Badge>
            )}
            <Badge tone={league.status === "archived" ? "neutral" : "amber"}>
              {league.status}
            </Badge>
          </div>
          <div className="mt-1 text-xs text-muted">
            id: {league.id} · mode: {league.mode}
            {league.last_opened_at
              ? ` · last opened ${new Date(league.last_opened_at).toLocaleDateString()}`
              : ""}
          </div>
        </div>

        <div
          className={cn(
            "h-4 w-4 rounded-full border-2 transition",
            isSelected ? "border-amber bg-amber" : "border-border",
          )}
          aria-hidden
        />
      </button>

      {canArchive && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleArchive();
          }}
          disabled={isTogglingArchive}
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition",
            "hover:bg-amber/10 hover:text-amber",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
          aria-label={
            league.status === "archived"
              ? `Restore league ${league.display_name}`
              : `Archive league ${league.display_name}`
          }
          title={
            league.status === "archived"
              ? `Restore ${league.display_name}`
              : `Archive ${league.display_name}`
          }
        >
          {isTogglingArchive ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : league.status === "archived" ? (
            <ArchiveRestore className="h-4 w-4" />
          ) : (
            <Archive className="h-4 w-4" />
          )}
        </button>
      )}
      {canDelete && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          disabled={isDeleting}
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition",
            "hover:bg-danger/10 hover:text-danger",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
          aria-label={`Delete league ${league.display_name}`}
          title={`Delete ${league.display_name}`}
        >
          {isDeleting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4" />
          )}
        </button>
      )}
    </li>
  );
}
