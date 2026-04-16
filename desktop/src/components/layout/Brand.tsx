import { cn } from "@/lib/cn";

/**
 * Text-only brand mark. Phase 3 keeps this lightweight; Phase 7 adds the
 * actual logo (`logo/NexGen.png`) copied into the Electron resources.
 */
export function Brand({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-amber text-espresso font-display font-bold">
        N
      </span>
      <div className="leading-tight">
        <div className="font-display text-sm font-bold tracking-wider text-cream">
          NEXGEN
        </div>
        <div className="text-[10px] uppercase tracking-[0.24em] text-amber-text">
          BBPro
        </div>
      </div>
    </div>
  );
}
