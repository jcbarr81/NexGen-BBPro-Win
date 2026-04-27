/**
 * Modal overlay shown while a Sim Day / Week / Month / To-X mutation
 * is running. Mounted from SeasonPage and any other place that fires a
 * sim — covers the full viewport so the user knows things are moving
 * even if they navigate away.
 *
 * No real-time progress yet (the sidecar returns one big response when
 * the batch finishes), so we show the action label, an elapsed timer,
 * and a rotating "stage" line that suggests what the engine is doing.
 * The timer + stage rotation give the page a heartbeat — without them,
 * a 30-second sim looks frozen.
 */

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui";

interface Props {
  /** True while any sim mutation is in-flight. */
  open: boolean;
  /** Short verb-phrase for the heading (e.g. "Simulating a week…"). */
  label: string | null;
}

const STAGES: string[] = [
  "Loading rosters and lineups…",
  "Running games for the day…",
  "Posting box scores and updating standings…",
  "Settling injuries and DL recoveries…",
  "Running CPU trade proposals…",
  "Running owner finance cadence…",
  "Saving snapshots…",
];

function formatElapsed(ms: number): string {
  const total = Math.floor(ms / 1000);
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function SimProgressOverlay({ open, label }: Props) {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [stageIdx, setStageIdx] = useState(0);

  // Reset and start the timer whenever the overlay opens.
  useEffect(() => {
    if (!open) {
      setStartedAt(null);
      setElapsedMs(0);
      setStageIdx(0);
      return;
    }
    const start = Date.now();
    setStartedAt(start);
    setElapsedMs(0);
    setStageIdx(0);
    const tickEvery = 250;
    const stageEvery = 1800;
    const tick = window.setInterval(() => {
      const now = Date.now();
      setElapsedMs(now - start);
      setStageIdx((idx) =>
        // Advance stages every ~1.8s, but cap at the last entry so we
        // don't loop back to "Loading rosters" mid-run.
        Math.min(STAGES.length - 1, Math.floor((now - start) / stageEvery)),
      );
    }, tickEvery);
    return () => window.clearInterval(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <Dialog open={open}>
      <DialogContent
        // ``[&_[aria-label='Close']]:hidden`` hides the built-in Radix
        // close X — we never want the user to be able to dismiss this
        // modal while the sim is in flight (would leave stale UI on a
        // partial result). The other handlers below cover Esc and click
        // outside.
        className="max-w-sm border-amber/40 bg-surface [&_[aria-label='Close']]:hidden"
        onPointerDownOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <div className="flex items-center gap-3">
          <Loader2 className="h-6 w-6 shrink-0 animate-spin text-amber" />
          <div className="flex-1">
            <DialogTitle className="text-base">
              {label ?? "Working…"}
            </DialogTitle>
            <DialogDescription className="text-xs text-muted">
              {STAGES[stageIdx]}
            </DialogDescription>
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between text-xs">
          <span className="text-muted">Elapsed</span>
          <span className="tabular-nums text-amber-text">
            {startedAt !== null ? formatElapsed(elapsedMs) : "0s"}
          </span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surfaceAlt">
          {/* Indeterminate progress — a sliding amber stripe that signals
              "still working" without lying about a percentage. */}
          <div className="h-full w-1/3 animate-[slide_1.4s_linear_infinite] rounded-full bg-amber/70" />
        </div>
        <style>{`
          @keyframes slide {
            from { transform: translateX(-50%); }
            to   { transform: translateX(300%); }
          }
        `}</style>
      </DialogContent>
    </Dialog>
  );
}
