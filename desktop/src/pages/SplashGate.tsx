/**
 * Gates the app behind a successful `/healthz` response so we never render
 * screens while the Python sidecar is still booting. Also surfaces a
 * persistent, unobtrusive status ribbon once healthy.
 */

import { useEffect, useState } from "react";
import { Loader2, AlertTriangle } from "lucide-react";

import { api, type HealthPayload } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { Card } from "@/components/ui";
import { Brand } from "@/components/layout/Brand";

interface Props {
  children: React.ReactNode;
}

type Phase =
  | { kind: "checking" }
  | { kind: "ready"; health: HealthPayload }
  | { kind: "error"; message: string };

export function SplashGate({ children }: Props) {
  const [phase, setPhase] = useState<Phase>({ kind: "checking" });
  const setActiveLeague = useAuthStore((s) => s.setActiveLeague);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((health) => {
        if (cancelled) return;
        // Seed the store with whatever league the sidecar thinks is active
        // so returning users skip the picker on launch.
        setActiveLeague(health.active_league ?? null);
        setPhase({ kind: "ready", health });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          setPhase({ kind: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [setActiveLeague]);

  if (phase.kind === "ready") {
    return (
      <>
        <HealthRibbon health={phase.health} />
        {children}
      </>
    );
  }

  return (
    <div className="flex h-full w-full items-center justify-center bg-canvas">
      <Card className="w-[420px] p-8">
        <div className="relative flex flex-col items-center gap-5 text-center">
          <Brand />
          {phase.kind === "checking" ? (
            <>
              <Loader2 className="h-8 w-8 animate-spin text-amber" />
              <div className="space-y-1">
                <h1 className="font-display text-xl">Starting NexGen-BBPro…</h1>
                <p className="text-sm text-muted">Waking the simulation sidecar.</p>
              </div>
            </>
          ) : (
            <>
              <AlertTriangle className="h-8 w-8 text-danger" />
              <div className="space-y-1">
                <h1 className="font-display text-xl">Sidecar unavailable</h1>
                <p className="text-sm text-muted">{phase.message}</p>
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}

function HealthRibbon({ health }: { health: HealthPayload }) {
  return (
    <div className="fixed bottom-2 right-3 z-50 rounded-md border border-border bg-surfaceAlt/80 px-2 py-1 text-[10px] uppercase tracking-wider text-muted backdrop-blur">
      v{health.version} · {health.active_league ?? "no league"}
    </div>
  );
}
