/**
 * Phase 4 port of ui/league_command_center_window.py.
 *
 * Renders the league-wide operations dashboard: phase + current sim date,
 * league overview counts, and a grid of status cards (injuries, finance,
 * free agency, draft, etc.) each with severity + summary + item list.
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  RefreshCw,
} from "lucide-react";

import { api } from "@/lib/api";
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

export function CommandCenterPage() {
  const snapshot = useQuery({
    queryKey: ["command-center"],
    queryFn: () => api.commandCenter(),
  });

  return (
    <AppShell
      title="Command Center"
      subtitle={
        snapshot.data
          ? `${snapshot.data.league_id} · ${snapshot.data.phase}${
              snapshot.data.sim_date ? ` · ${snapshot.data.sim_date}` : ""
            }`
          : "League-wide operations dashboard"
      }
    >
      <div className="mb-4 flex items-center justify-end">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Refresh"
          onClick={() => snapshot.refetch()}
        >
          <RefreshCw className="h-4 w-4" />
        </Button>
      </div>
      {snapshot.isLoading ? (
        <LoadingCard />
      ) : snapshot.isError ? (
        <ErrorCard message={(snapshot.error as Error).message} />
      ) : snapshot.data ? (
        <div className="space-y-6">
          <OverviewRow overview={snapshot.data.overview} />
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {snapshot.data.cards.map((card) => (
              <CommandCard key={card.card_id} card={card} />
            ))}
          </div>
        </div>
      ) : null}
    </AppShell>
  );
}

function OverviewRow({ overview }: { overview: Record<string, number> }) {
  const entries = Object.entries(overview);
  if (entries.length === 0) return null;
  return (
    <Card>
      <CardContent className="grid grid-cols-2 gap-3 p-4 sm:grid-cols-4 lg:grid-cols-6">
        {entries.map(([key, value]) => (
          <div
            key={key}
            className="rounded-xl border border-border bg-surfaceAlt/40 p-3 text-center"
          >
            <div className="font-display text-2xl font-bold tabular-nums text-amber-text">
              {value}
            </div>
            <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
              {key.replace(/_/g, " ")}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

interface CCCard {
  card_id: string;
  title: string;
  severity: string;
  summary: string;
  count: number;
  items: Array<Record<string, unknown>>;
  actions: string[];
}

function CommandCard({ card }: { card: CCCard }) {
  const sev = card.severity.toLowerCase();
  const Icon =
    sev === "critical"
      ? AlertOctagon
      : sev === "warning"
        ? AlertTriangle
        : sev === "success" || sev === "ok"
          ? CheckCircle2
          : Info;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="text-base">{card.title}</CardTitle>
          <CardDescription>{card.summary || "—"}</CardDescription>
        </div>
        <Badge tone={severityTone(card.severity)}>
          <Icon className="h-3 w-3" /> {card.count}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {card.items.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">Nothing to report.</div>
        ) : (
          <ul className="divide-y divide-border/60">
            {card.items.slice(0, 8).map((item, i) => (
              <li key={i} className="px-6 py-2 text-sm">
                <ItemRow item={item} />
              </li>
            ))}
          </ul>
        )}
        {card.actions.length > 0 && (
          <div className="flex flex-wrap gap-2 border-t border-border/60 bg-surfaceAlt/40 px-6 py-2 text-[11px] uppercase tracking-wider text-muted">
            Suggested:
            {card.actions.map((action) => (
              <span key={action}>{action}</span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ItemRow({ item }: { item: Record<string, unknown> }) {
  // Common shape across cards: { title, detail, severity?, team_id?, player_id? }
  const title = String(item.title ?? item.name ?? item.label ?? "—");
  const detail = String(item.detail ?? item.description ?? item.summary ?? "");
  const sev = String(item.severity ?? "");
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="truncate font-semibold">{title}</div>
        {detail && <div className="truncate text-xs text-muted">{detail}</div>}
      </div>
      {sev && (
        <Badge tone={severityTone(sev)} className="ml-2 shrink-0">
          {sev}
        </Badge>
      )}
    </div>
  );
}

function severityTone(
  severity: string,
): "danger" | "warning" | "amber" | "success" | "neutral" {
  const s = severity.toLowerCase();
  if (s === "critical" || s === "error") return "danger";
  if (s === "warning") return "warning";
  if (s === "info") return "amber";
  if (s === "success" || s === "ok") return "success";
  return "neutral";
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading command center…</span>
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

