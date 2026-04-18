import type { ComponentType, ReactNode, SVGProps } from "react";

import { Card } from "@/components/ui";
import { cn } from "@/lib/cn";

interface StatCardProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "neutral" | "amber" | "success" | "danger";
  Icon?: ComponentType<SVGProps<SVGSVGElement>>;
  className?: string;
  /**
   * Render the value as a stadium scoreboard readout — tabular monospace
   * numerals with an amber LED glow, framed in a dark inset. Defaults to
   * true because this component is almost always showing a number.
   */
  scoreboard?: boolean;
  /**
   * Optional hex color (usually a team's primary) painted as a 3-px left
   * border so team pages read as visually grouped without losing the
   * shared card chrome.
   */
  accentColor?: string;
}

const toneClasses: Record<NonNullable<StatCardProps["tone"]>, string> = {
  neutral: "text-ink",
  amber: "text-amber-text",
  success: "text-success",
  danger: "text-danger",
};

/**
 * Headline metric tile. The value is rendered in a scoreboard-style inset
 * (tabular mono, amber LED glow, dark panel) which reads as "stadium
 * out-of-town scoreboard" and gives the dashboard a ballpark feel. Set
 * ``scoreboard={false}`` for non-numeric values (team names, streaks).
 */
export function StatCard({
  label,
  value,
  sub,
  tone = "neutral",
  Icon,
  className,
  scoreboard = true,
  accentColor,
}: StatCardProps) {
  return (
    <Card
      className={cn("relative overflow-hidden p-5", className)}
      style={
        accentColor
          ? { boxShadow: `inset 3px 0 0 0 ${accentColor}` }
          : undefined
      }
    >
      <div className="relative flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            {label}
          </div>
          {scoreboard ? (
            <div className="mt-2 inline-flex min-w-[64px] items-center justify-center rounded-md border border-border-strong/40 bg-espresso/70 px-3 py-1 shadow-inset">
              <span className="scoreboard-digits text-2xl font-bold leading-none">
                {value}
              </span>
            </div>
          ) : (
            <div
              className={cn(
                "mt-1 font-display text-3xl font-bold leading-none",
                toneClasses[tone],
              )}
            >
              {value}
            </div>
          )}
          {sub && <div className="mt-2 text-xs text-muted">{sub}</div>}
        </div>
        {Icon && (
          <div className="ml-3 shrink-0 rounded-lg border border-border bg-surfaceAlt p-2 text-amber">
            <Icon className="h-5 w-5" aria-hidden />
          </div>
        )}
      </div>
    </Card>
  );
}
