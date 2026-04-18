/**
 * Full ballpark browser — port of ui/park_selector_dialog.py.
 *
 * Shows the whole ParkConfig catalog filtered by name. Right pane renders
 * the on-demand park diagram served by /parks/preview (fetched as blob so
 * we can include the bearer token).
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, Loader2, Search } from "lucide-react";

import { api } from "@/lib/api";
import { getBridge } from "@/lib/bridge";
import { useAuthStore } from "@/lib/auth-store";
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

interface Park {
  park_id: string;
  name: string;
  year: number;
  lf: number | null;
  cf: number | null;
  rf: number | null;
  foul_territory: string | null;
  has_preview: boolean;
}

interface ParkBrowserProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentStadium: string;
  onSelect: (park: Park) => void;
}

export function ParkBrowser({
  open,
  onOpenChange,
  currentStadium,
  onSelect,
}: ParkBrowserProps) {
  const parksQuery = useQuery({
    queryKey: ["parks"],
    queryFn: () => api.listParks(),
    enabled: open,
  });

  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Park | null>(null);

  const parks: Park[] = parksQuery.data?.parks ?? [];
  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return parks;
    return parks.filter((p) => p.name.toLowerCase().includes(q));
  }, [parks, filter]);

  useEffect(() => {
    if (!open) return;
    if (parks.length === 0) {
      setSelected(null);
      return;
    }
    const match =
      parks.find((p) => p.name === currentStadium) ?? filtered[0] ?? parks[0];
    setSelected(match ?? null);
  }, [open, parks, currentStadium]);

  function commit() {
    if (selected) onSelect(selected);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Select Stadium</DialogTitle>
          <DialogDescription>
            Pick a park from the catalog. Preview renders the field geometry.
          </DialogDescription>
        </DialogHeader>

        <div className="mb-3">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <Input
              className="pl-8"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Type to filter by name…"
            />
          </div>
        </div>

        <div className="grid h-[420px] grid-cols-5 gap-3">
          <div className="col-span-2 overflow-y-auto rounded-md border border-border bg-surface">
            {parksQuery.isLoading && (
              <div className="flex items-center gap-2 p-4 text-sm text-muted">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading catalog…
              </div>
            )}
            {parksQuery.isError && (
              <div className="p-4 text-sm text-danger">
                {(parksQuery.error as Error).message}
              </div>
            )}
            {filtered.map((p) => {
              const isSelected = selected?.name === p.name && selected?.year === p.year;
              return (
                <button
                  key={`${p.park_id}-${p.year}-${p.name}`}
                  type="button"
                  onClick={() => setSelected(p)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 border-b border-border/50 px-3 py-2 text-left text-sm transition",
                    isSelected
                      ? "bg-amber/10 text-ink"
                      : "hover:bg-surfaceAlt",
                  )}
                >
                  <div>
                    <div className="font-semibold">{p.name}</div>
                    {p.year > 0 && (
                      <div className="text-[10px] text-muted">{p.year}</div>
                    )}
                  </div>
                  <Building2 className="h-4 w-4 text-amber" />
                </button>
              );
            })}
            {!parksQuery.isLoading && filtered.length === 0 && (
              <div className="p-4 text-sm text-muted">No parks match.</div>
            )}
          </div>

          <div className="col-span-3 flex flex-col rounded-md border border-border bg-surface">
            {selected ? (
              <PreviewPane park={selected} />
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-muted">
                Select a park to preview.
              </div>
            )}
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={commit} disabled={!selected}>
            Use Stadium
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PreviewPane({ park }: { park: Park }) {
  const [imgUrl, setImgUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "none" | "error">(
    "loading",
  );
  const token = useAuthStore((s) => s.token);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    setImgUrl(null);

    if (!park.has_preview) {
      setStatus("none");
      return;
    }

    setStatus("loading");
    const { apiBaseUrl, launchToken } = getBridge();
    const authToken = token ?? launchToken;
    const url = `${apiBaseUrl}/parks/preview?park_id=${encodeURIComponent(
      park.park_id,
    )}&year=${park.year}`;

    fetch(url, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setImgUrl(objectUrl);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [park.park_id, park.year, park.has_preview, token]);

  return (
    <div className="flex flex-1 flex-col">
      <div className="border-b border-border px-3 py-2">
        <div className="text-sm font-semibold">{park.name}</div>
        <div className="text-xs text-muted">
          {park.year > 0 ? park.year : "No historical year"}
          {park.lf && park.cf && park.rf ? (
            <>
              {" · "}
              {`LF ${park.lf} / CF ${park.cf} / RF ${park.rf}`}
            </>
          ) : null}
          {park.foul_territory ? ` · ${park.foul_territory} foul` : ""}
        </div>
      </div>
      <div className="flex flex-1 items-center justify-center p-3">
        {status === "loading" && (
          <Loader2 className="h-5 w-5 animate-spin text-amber" />
        )}
        {status === "ready" && imgUrl && (
          <img
            src={imgUrl}
            alt={park.name}
            className="max-h-full max-w-full rounded-md"
          />
        )}
        {status === "none" && (
          <div className="text-xs text-muted">No preview available.</div>
        )}
        {status === "error" && (
          <div className="text-xs text-danger">Failed to render diagram.</div>
        )}
      </div>
    </div>
  );
}
