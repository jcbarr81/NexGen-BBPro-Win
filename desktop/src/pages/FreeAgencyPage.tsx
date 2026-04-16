/**
 * Phase 4 port of ui/free_agency_window.py.
 *
 * Lists every player not on a team's roster and lets the active team sign
 * them at any roster level. Sorting + filter + position picker keep the
 * scan manageable; signing immediately invalidates roster + activity
 * caches so the rest of the UI stays in sync.
 */

import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Loader2,
  Search,
  UserPlus,
  Users,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";

type SortKey = "name" | "pos" | "role" | "bats" | string;
type SortDir = "asc" | "desc";
type Filter = "all" | "hitters" | "pitchers";

const HITTER_COLUMNS: Array<{ key: string; label: string }> = [
  { key: "ch", label: "CH" },
  { key: "ph", label: "PH" },
  { key: "sp", label: "SP" },
  { key: "eye", label: "EYE" },
  { key: "fa", label: "FA" },
];
const PITCHER_COLUMNS: Array<{ key: string; label: string }> = [
  { key: "fb", label: "FB" },
  { key: "control", label: "CTRL" },
  { key: "movement", label: "MOV" },
  { key: "endurance", label: "END" },
];

type FreeAgent = NonNullable<
  Awaited<ReturnType<typeof api.freeAgents>>
>["free_agents"][number];

export function FreeAgencyPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [position, setPosition] = useState<string>("");
  const [signing, setSigning] = useState<FreeAgent | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const list = useQuery({
    queryKey: ["free-agents"],
    queryFn: () => api.freeAgents(2000),
  });

  const positions = useMemo(() => {
    const s = new Set<string>();
    for (const fa of list.data?.free_agents ?? []) {
      if (fa.primary_position) s.add(fa.primary_position);
    }
    return [...s].sort();
  }, [list.data]);

  const filtered = useMemo(() => {
    let rows = list.data?.free_agents ?? [];
    if (filter === "hitters") rows = rows.filter((r) => !r.is_pitcher);
    if (filter === "pitchers") rows = rows.filter((r) => r.is_pitcher);
    if (position)
      rows = rows.filter((r) => r.primary_position === position);
    if (search.trim()) {
      const needle = search.trim().toLowerCase();
      rows = rows.filter((r) =>
        `${r.first_name} ${r.last_name} ${r.player_id}`
          .toLowerCase()
          .includes(needle),
      );
    }
    const sorted = [...rows];
    sorted.sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      const as = String(av).toLowerCase();
      const bs = String(bv).toLowerCase();
      if (as < bs) return sortDir === "asc" ? -1 : 1;
      if (as > bs) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [list.data, filter, position, search, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir(key === "name" || key === "pos" ? "asc" : "desc");
    }
  }

  const pitcherHeavy =
    filter === "pitchers" ||
    (filter === "all" &&
      filtered.length > 0 &&
      filtered.filter((p) => p.is_pitcher).length / filtered.length > 0.5);
  const columns = pitcherHeavy ? PITCHER_COLUMNS : HITTER_COLUMNS;

  return (
    <AppShell
      title="Free Agency"
      subtitle={`${list.data?.count ?? 0} unsigned players`}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-9"
              placeholder="Search by name or id…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
            {(["all", "hitters", "pitchers"] as const).map((opt) => (
              <Pill
                key={opt}
                active={filter === opt}
                onClick={() => setFilter(opt)}
              >
                {opt}
              </Pill>
            ))}
          </div>
          <select
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            className="h-9 rounded-md border border-border bg-canvas/60 px-2 text-xs font-semibold uppercase tracking-wider text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
          >
            <option value="">All positions</option>
            {positions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <span className="text-xs text-muted">{filtered.length} shown</span>
      </div>

      {list.isLoading ? (
        <LoadingCard />
      ) : list.isError ? (
        <ErrorCard message={(list.error as Error).message} />
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Users className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">No free agents</h2>
            <p className="max-w-sm text-sm text-muted">
              Either every player is signed or your filter is too tight.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Available</CardTitle>
            <Badge tone="amber">
              <Users className="h-3 w-3" /> {filtered.length}
            </Badge>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                    <HeaderCell label="Player" keyId="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} align="left" />
                    <HeaderCell label="Pos" keyId="pos" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    <HeaderCell label="B" keyId="bats" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    <HeaderCell label="Role" keyId="role" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                    {columns.map((c) => (
                      <HeaderCell
                        key={c.key}
                        label={c.label}
                        keyId={c.key}
                        sortKey={sortKey}
                        sortDir={sortDir}
                        onClick={toggleSort}
                      />
                    ))}
                    <th className="px-4 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((fa) => (
                    <tr
                      key={fa.player_id}
                      className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
                    >
                      <td className="px-6 py-2">
                        <Link
                          to={`/player/${encodeURIComponent(fa.player_id)}`}
                          className="font-semibold hover:text-amber"
                        >
                          {fa.last_name}
                          {fa.first_name ? `, ${fa.first_name}` : ""}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                        {fa.primary_position || "—"}
                      </td>
                      <td className="px-3 py-2 text-right">{fa.bats || "—"}</td>
                      <td className="px-3 py-2 text-right text-xs uppercase tracking-wider text-muted">
                        {fa.role || (fa.is_pitcher ? "PIT" : "POS")}
                      </td>
                      {columns.map((col) => (
                        <td key={col.key} className="px-3 py-2 text-right tabular-nums">
                          <RatingCell value={fa.ratings[col.key]} />
                        </td>
                      ))}
                      <td className="px-4 py-2 text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setSigning(fa)}
                          disabled={!teamId}
                          title={teamId ? "Sign to your team" : "No active team"}
                        >
                          <UserPlus className="h-3 w-3" /> Sign
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <SignDialog
        player={signing}
        teamId={teamId}
        onClose={() => setSigning(null)}
      />
    </AppShell>
  );
}

function SignDialog({
  player,
  teamId,
  onClose,
}: {
  player: FreeAgent | null;
  teamId: string | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [level, setLevel] = useState<"ACT" | "AAA" | "LOW">("ACT");
  const [error, setError] = useState<string | null>(null);

  const sign = useMutation({
    mutationFn: () => {
      if (!player || !teamId) return Promise.reject(new Error("No team"));
      return api.signFreeAgent(teamId, {
        player_id: player.player_id,
        level,
      });
    },
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["free-agents"] });
      queryClient.invalidateQueries({ queryKey: ["team-roster"] });
      queryClient.invalidateQueries({ queryKey: ["activity"] });
      onClose();
    },
    onError: (err) =>
      setError(err instanceof Error ? err.message : "Sign failed."),
  });

  function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    sign.mutate();
  }

  return (
    <Dialog open={!!player} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            Sign {player?.last_name}
            {player?.first_name ? `, ${player.first_name}` : ""}
          </DialogTitle>
          <DialogDescription>
            Adds the player to {teamId ?? "—"} at the chosen roster level.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label>Roster level</Label>
            <div className="flex rounded-lg border border-border bg-surfaceAlt p-1">
              {(["ACT", "AAA", "LOW"] as const).map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => setLevel(opt)}
                  className={cn(
                    "flex-1 rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                    level === opt
                      ? "bg-amber text-espresso"
                      : "text-muted hover:bg-surface hover:text-ink",
                  )}
                >
                  {opt}
                </button>
              ))}
            </div>
          </div>
          {error && (
            <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={sign.isPending || !teamId}>
              {sign.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Sign
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function sortValue(p: FreeAgent, key: SortKey): string | number | null {
  switch (key) {
    case "name":
      return `${p.last_name}, ${p.first_name}`;
    case "pos":
      return p.primary_position;
    case "bats":
      return p.bats;
    case "role":
      return p.role;
    default: {
      const raw = p.ratings[key];
      if (raw == null) return null;
      const n = typeof raw === "number" ? raw : Number(raw);
      return Number.isFinite(n) ? n : String(raw);
    }
  }
}

function HeaderCell({
  label,
  keyId,
  sortKey,
  sortDir,
  onClick,
  align = "right",
}: {
  label: string;
  keyId: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === keyId;
  const Arrow = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown;
  return (
    <th
      className={cn(
        "select-none px-3 py-2 font-semibold",
        align === "left" ? "pl-6 text-left" : "text-right",
      )}
    >
      <button
        type="button"
        onClick={() => onClick(keyId)}
        className={cn(
          "inline-flex items-center gap-1 hover:text-ink",
          active ? "text-ink" : "text-muted",
          align === "right" && "flex-row-reverse",
        )}
      >
        <Arrow className="h-3 w-3" />
        {label}
      </button>
    </th>
  );
}

function RatingCell({ value }: { value: number | string | null | undefined }) {
  if (value == null || value === "") return <span className="text-subtle">—</span>;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return <>{String(value)}</>;
  const tone =
    n >= 85 ? "text-success" : n >= 70 ? "text-amber-text" : n >= 50 ? "text-ink" : "text-subtle";
  return <span className={tone}>{Math.round(n)}</span>;
}

function Pill({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
        active
          ? "bg-amber text-espresso"
          : "text-muted hover:bg-surface hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading free agents…</span>
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
