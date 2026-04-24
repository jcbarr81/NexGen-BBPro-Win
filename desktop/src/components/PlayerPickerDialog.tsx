/**
 * League-wide player picker — ports ``ComparisonSelectorDialog`` from
 * ``ui/player_profile_dialog.py``. Search by name / id, select one, and
 * fire ``onPick(player_id)``. Caller decides what to do with the pick
 * (e.g. navigate to the compare page).
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
} from "@/components/ui";

interface PlayerPickerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Player id to exclude from the list (usually the current page's subject). */
  excludeId?: string;
  title?: string;
  description?: string;
  onPick: (playerId: string) => void;
}

export function PlayerPickerDialog({
  open,
  onOpenChange,
  excludeId,
  title = "Select a player",
  description = "Search league players by name or id.",
  onPick,
}: PlayerPickerDialogProps) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setQuery("");
      setSelectedId(null);
    }
  }, [open]);

  const players = useQuery({
    queryKey: ["browse-players", "picker"],
    queryFn: () => api.browsePlayers({ limit: 2000 }),
    enabled: open,
    staleTime: 30_000,
  });

  const filtered = useMemo(() => {
    const rows = players.data?.players ?? [];
    const needle = query.trim().toLowerCase();
    let out = rows;
    if (excludeId) out = out.filter((p) => p.player_id !== excludeId);
    if (needle) {
      out = out.filter((p) => {
        const name = `${p.first_name} ${p.last_name} ${p.player_id}`.toLowerCase();
        return name.includes(needle);
      });
    }
    return out.slice(0, 500);
  }, [players.data, query, excludeId]);

  useEffect(() => {
    if (filtered.length > 0 && !filtered.some((p) => p.player_id === selectedId)) {
      setSelectedId(filtered[0].player_id);
    }
  }, [filtered, selectedId]);

  function accept() {
    if (selectedId) onPick(selectedId);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name or id…"
            className="pl-9"
          />
        </div>

        <div className="mt-3 max-h-80 overflow-y-auto rounded-lg border border-border bg-canvas/40">
          {players.isLoading ? (
            <div className="flex items-center gap-2 px-4 py-6 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading players…
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-4 py-6 text-sm text-muted">No matches.</div>
          ) : (
            <ul className="divide-y divide-border/40">
              {filtered.map((p) => {
                const name = `${p.first_name} ${p.last_name}`.trim() || p.player_id;
                const isSelected = p.player_id === selectedId;
                return (
                  <li key={p.player_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(p.player_id)}
                      onDoubleClick={() => {
                        setSelectedId(p.player_id);
                        accept();
                      }}
                      className={cn(
                        "flex w-full items-center justify-between gap-3 px-4 py-2 text-left text-sm transition",
                        isSelected
                          ? "bg-amber/10 text-ink"
                          : "hover:bg-surfaceAlt/40",
                      )}
                    >
                      <span className="min-w-0 truncate font-semibold">
                        {name}
                      </span>
                      <span className="flex shrink-0 items-center gap-3 text-[11px] uppercase tracking-wider text-muted">
                        <span>{p.primary_position || "?"}</span>
                        <span>{p.team_id || "FA"}</span>
                        <span className="font-mono text-[10px]">
                          {p.player_id}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={accept} disabled={!selectedId}>
            Select
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
