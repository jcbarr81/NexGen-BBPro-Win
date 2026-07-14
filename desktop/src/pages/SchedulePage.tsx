/**
 * Phase 4 port of ui/schedule_page.py.
 *
 * Two view modes:
 *   - List: upcoming + results, two-column.
 *   - Calendar: month grid with off-days, the All-Star break window, the
 *     trade deadline, the draft date, and the current sim date all
 *     visually marked. Picks a date to filter the list view.
 *
 * Both modes share the "My team" / "All teams" scope toggle.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CalendarClock,
  CalendarDays,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Gavel,
  Home,
  List,
  Loader2,
  Plane,
  Star,
  Target,
} from "lucide-react";

import {
  api,
  type ScheduleGame,
  type ScheduleMarkers,
  type Team,
} from "@/lib/api";
import { TeamLogo } from "@/components/TeamLogo";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { usePersistedState } from "@/lib/use-persisted-state";
import { useTeams } from "@/lib/use-teams";
import { useVirtualRows } from "@/lib/use-virtual-rows";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

type Scope = "team" | "league";
type ViewMode = "list" | "calendar";

export function SchedulePage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const [scope, setScope] = usePersistedState<Scope>(
    "schedule:scope",
    teamId ? "team" : "league",
  );
  const [view, setView] = usePersistedState<ViewMode>("schedule:view", "list");

  const effectiveScope: Scope = teamId ? scope : "league";

  const schedule = useQuery({
    queryKey: ["schedule", effectiveScope, teamId],
    queryFn: () =>
      api.schedule({
        ...(effectiveScope === "team" && teamId
          ? { teamId }
          : { limit: 5000 }),
        includeMarkers: true,
      }),
  });

  const teamsQ = useTeams();
  const teamById = useMemo(() => {
    const m = new Map<string, Team>();
    for (const t of teamsQ.data ?? []) m.set(t.team_id, t);
    return m;
  }, [teamsQ.data]);

  const games = schedule.data?.games ?? [];
  const markers = schedule.data?.markers;

  const { upcoming, results } = useMemo(() => {
    const up: ScheduleGame[] = [];
    const done: ScheduleGame[] = [];
    for (const g of games) {
      (g.played ? done : up).push(g);
    }
    done.reverse();
    return { upcoming: up, results: done };
  }, [games]);

  return (
    <AppShell
      title="Schedule"
      subtitle={
        effectiveScope === "team" && teamId
          ? `${teamId} · upcoming and played games`
          : "League-wide schedule"
      }
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
            <Pill
              active={effectiveScope === "team"}
              disabled={!teamId}
              onClick={() => setScope("team")}
            >
              My team
            </Pill>
            <Pill
              active={effectiveScope === "league"}
              onClick={() => setScope("league")}
            >
              All teams
            </Pill>
          </div>
          <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
            <Pill active={view === "list"} onClick={() => setView("list")}>
              <List className="mr-1 inline h-3 w-3" /> List
            </Pill>
            <Pill
              active={view === "calendar"}
              onClick={() => setView("calendar")}
            >
              <CalendarDays className="mr-1 inline h-3 w-3" /> Calendar
            </Pill>
          </div>
        </div>
        {schedule.data && (
          <div className="text-xs text-muted">{schedule.data.count} games</div>
        )}
      </div>

      {schedule.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading schedule…</span>
          </CardContent>
        </Card>
      ) : schedule.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(schedule.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : view === "calendar" ? (
        <CalendarView
          games={games}
          markers={markers}
          teamId={effectiveScope === "team" ? teamId : null}
          teamById={teamById}
          onSwitchToList={() => setView("list")}
        />
      ) : (
        <>
          {markers && (
            <MarkerLegend
              markers={markers}
              className="mb-4"
              teamId={effectiveScope === "team" ? teamId : null}
            />
          )}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <ScheduleCard
              title="Upcoming"
              description={`${upcoming.length} scheduled`}
              icon={<CalendarClock className="h-3 w-3" />}
              empty="No upcoming games."
              games={upcoming}
              teamId={effectiveScope === "team" ? teamId : null}
              teamById={teamById}
            />
            <ScheduleCard
              title="Results"
              description={`${results.length} played`}
              icon={<CheckCircle2 className="h-3 w-3" />}
              empty="No games played yet."
              games={results}
              teamId={effectiveScope === "team" ? teamId : null}
              teamById={teamById}
              reverseChrono
            />
          </div>
        </>
      )}
    </AppShell>
  );
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

// ------------------------------- Calendar -------------------------------

interface CalendarViewProps {
  games: ScheduleGame[];
  markers: ScheduleMarkers | undefined;
  teamId: string | null;
  teamById: Map<string, Team>;
  onSwitchToList: () => void;
}

function CalendarView({
  games,
  markers,
  teamId,
  teamById,
  onSwitchToList,
}: CalendarViewProps) {
  // Anchor month: prefer today (sim date) if available; else first game's
  // month; else real today.
  const initialMonth = useMemo(() => {
    const seed =
      markers?.today ?? games[0]?.date ?? new Date().toISOString().slice(0, 10);
    return monthStart(seed);
  }, [markers?.today, games]);

  const [currentMonth, setCurrentMonth] = useState<Date>(initialMonth);
  // Re-anchor when the data first loads (initialMonth changes from a real
  // sim date being available).
  useEffect(() => {
    setCurrentMonth(initialMonth);
  }, [initialMonth]);

  const gamesByDate = useMemo(() => {
    const m = new Map<string, ScheduleGame[]>();
    for (const g of games) {
      const arr = m.get(g.date) ?? [];
      arr.push(g);
      m.set(g.date, arr);
    }
    return m;
  }, [games]);

  const allStarSet = useMemo(
    () => new Set(markers?.all_star_break ?? []),
    [markers?.all_star_break],
  );

  // Bound navigation by season window (with a one-month buffer so users
  // can scroll just past it).
  const minMonth = markers?.season_start
    ? monthStart(markers.season_start)
    : null;
  const maxMonth = markers?.season_end ? monthStart(markers.season_end) : null;

  const monthLabel = currentMonth.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });

  const todayIso = markers?.today ?? null;

  function shiftMonth(delta: number) {
    setCurrentMonth(
      (prev) => new Date(prev.getFullYear(), prev.getMonth() + delta, 1),
    );
  }
  function jumpToToday() {
    if (todayIso) setCurrentMonth(monthStart(todayIso));
  }

  return (
    <div className="space-y-4">
      {markers && <MarkerLegend markers={markers} teamId={teamId} />}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => shiftMonth(-1)}
              disabled={
                minMonth != null && currentMonth.getTime() <= minMonth.getTime()
              }
              className="rounded-md border border-border bg-surfaceAlt p-1 text-muted transition hover:bg-surface hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="Previous month"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <CardTitle className="min-w-[10rem] text-center">
              {monthLabel}
            </CardTitle>
            <button
              type="button"
              onClick={() => shiftMonth(1)}
              disabled={
                maxMonth != null && currentMonth.getTime() >= maxMonth.getTime()
              }
              className="rounded-md border border-border bg-surfaceAlt p-1 text-muted transition hover:bg-surface hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
              aria-label="Next month"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
            {todayIso && (
              <button
                type="button"
                onClick={jumpToToday}
                className="rounded-md border border-border bg-surfaceAlt px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted transition hover:bg-surface hover:text-amber"
              >
                Today
              </button>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-3">
          <CalendarMonth
            month={currentMonth}
            gamesByDate={gamesByDate}
            allStarSet={allStarSet}
            tradeDeadline={markers?.trade_deadline ?? null}
            draftDate={markers?.draft_date ?? null}
            seasonStart={markers?.season_start ?? null}
            seasonEnd={markers?.season_end ?? null}
            todayIso={todayIso}
            teamId={teamId}
            teamById={teamById}
            onPickGame={onSwitchToList}
          />
        </CardContent>
      </Card>
    </div>
  );
}

interface CalendarMonthProps {
  month: Date;
  gamesByDate: Map<string, ScheduleGame[]>;
  allStarSet: Set<string>;
  tradeDeadline: string | null;
  draftDate: string | null;
  seasonStart: string | null;
  seasonEnd: string | null;
  todayIso: string | null;
  teamId: string | null;
  teamById: Map<string, Team>;
  onPickGame: () => void;
}

function CalendarMonth({
  month,
  gamesByDate,
  allStarSet,
  tradeDeadline,
  draftDate,
  seasonStart,
  seasonEnd,
  todayIso,
  teamId,
  teamById,
  onPickGame,
}: CalendarMonthProps) {
  const cells = useMemo(() => buildMonthCells(month), [month]);
  const dayHeaders = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  return (
    <div>
      <div className="mb-2 grid grid-cols-7 gap-1">
        {dayHeaders.map((d) => (
          <div
            key={d}
            className="text-center text-[10px] font-semibold uppercase tracking-wider text-muted"
          >
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((cell, idx) => (
          <DayCell
            key={idx}
            cell={cell}
            currentMonth={month}
            games={gamesByDate.get(cell.iso) ?? []}
            isAllStar={allStarSet.has(cell.iso)}
            isTradeDeadline={tradeDeadline === cell.iso}
            isDraftDate={draftDate === cell.iso}
            isToday={todayIso === cell.iso}
            inSeason={isInSeason(cell.iso, seasonStart, seasonEnd)}
            teamId={teamId}
            teamById={teamById}
            onPickGame={onPickGame}
          />
        ))}
      </div>
    </div>
  );
}

interface DayCellProps {
  cell: { date: Date; iso: string };
  currentMonth: Date;
  games: ScheduleGame[];
  isAllStar: boolean;
  isTradeDeadline: boolean;
  isDraftDate: boolean;
  isToday: boolean;
  inSeason: boolean;
  teamId: string | null;
  teamById: Map<string, Team>;
  onPickGame: () => void;
}

function DayCell({
  cell,
  currentMonth,
  games,
  isAllStar,
  isTradeDeadline,
  isDraftDate,
  isToday,
  inSeason,
  teamId,
  teamById,
  onPickGame,
}: DayCellProps) {
  const inMonth = cell.date.getMonth() === currentMonth.getMonth();
  const hasGames = games.length > 0;
  const isOffDay = inSeason && !hasGames && !isAllStar;

  const teamGame = teamId
    ? games.find(
        (g) => g.home === teamId || g.away === teamId || g.opponent === teamId,
      )
    : null;

  return (
    <div
      className={cn(
        "relative min-h-[5.5rem] rounded-md border p-1.5 text-left transition",
        inMonth ? "border-border bg-surface" : "border-border/30 bg-surface/40",
        isAllStar && "border-amber/50 bg-amber/10",
        isToday && "ring-2 ring-amber ring-offset-1 ring-offset-bg",
        !inSeason && "opacity-60",
      )}
    >
      <div className="mb-1 flex items-start justify-between gap-1">
        <span
          className={cn(
            "text-[11px] font-semibold tabular-nums",
            inMonth ? "text-ink" : "text-subtle",
            isToday && "text-amber",
          )}
        >
          {cell.date.getDate()}
        </span>
        <div className="flex items-center gap-0.5">
          {isDraftDate && (
            <span title="Amateur Draft">
              <Gavel className="h-3 w-3 text-amber" />
            </span>
          )}
          {isTradeDeadline && (
            <span title="Trade deadline">
              <Target className="h-3 w-3 text-danger" />
            </span>
          )}
          {isAllStar && !isDraftDate && !isTradeDeadline && (
            <span title="All-Star break">
              <Star className="h-3 w-3 text-amber" />
            </span>
          )}
        </div>
      </div>

      {isAllStar && (
        <div className="text-[10px] font-semibold uppercase tracking-wider text-amber">
          All-Star
        </div>
      )}

      {isOffDay && (
        <div className="text-[10px] uppercase tracking-wider text-subtle">
          Off
        </div>
      )}

      {hasGames && teamId ? (
        teamGame ? (
          <TeamGameTile
            game={teamGame}
            teamId={teamId}
            teamById={teamById}
            onPick={onPickGame}
          />
        ) : (
          <div className="text-[10px] text-subtle">Off</div>
        )
      ) : hasGames ? (
        <LeagueGameTile games={games} onPick={onPickGame} />
      ) : null}
    </div>
  );
}

function TeamGameTile({
  game,
  teamId,
  teamById,
  onPick,
}: {
  game: ScheduleGame;
  teamId: string;
  teamById: Map<string, Team>;
  onPick: () => void;
}) {
  const isHome = game.is_home ?? game.home === teamId;
  const opponent = game.opponent ?? (isHome ? game.away : game.home);
  const oppMeta = teamById.get(opponent);
  const tone = game.played
    ? game.result?.startsWith("W")
      ? "border-success/60 bg-success/10 text-success"
      : game.result?.startsWith("L")
        ? "border-danger/60 bg-danger/10 text-danger"
        : "border-border bg-surfaceAlt text-muted"
    : "border-amber/40 bg-amber/5 text-ink";

  const boxLink = game.boxscore
    ? `/boxscore?path=${encodeURIComponent(game.boxscore)}`
    : null;

  const inner = (
    <div
      className={cn(
        "flex items-center gap-1 rounded border px-1 py-0.5 text-[10px]",
        tone,
      )}
    >
      {isHome ? (
        <Home className="h-2.5 w-2.5 shrink-0" aria-label="Home" />
      ) : (
        <Plane className="h-2.5 w-2.5 shrink-0" aria-label="Away" />
      )}
      <TeamLogo
        teamId={opponent}
        abbreviation={oppMeta?.abbreviation || opponent}
        primaryColor={oppMeta?.primary_color}
        secondaryColor={oppMeta?.secondary_color}
        className="h-3.5 w-3.5 shrink-0 rounded text-[7px]"
      />
      <span className="truncate font-semibold">
        {oppMeta?.abbreviation || opponent}
      </span>
      {game.played && game.result && (
        <span className="ml-auto font-semibold tabular-nums">
          {game.result}
        </span>
      )}
    </div>
  );

  if (boxLink) {
    return (
      <Link to={boxLink} onClick={onPick} title="View boxscore">
        {inner}
      </Link>
    );
  }
  return <div title={`${isHome ? "vs" : "@"} ${opponent}`}>{inner}</div>;
}

function LeagueGameTile({
  games,
  onPick,
}: {
  games: ScheduleGame[];
  onPick: () => void;
}) {
  const played = games.filter((g) => g.played).length;
  const total = games.length;
  return (
    <button
      type="button"
      onClick={onPick}
      className="w-full rounded border border-border/60 bg-surfaceAlt/60 px-1 py-0.5 text-[10px] text-muted transition hover:border-amber/60 hover:text-amber"
      title={`${total} games — ${played} played`}
    >
      <span className="font-semibold tabular-nums">{total}</span>{" "}
      {total === 1 ? "game" : "games"}
      {played > 0 && played < total && (
        <span className="ml-1 text-subtle">({played} done)</span>
      )}
    </button>
  );
}

function MarkerLegend({
  markers,
  className,
  teamId,
}: {
  markers: ScheduleMarkers;
  className?: string;
  teamId: string | null;
}) {
  const items: Array<{
    label: string;
    icon: React.ReactNode;
    value: string | null;
    tone: "amber" | "danger" | "success" | "neutral";
  }> = [];

  if (markers.today) {
    items.push({
      label: "Today",
      icon: <CalendarClock className="h-3 w-3" />,
      value: formatDate(markers.today),
      tone: "success",
    });
  }
  const first = markers.all_star_break[0];
  const last = markers.all_star_break[markers.all_star_break.length - 1];
  if (first && last) {
    items.push({
      label: "All-Star break",
      icon: <Star className="h-3 w-3" />,
      value:
        first === last
          ? formatDate(first)
          : `${formatDate(first)} – ${formatDate(last)}`,
      tone: "amber",
    });
  }
  items.push({
    label: "Trade deadline",
    icon: <Target className="h-3 w-3" />,
    value: formatDate(markers.trade_deadline),
    tone: "danger",
  });
  if (markers.draft_date) {
    items.push({
      label: "Amateur draft",
      icon: <Gavel className="h-3 w-3" />,
      value: formatDate(markers.draft_date),
      tone: "amber",
    });
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {items.map((item) => (
        <Badge
          key={item.label}
          tone={item.tone}
          className="text-[11px]"
          title={teamId ? `${item.label} (showing ${teamId})` : item.label}
        >
          {item.icon}
          <span className="ml-1 font-semibold">{item.label}:</span>
          <span className="ml-1 tabular-nums">{item.value}</span>
        </Badge>
      ))}
    </div>
  );
}

// ------------------------------- List view -------------------------------

interface ScheduleCardProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  empty: string;
  games: ScheduleGame[];
  teamId: string | null;
  teamById: Map<string, Team>;
  reverseChrono?: boolean;
}

function ScheduleCard({
  title,
  description,
  icon,
  empty,
  games,
  teamId,
  teamById,
}: ScheduleCardProps) {
  // A full-season league scope can be thousands of games — virtualize the
  // list so only the visible window of rows mounts.
  const rowVirtual = useVirtualRows({
    count: games.length,
    estimateRowHeight: 53,
  });

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <Badge tone="amber">
          {icon} {games.length}
        </Badge>
      </CardHeader>
      <CardContent className="p-0">
        {games.length === 0 ? (
          <div className="px-6 py-6 text-sm text-muted">{empty}</div>
        ) : (
          <div
            ref={rowVirtual.scrollRef}
            className="max-h-[70vh] overflow-y-auto"
          >
            <ul className="divide-y divide-border/60">
              {rowVirtual.paddingTop > 0 && (
                <li
                  aria-hidden="true"
                  style={{ height: rowVirtual.paddingTop }}
                />
              )}
              {rowVirtual.items.map((vi) => {
                const game = games[vi.index];
                if (!game) return null;
                return (
                  <GameRow
                    key={`${game.date}-${game.home}-${game.away}-${vi.index}`}
                    index={vi.index}
                    measureRef={rowVirtual.measureRow}
                    game={game}
                    teamId={teamId}
                    teamById={teamById}
                  />
                );
              })}
              {rowVirtual.paddingBottom > 0 && (
                <li
                  aria-hidden="true"
                  style={{ height: rowVirtual.paddingBottom }}
                />
              )}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GameRow({
  game,
  teamId,
  teamById,
  index,
  measureRef,
}: {
  game: ScheduleGame;
  teamId: string | null;
  teamById: Map<string, Team>;
  index: number;
  measureRef: (node: Element | null) => void;
}) {
  const isTeamView = !!teamId;
  const isHome = game.is_home ?? game.home === teamId;
  const opponent = game.opponent ?? (isHome ? game.away : game.home);

  const logoFor = (tid: string | undefined, size = "h-5 w-5") => {
    if (!tid) return null;
    const t = teamById.get(tid);
    return (
      <TeamLogo
        teamId={tid}
        abbreviation={t?.abbreviation || tid}
        primaryColor={t?.primary_color}
        secondaryColor={t?.secondary_color}
        className={`${size} shrink-0 rounded text-[9px]`}
      />
    );
  };

  return (
    <li
      data-index={index}
      ref={measureRef}
      className="flex items-center justify-between gap-4 px-6 py-3 text-sm transition hover:bg-surfaceAlt/40"
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className="w-20 shrink-0 text-xs font-semibold uppercase tracking-wider text-muted">
          {formatDate(game.date)}
        </div>
        {isTeamView ? (
          <div className="flex items-center gap-2">
            {isHome ? (
              <Home className="h-4 w-4 text-amber" aria-label="Home" />
            ) : (
              <Plane className="h-4 w-4 text-muted" aria-label="Away" />
            )}
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">
              {isHome ? "vs" : "@"}
            </span>
            {logoFor(opponent, "h-5 w-5")}
            <span className="font-semibold">{opponent}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2 font-semibold">
            {logoFor(game.away, "h-5 w-5")}
            <span>{game.away}</span>
            <span className="text-muted">@</span>
            {logoFor(game.home, "h-5 w-5")}
            <span>{game.home}</span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        {game.played ? (
          game.boxscore ? (
            <Link
              to={`/boxscore?path=${encodeURIComponent(game.boxscore)}`}
              title="View boxscore"
            >
              <Badge
                tone="neutral"
                className="cursor-pointer hover:border-amber/60 hover:text-amber-text"
              >
                {game.result || "Final"}
              </Badge>
            </Link>
          ) : (
            <Badge tone="neutral">{game.result || "Final"}</Badge>
          )
        ) : (
          <Badge tone="amber">Scheduled</Badge>
        )}
      </div>
    </li>
  );
}

// ------------------------------- helpers -------------------------------

function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function monthStart(iso: string): Date {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function buildMonthCells(month: Date): Array<{ date: Date; iso: string }> {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const startOffset = first.getDay(); // 0 = Sunday
  const start = new Date(first);
  start.setDate(start.getDate() - startOffset);

  const cells: Array<{ date: Date; iso: string }> = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    cells.push({ date: d, iso: toIsoLocal(d) });
  }
  return cells;
}

function toIsoLocal(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isInSeason(
  iso: string,
  start: string | null,
  end: string | null,
): boolean {
  if (!start || !end) return true;
  return iso >= start && iso <= end;
}
