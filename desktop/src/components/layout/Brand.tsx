import { cn } from "@/lib/cn";

/**
 * Stitched-baseball brand mark. An off-white sphere with the two red
 * figure-8 seams and the amber "N" monogram stamped inside. Rendered
 * inline so we don't pay for another image fetch and so the seam color
 * tracks the design token.
 */
function BaseballMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 40 40"
      className={className}
      aria-hidden
    >
      <defs>
        <radialGradient id="bb-surface" cx="35%" cy="30%" r="75%">
          <stop offset="0%" stopColor="hsl(var(--chalk))" />
          <stop offset="85%" stopColor="hsl(var(--parchment))" />
          <stop offset="100%" stopColor="hsl(var(--walnut))" />
        </radialGradient>
      </defs>
      <circle
        cx="20"
        cy="20"
        r="18"
        fill="url(#bb-surface)"
        stroke="hsl(var(--walnut))"
        strokeWidth="0.8"
      />
      {/* Two figure-8 seams. strokeDasharray fakes the stitched look. */}
      <path
        d="M 5 14 Q 20 22 35 14"
        fill="none"
        stroke="hsl(var(--seam))"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeDasharray="0.5 2.5"
      />
      <path
        d="M 5 26 Q 20 18 35 26"
        fill="none"
        stroke="hsl(var(--seam))"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeDasharray="0.5 2.5"
      />
      <text
        x="20"
        y="26"
        textAnchor="middle"
        fontFamily="Space Grotesk, Inter, sans-serif"
        fontWeight="800"
        fontSize="15"
        fill="hsl(var(--amber))"
        stroke="hsl(var(--mahogany))"
        strokeWidth="0.4"
      >
        N
      </text>
    </svg>
  );
}

export function Brand({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <BaseballMark className="h-9 w-9 drop-shadow-[0_1px_2px_rgba(0,0,0,0.5)]" />
      <div className="leading-tight">
        <div className="font-display text-sm font-bold tracking-[0.18em] text-cream">
          NEXGEN
        </div>
        <div className="text-[10px] uppercase tracking-[0.3em] text-amber-text">
          BBPro
        </div>
      </div>
    </div>
  );
}
