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
}

const toneClasses: Record<NonNullable<StatCardProps["tone"]>, string> = {
  neutral: "text-ink",
  amber: "text-amber-text",
  success: "text-success",
  danger: "text-danger",
};

/**
 * Headline metric tile -- ports the "MetricValue" styling from
 * ui/theme_enhanced.py (amber-accented numbers, subdued label).
 */
export function StatCard({
  label,
  value,
  sub,
  tone = "neutral",
  Icon,
  className,
}: StatCardProps) {
  return (
    <Card className={cn("p-5", className)}>
      <div className="relative flex items-start justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            {label}
          </div>
          <div
            className={cn(
              "mt-1 font-display text-3xl font-bold leading-none",
              toneClasses[tone],
            )}
          >
            {value}
          </div>
          {sub && <div className="mt-2 text-xs text-muted">{sub}</div>}
        </div>
        {Icon && (
          <div className="rounded-lg border border-border bg-surfaceAlt p-2 text-amber">
            <Icon className="h-5 w-5" aria-hidden />
          </div>
        )}
      </div>
    </Card>
  );
}
