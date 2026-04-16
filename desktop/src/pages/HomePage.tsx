/**
 * Phase 3 home page showcases the new design system while still proving
 * the authenticated session round-trips against `/leagues` and `/teams`.
 * Phase 4 replaces this with the real owner dashboard port.
 */

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  BarChart3,
  LayoutDashboard,
  Loader2,
  Trophy,
  Users,
} from "lucide-react";

import { api } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { StatCard } from "@/components/StatCard";
import {
  Badge,
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

export function HomePage() {
  const leagues = useQuery({
    queryKey: ["leagues"],
    queryFn: () => api.listLeagues(),
  });
  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
  });

  return (
    <AppShell
      title="Dashboard"
      subtitle="A preview of the Phase 3 design system on live sidecar data."
    >
      <div className="space-y-6 animate-fade-in">
        <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatCard
            label="Leagues"
            value={leagues.data?.length ?? (leagues.isLoading ? "…" : 0)}
            sub="Registered in league_registry.json"
            Icon={Trophy}
            tone="amber"
          />
          <StatCard
            label="Teams"
            value={teams.data?.length ?? (teams.isLoading ? "…" : 0)}
            sub="Loaded from teams.csv"
            Icon={Users}
          />
          <StatCard
            label="Phase"
            value="3 / 9"
            sub="Design system complete"
            Icon={LayoutDashboard}
            tone="success"
          />
        </section>

        <Tabs defaultValue="leagues">
          <TabsList>
            <TabsTrigger value="leagues">Leagues</TabsTrigger>
            <TabsTrigger value="teams">Teams</TabsTrigger>
          </TabsList>

          <TabsContent value="leagues">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>League registry</CardTitle>
                  <CardDescription>Fetched from <code>/leagues</code>.</CardDescription>
                </div>
                <Badge tone="amber">
                  <BarChart3 className="h-3 w-3" /> GET /leagues
                </Badge>
              </CardHeader>
              <CardContent className="p-0">
                <QueryList
                  isLoading={leagues.isLoading}
                  isError={leagues.isError}
                  error={leagues.error}
                  items={leagues.data}
                  renderItem={(league) => (
                    <Row
                      key={String(league.id)}
                      title={String(league.display_name ?? league.id)}
                      subtitle={`id: ${String(league.id)}`}
                      badge={String(league.status ?? "")}
                    />
                  )}
                  emptyMessage="No leagues registered yet."
                />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="teams">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>Teams</CardTitle>
                  <CardDescription>Fetched from <code>/teams</code>.</CardDescription>
                </div>
                <Badge tone="amber">
                  <Users className="h-3 w-3" /> GET /teams
                </Badge>
              </CardHeader>
              <CardContent className="p-0">
                <QueryList
                  isLoading={teams.isLoading}
                  isError={teams.isError}
                  error={teams.error}
                  items={teams.data}
                  renderItem={(team) => (
                    <Row
                      key={String(team.team_id)}
                      title={`${String(team.city ?? "")} ${String(team.name ?? "")}`.trim()}
                      subtitle={`${String(team.abbreviation ?? "")} · ${String(team.division ?? "")}`}
                      swatch={String(team.primary_color ?? "")}
                    />
                  )}
                  emptyMessage="No teams configured."
                />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </AppShell>
  );
}

interface QueryListProps<T> {
  isLoading: boolean;
  isError: boolean;
  error?: unknown;
  items?: T[];
  renderItem: (item: T) => React.ReactNode;
  emptyMessage: string;
}

function QueryList<T>({
  isLoading,
  isError,
  error,
  items,
  renderItem,
  emptyMessage,
}: QueryListProps<T>) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-6 py-8 text-sm text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }
  if (isError) {
    return (
      <div className="px-6 py-6 text-sm text-danger">
        {(error as Error)?.message ?? "Request failed."}
      </div>
    );
  }
  if (!items || items.length === 0) {
    return <div className="px-6 py-6 text-sm text-muted">{emptyMessage}</div>;
  }
  return <ul className="divide-y divide-border/60">{items.map(renderItem)}</ul>;
}

interface RowProps {
  title: string;
  subtitle?: string;
  badge?: string;
  swatch?: string;
}

function Row({ title, subtitle, badge, swatch }: RowProps) {
  return (
    <li className="flex items-center justify-between gap-4 px-6 py-3 text-sm transition hover:bg-surfaceAlt/40">
      <div className="flex min-w-0 items-center gap-3">
        {swatch && (
          <span
            className="h-5 w-5 shrink-0 rounded-full border border-border"
            style={{ backgroundColor: swatch }}
            aria-hidden
          />
        )}
        <div className="min-w-0">
          <div className="truncate font-semibold">{title}</div>
          {subtitle && (
            <div className="truncate text-xs text-muted">{subtitle}</div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {badge && <Badge tone="neutral">{badge}</Badge>}
        <ArrowRight className="h-4 w-4 text-muted" aria-hidden />
      </div>
    </li>
  );
}
