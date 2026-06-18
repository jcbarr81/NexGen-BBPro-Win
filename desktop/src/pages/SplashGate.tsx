/**
 * Gates the app behind a successful `/healthz` response so we never render
 * screens while the Python sidecar is still booting. Also surfaces a
 * persistent, unobtrusive status ribbon once healthy.
 */

import { useEffect, useState } from "react";
import { Loader2, AlertTriangle, RefreshCw } from "lucide-react";

import { api, type HealthPayload } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { isCloud } from "@/lib/cloud-auth";
import { Button, Card } from "@/components/ui";
import { Brand } from "@/components/layout/Brand";

interface Props {
  children: React.ReactNode;
}

type Phase =
  | { kind: "checking"; slow: boolean }
  | { kind: "ready"; health: HealthPayload }
  | { kind: "error"; message: string };

// Per-attempt timeout so a hung request can't freeze the splash, plus a few
// auto-retries because a cold Cloud Run instance can take a while to wake.
const PROBE_TIMEOUT_MS = 12_000;
const RETRY_DELAY_MS = 2_000;
const MAX_ATTEMPTS = 5;

export function SplashGate({ children }: Props) {
  const [phase, setPhase] = useState<Phase>({ kind: "checking", slow: false });
  const setActiveLeague = useAuthStore((s) => s.setActiveLeague);
  const setAppVersion = useAuthStore((s) => s.setAppVersion);
  // Bumping this re-runs the effect for a manual retry from the error card.
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    async function probe(attempt: number): Promise<void> {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
      try {
        const health = await api.health(controller.signal);
        if (cancelled) return;
        // Seed the store with whatever league the sidecar thinks is active
        // so returning users skip the picker on launch. NOT in cloud mode —
        // there the global pointer is meaningless (each user picks their own
        // league), and seeding it could grant access to a league they're not in.
        if (!isCloud()) setActiveLeague(health.active_league ?? null);
        // Expose the version for the sidebar footer tag.
        setAppVersion(health.version ?? null);
        setPhase({ kind: "ready", health });
      } catch (err: unknown) {
        if (cancelled) return;
        if (attempt < MAX_ATTEMPTS) {
          // Keep the spinner up; after the first miss, tell the user it's
          // taking longer than usual (a waking instance) so it doesn't look
          // frozen.
          setPhase({ kind: "checking", slow: attempt >= 1 });
          retryTimer = setTimeout(() => void probe(attempt + 1), RETRY_DELAY_MS);
        } else {
          const message =
            err instanceof DOMException && err.name === "AbortError"
              ? "The simulation service didn't respond in time. It may be waking up — retry in a moment."
              : err instanceof Error
                ? err.message
                : String(err);
          setPhase({ kind: "error", message });
        }
      } finally {
        clearTimeout(timeout);
      }
    }

    setPhase({ kind: "checking", slow: false });
    void probe(1);
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [setActiveLeague, setAppVersion, retryNonce]);

  if (phase.kind === "ready") {
    // The version/league tag now lives in the sidebar footer (see Sidebar.tsx)
    // so it can't float over page buttons or nav links.
    return <>{children}</>;
  }

  return (
    <div
      className="flex h-full w-full items-center justify-center bg-canvas"
      style={{
        backgroundImage:
          "radial-gradient(circle at 50% 110%, hsl(var(--ballpark) / 0.25), transparent 65%)",
      }}
    >
      <Card className="seam-accent relative w-[420px] overflow-hidden p-8">
        <div className="relative flex flex-col items-center gap-5 text-center">
          <Brand />
          {phase.kind === "checking" ? (
            <>
              <Loader2 className="h-8 w-8 animate-spin text-amber" />
              <div className="space-y-1">
                <h1 className="font-display text-xl">Starting NexGen-BBPro…</h1>
                <p className="text-sm text-muted">
                  {phase.slow
                    ? "Still waking the simulation service — this can take a few seconds."
                    : "Waking the simulation sidecar."}
                </p>
              </div>
            </>
          ) : (
            <>
              <AlertTriangle className="h-8 w-8 text-danger" />
              <div className="space-y-1">
                <h1 className="font-display text-xl">Sidecar unavailable</h1>
                <p className="text-sm text-muted">{phase.message}</p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setRetryNonce((n) => n + 1)}
              >
                <RefreshCw className="mr-1 h-4 w-4" /> Retry
              </Button>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}
