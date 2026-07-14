/**
 * Global command palette — Cmd/Ctrl+K from anywhere opens a search
 * overlay that jumps to players, teams, or pages. Light substitute for
 * shipping ``cmdk`` as a dependency; fits the rest of the stack
 * (Radix Dialog + Zustand + existing ``useHotkey``).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Search,
  Trophy,
  UserSearch,
  Users,
} from "lucide-react";

import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/lib/auth-store";
import { useHotkey } from "@/lib/use-hotkey";
import { useLeagueCapabilities } from "@/lib/league-capabilities";
import { ROUTE_INDEX } from "@/lib/route-index";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
} from "@/components/ui";

type Kind = "page" | "player" | "team";

interface CommandItem {
  kind: Kind;
  label: string;
  /** Secondary text rendered after the label (team, position, etc.). */
  sub?: string;
  /** ``haystack`` is the string we actually match against the query. */
  haystack: string;
  to: string;
}

// Routes that are jumpable but not part of ROUTE_INDEX (detail/help pages).
const EXTRA_PAGE_ITEMS: CommandItem[] = [
  { kind: "page", label: "Help", to: "/help", haystack: "help manuals tutorials" },
];

/**
 * Jump-target pages, derived from ROUTE_INDEX so the palette can never
 * drift from the real navigation (the old hand-maintained list did).
 * Applies the same adminOnly/capability filters the hub pages use, so
 * owners don't see commissioner surfaces.
 */
function usePageItems(): CommandItem[] {
  const role = useAuthStore((s) => s.role);
  const capabilities = useLeagueCapabilities();
  return useMemo(() => {
    const items: CommandItem[] = ROUTE_INDEX.filter((r) => {
      if (r.adminOnly && role !== "admin") return false;
      if (r.capability === "finance" && !capabilities.financeEnabled) return false;
      if (r.capability === "multi-owner" && !capabilities.multiOwner) return false;
      return true;
    }).map((r) => ({
      kind: "page" as const,
      label: r.label,
      sub: r.description,
      haystack: `${r.label} ${r.description} ${r.path}`.toLowerCase(),
      to: r.path,
    }));
    return [...items, ...EXTRA_PAGE_ITEMS];
  }, [role, capabilities.financeEnabled, capabilities.multiOwner]);
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const navigate = useNavigate();
  const listRef = useRef<HTMLUListElement>(null);
  const [activeIdx, setActiveIdx] = useState(0);

  // Global hotkey — ``allowInInputs`` so Cmd+K still works from a text
  // field, which is the muscle-memory users expect.
  useHotkey("mod+k", () => setOpen((o) => !o), { allowInInputs: true });

  useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveIdx(0);
    }
  }, [open]);

  const players = useQuery({
    queryKey: ["command-palette-players"],
    queryFn: () => api.browsePlayers({ limit: 2000 }),
    enabled: open,
    staleTime: 60_000,
  });
  const teamsQ = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    enabled: open,
    staleTime: 60_000,
  });

  const pageItems = usePageItems();

  const items = useMemo<CommandItem[]>(() => {
    const all: CommandItem[] = [];
    const q = query.trim().toLowerCase();

    for (const page of pageItems) {
      if (!q || page.haystack.includes(q) || page.label.toLowerCase().includes(q)) {
        all.push(page);
      }
    }

    for (const t of teamsQ.data ?? []) {
      const label = `${t.city} ${t.name}`.trim();
      const hay = `${label} ${t.abbreviation} ${t.team_id}`.toLowerCase();
      if (!q || hay.includes(q)) {
        all.push({
          kind: "team",
          label,
          sub: `${t.abbreviation} · ${t.division}`,
          haystack: hay,
          to: `/team/${encodeURIComponent(t.team_id)}`,
        });
      }
    }

    if (q.length >= 2) {
      for (const p of players.data?.players ?? []) {
        const label = `${p.last_name}, ${p.first_name}`.trim();
        const hay = `${label} ${p.player_id} ${p.primary_position}`.toLowerCase();
        if (hay.includes(q)) {
          all.push({
            kind: "player",
            label: label || p.player_id,
            sub: `${p.primary_position || "?"} · ${p.team_id || "FA"}`,
            haystack: hay,
            to: `/player/${encodeURIComponent(p.player_id)}`,
          });
          if (all.length > 200) break;
        }
      }
    }

    return all.slice(0, 100);
  }, [query, players.data, teamsQ.data, pageItems]);

  useEffect(() => {
    if (activeIdx >= items.length) setActiveIdx(0);
  }, [items.length, activeIdx]);

  function pick(item: CommandItem) {
    navigate(item.to);
    setOpen(false);
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(items.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const picked = items[activeIdx];
      if (picked) pick(picked);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        className="max-w-xl"
        onOpenAutoFocus={(e) => {
          // Let the Input's own autoFocus take precedence over Radix's
          // default "first focusable".
          e.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>
            <span className="inline-flex items-center gap-2">
              <Search className="h-4 w-4" /> Jump to…
            </span>
          </DialogTitle>
          <DialogDescription>
            Pages, teams, or players. Use ↑ ↓ to move, Enter to open.
          </DialogDescription>
        </DialogHeader>

        <Input
          autoFocus
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveIdx(0);
          }}
          onKeyDown={handleKey}
          placeholder="Search…"
        />

        <ul
          ref={listRef}
          className="mt-2 max-h-80 overflow-y-auto rounded-lg border border-border bg-canvas/40"
          role="listbox"
        >
          {items.length === 0 ? (
            <li className="px-4 py-6 text-sm text-muted">No matches.</li>
          ) : (
            items.map((item, idx) => (
              <li key={`${item.kind}:${item.to}`}>
                <button
                  type="button"
                  onClick={() => pick(item)}
                  onMouseEnter={() => setActiveIdx(idx)}
                  className={cn(
                    "flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition",
                    idx === activeIdx
                      ? "bg-amber/10 text-ink"
                      : "hover:bg-surfaceAlt/40",
                  )}
                  role="option"
                  aria-selected={idx === activeIdx}
                >
                  <KindIcon kind={item.kind} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold">{item.label}</div>
                    {item.sub && (
                      <div className="truncate text-[11px] uppercase tracking-wider text-muted">
                        {item.sub}
                      </div>
                    )}
                  </div>
                  <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted">
                    {item.kind}
                  </span>
                  {idx === activeIdx && (
                    <ArrowRight className="h-3 w-3 shrink-0 text-amber" />
                  )}
                </button>
              </li>
            ))
          )}
        </ul>

        <div className="mt-2 text-[10px] uppercase tracking-wider text-muted">
          Press <kbd className="rounded border border-border bg-surfaceAlt px-1">Esc</kbd> to close.
        </div>
      </DialogContent>
    </Dialog>
  );
}

function KindIcon({ kind }: { kind: Kind }) {
  if (kind === "player") return <UserSearch className="h-4 w-4 text-amber" />;
  if (kind === "team") return <Users className="h-4 w-4 text-amber" />;
  return <Trophy className="h-4 w-4 text-amber" />;
}
