/**
 * Phase 4 port of ui/news_window.py.
 *
 * Reads the narrative news feed (data/news_feed.txt) via the sidecar with
 * a substring filter and a "my team" toggle. Lines are pre-parsed
 * server-side into {timestamp, category, team, message} so the UI can
 * render badges instead of raw strings.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeftRight,
  Award,
  ChevronUp,
  Flag,
  GraduationCap,
  HeartPulse,
  Inbox,
  Loader2,
  Medal,
  Newspaper,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  Trophy,
  Users,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { usePersistedState } from "@/lib/use-persisted-state";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  Input,
} from "@/components/ui";

type Scope = "team" | "all";

export function NewsPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const [scope, setScope] = usePersistedState<Scope>(
    "news:scope",
    teamId ? "team" : "all",
  );
  const [search, setSearch] = usePersistedState("news:search", "");
  const [category, setCategory] = usePersistedState<string>(
    "news:category",
    "",
  );

  const effectiveScope: Scope = teamId ? scope : "all";

  const news = useQuery({
    queryKey: ["news", effectiveScope, teamId, search, category],
    queryFn: () =>
      api.news({
        q: search || undefined,
        teamId: effectiveScope === "team" ? (teamId as string) : undefined,
        category: category || undefined,
        limit: 500,
      }),
  });

  return (
    <AppShell
      title="News Feed"
      subtitle={
        effectiveScope === "team" && teamId
          ? `Headlines tagged ${teamId}`
          : "League-wide narrative feed"
      }
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
          <Pill
            active={effectiveScope === "team"}
            disabled={!teamId}
            onClick={() => setScope("team")}
          >
            My team
          </Pill>
          <Pill
            active={effectiveScope === "all"}
            onClick={() => setScope("all")}
          >
            All teams
          </Pill>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative w-64">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-9"
              placeholder="Filter…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Refresh"
            onClick={() => news.refetch()}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
          {news.data && (
            <span className="text-xs text-muted">{news.data.count} items</span>
          )}
        </div>
      </div>

      {/* Category filter chips. Always shows "All" plus whatever
          categories the server reports for the current scope. */}
      {news.data && news.data.categories.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <CategoryChip
            id=""
            label="All"
            count={news.data.categories.reduce((sum, c) => sum + c.count, 0)}
            active={category === ""}
            onClick={() => setCategory("")}
          />
          {news.data.categories.map((c) => (
            <CategoryChip
              key={c.id}
              id={c.id}
              label={categoryLabel(c.id)}
              count={c.count}
              active={category === c.id}
              onClick={() => setCategory(category === c.id ? "" : c.id)}
            />
          ))}
        </div>
      )}

      {news.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading news…</span>
          </CardContent>
        </Card>
      ) : news.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(news.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : !news.data || news.data.items.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Newspaper className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">No headlines</h2>
            <p className="max-w-sm text-sm text-muted">
              The news feed is empty for this filter.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <ul className="divide-y divide-border/60">
              {news.data.items.map((item, i) => (
                <NewsRow key={`${item.timestamp}-${i}`} item={item} />
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </AppShell>
  );
}

function NewsRow({
  item,
}: {
  item: {
    timestamp: string;
    category: string;
    team: string;
    message: string;
    raw: string;
  };
}) {
  const tone = toneFor(item.category);
  return (
    <li className="flex items-start gap-3 px-6 py-3 text-sm">
      <div
        className={cn(
          "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border",
          tone,
        )}
      >
        <CategoryIcon category={item.category} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          {item.timestamp && (
            <span className="text-[10px] uppercase tracking-wider text-muted">
              {formatStamp(item.timestamp)}
            </span>
          )}
          {item.category && (
            <Badge tone={badgeToneFor(item.category)}>{item.category}</Badge>
          )}
          {item.team && (
            <Link
              to={`/team/${encodeURIComponent(item.team)}`}
              className="text-xs font-semibold uppercase tracking-wider text-amber-text hover:text-amber"
            >
              {item.team}
            </Link>
          )}
        </div>
        <p className="mt-0.5 leading-snug">
          {item.message || item.raw}
        </p>
      </div>
    </li>
  );
}

function CategoryIcon({ category }: { category: string }) {
  const c = category.toLowerCase();
  if (c.includes("injur")) return <HeartPulse className="h-3 w-3" />;
  if (c.includes("retir")) return <Flag className="h-3 w-3" />;
  if (c.includes("promot") || c.includes("callup")) return <ChevronUp className="h-3 w-3" />;
  if (c.includes("trade")) return <ArrowLeftRight className="h-3 w-3" />;
  if (c.includes("draft")) return <GraduationCap className="h-3 w-3" />;
  if (c.includes("hof") || c.includes("hall")) return <Medal className="h-3 w-3" />;
  if (c.includes("award")) return <Award className="h-3 w-3" />;
  if (c.includes("all_star") || c.includes("all-star")) return <Star className="h-3 w-3" />;
  if (c.includes("milestone") || c.includes("record"))
    return <Sparkles className="h-3 w-3" />;
  if (c.includes("transaction") || c.includes("sign")) return <Inbox className="h-3 w-3" />;
  if (c.includes("roster")) return <Users className="h-3 w-3" />;
  return <Newspaper className="h-3 w-3" />;
}

function toneFor(category: string): string {
  const c = category.toLowerCase();
  if (c.includes("injur")) return "border-warning/40 bg-warning/10 text-warning";
  if (c.includes("retir")) return "border-muted bg-surfaceAlt text-muted";
  if (c.includes("promot") || c.includes("callup"))
    return "border-success/40 bg-success/10 text-success";
  if (c.includes("trade") || c.includes("transaction") || c.includes("sign"))
    return "border-amber/40 bg-amber/10 text-amber-text";
  if (c.includes("draft")) return "border-amber/40 bg-amber/10 text-amber-text";
  if (
    c.includes("milestone") ||
    c.includes("award") ||
    c.includes("hof") ||
    c.includes("hall") ||
    c.includes("all_star") ||
    c.includes("all-star")
  )
    return "border-success/40 bg-success/10 text-success";
  return "border-border bg-surfaceAlt text-muted";
}

function badgeToneFor(
  category: string,
): "amber" | "success" | "danger" | "warning" | "neutral" {
  const c = category.toLowerCase();
  if (c.includes("injur")) return "warning";
  if (c.includes("trade") || c.includes("transaction") || c.includes("sign"))
    return "amber";
  if (c.includes("draft")) return "amber";
  if (
    c.includes("promot") ||
    c.includes("callup") ||
    c.includes("milestone") ||
    c.includes("award") ||
    c.includes("hof") ||
    c.includes("hall") ||
    c.includes("all_star") ||
    c.includes("all-star")
  )
    return "success";
  return "neutral";
}

function categoryLabel(id: string): string {
  if (!id) return "All";
  // Pretty-print snake_case → Title Case while leaving common words alone.
  const words = id.split(/[_-]+/);
  return words
    .map((w) =>
      w === "hof"
        ? "HOF"
        : w === "mvp"
          ? "MVP"
          : w.charAt(0).toUpperCase() + w.slice(1),
    )
    .join(" ");
}

function CategoryChip({
  id,
  label,
  count,
  active,
  onClick,
}: {
  id: string;
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  const tone = id ? toneFor(id) : "border-border bg-surfaceAlt text-muted";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
        active
          ? "border-amber bg-amber/20 text-amber-text"
          : `${tone} hover:border-amber/60`,
      )}
    >
      {id && <CategoryIcon category={id} />}
      <span>{label}</span>
      <span className="opacity-60">{count}</span>
    </button>
  );
}

function formatStamp(raw: string): string {
  // Source format is "YYYY-MM-DD HH:MM:SS"; collapse to short date + HH:MM.
  if (!raw) return "";
  const m = raw.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/);
  if (!m) return raw;
  const d = new Date(`${m[1]}T${m[2]}:00`);
  if (Number.isNaN(d.getTime())) return raw;
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })} · ${m[2]}`;
}

function Pill({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
        active
          ? "bg-amber text-espresso"
          : "text-muted hover:bg-surface hover:text-ink",
        disabled && "pointer-events-none opacity-50",
      )}
    >
      {children}
    </button>
  );
}
