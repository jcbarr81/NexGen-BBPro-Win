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
  ArrowRight,
  CheckCircle2,
  Loader2,
  PlusCircle,
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
} from "@/components/ui";
import { Brand } from "@/components/layout/Brand";

export function LeagueSelectPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const setActiveLeague = useAuthStore((s) => s.setActiveLeague);
  const role = useAuthStore((s) => s.role);
  const isAdmin = role === "admin";
  const [selectedId, setSelectedId] = useState<string | null>(null);

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
      navigate("/home", { replace: true });
    },
  });

  async function handleContinue() {
    if (!selectedId) return;
    if (selectedId === active.data?.league_id) {
      setActiveLeague(selectedId);
      navigate("/home", { replace: true });
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
                {isAdmin
                  ? "Pick an existing league or create a new one. You can switch leagues at any time from the sidebar."
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
                {isAdmin
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
              {isAdmin && (
                <Button
                  variant="outline"
                  onClick={() => navigate("/leagues/new")}
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
                Continue
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
      </div>
    </div>
  );
}

interface LeagueRowProps {
  league: League;
  isActive: boolean;
  isSelected: boolean;
  onSelect: () => void;
}

function LeagueRow({ league, isActive, isSelected, onSelect }: LeagueRowProps) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={cn(
          "flex w-full items-center justify-between gap-4 px-6 py-4 text-left transition",
          isSelected ? "bg-amber/10" : "hover:bg-surfaceAlt/40",
        )}
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
    </li>
  );
}
