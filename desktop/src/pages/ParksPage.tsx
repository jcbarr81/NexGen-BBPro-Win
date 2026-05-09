/**
 * Standalone ballpark browser — the pre-roster-edit entry point the
 * audit flagged as missing. Same catalog + preview the Team Settings
 * dialog uses, but as a first-class page so you can browse without
 * committing to assigning a stadium.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Building2, Loader2, Search } from "lucide-react";

import { api } from "@/lib/api";
import { getBridge } from "@/lib/bridge";
import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
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

export function ParksPage() {
  return (
    <AppShell
      title="Ballparks"
      subtitle="Browse the park catalog — pick one from Team Settings to assign it"
    >
      <ParksBody />
    </AppShell>
  );
}

function ParksBody() {
  const parksQuery = useQuery({
    queryKey: ["parks"],
    queryFn: () => api.listParks(),
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
    if (!selected && parks.length > 0) setSelected(parks[0]);
  }, [parks, selected]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Building2 className="h-4 w-4 text-amber" /> Catalog
        </CardTitle>
        <CardDescription>
          {parksQuery.data
            ? `${parksQuery.data.count} parks in the catalog.`
            : "Loading…"}{" "}
          Pick a stadium from{" "}
          <a href="#/settings" className="text-amber underline-offset-2 hover:underline">
            Team Settings
          </a>{" "}
          to assign it to your team.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-3 relative max-w-md">
          <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input
            className="pl-8"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by name…"
          />
        </div>
        <div className="grid h-[600px] grid-cols-5 gap-3">
          <div className="col-span-2 overflow-y-auto rounded-md border border-border bg-surface">
            {parksQuery.isLoading && (
              <div className="flex items-center gap-2 p-4 text-sm text-muted">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading…
              </div>
            )}
            {filtered.map((p) => {
              const isSel = selected?.name === p.name && selected?.year === p.year;
              return (
                <button
                  key={`${p.park_id}-${p.year}-${p.name}`}
                  type="button"
                  onClick={() => setSelected(p)}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 border-b border-border/50 px-3 py-2 text-left text-sm transition",
                    isSel ? "bg-amber/10 text-ink" : "hover:bg-surfaceAlt",
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
      </CardContent>
    </Card>
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
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold">{park.name}</div>
            <div className="text-xs text-muted">
              {park.year > 0 ? park.year : "No historical year"}
            </div>
          </div>
          {park.park_id && <Badge tone="amber">{park.park_id}</Badge>}
        </div>
        {park.lf && park.cf && park.rf && (
          <div className="mt-1 text-[11px] text-muted">
            LF {park.lf} / CF {park.cf} / RF {park.rf}
            {park.foul_territory ? ` · ${park.foul_territory} foul` : ""}
          </div>
        )}
      </div>
      {/* min-h-0 + overflow-hidden lets the flex child actually respect
          max-h-full on the image — without it the parent's intrinsic
          content size wins and the diagram overflows the card. */}
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden p-3">
        {status === "loading" && <Loader2 className="h-5 w-5 animate-spin text-amber" />}
        {status === "ready" && imgUrl && (
          <img
            src={imgUrl}
            alt={park.name}
            className="max-h-full max-w-full rounded-md object-contain"
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
