/**
 * Five-star display with half-star support, ported from PyQt's
 * ``ui/star_rating.py``. The server-side view-model already computes a
 * 1-5 "star" value from the 35-99 display rating; we just render it.
 */

import { Star, StarHalf } from "lucide-react";

import { cn } from "@/lib/cn";

interface StarRatingProps {
  /** Star value 1..5 (supports half-steps, e.g. 4.5). */
  value: number;
  /** Tailwind size class applied to each star (default ``h-4 w-4``). */
  size?: string;
  className?: string;
}

const STAR_COUNT = 5;

export function StarRating({
  value,
  size = "h-4 w-4",
  className,
}: StarRatingProps) {
  const clamped = Math.max(0, Math.min(STAR_COUNT, value));
  const filled = Math.floor(clamped);
  const hasHalf = clamped - filled >= 0.25 && clamped - filled < 0.75;
  const isEffectivelyFull = clamped - filled >= 0.75;
  return (
    <div
      className={cn("inline-flex items-center gap-0.5 text-amber", className)}
      aria-label={`${clamped.toFixed(1)} out of 5 stars`}
      title={`${clamped.toFixed(1)} / 5`}
    >
      {Array.from({ length: STAR_COUNT }).map((_, idx) => {
        const fullCount = isEffectivelyFull ? filled + 1 : filled;
        if (idx < fullCount) {
          return <Star key={idx} className={cn(size, "fill-amber")} />;
        }
        if (idx === fullCount && hasHalf) {
          return <StarHalf key={idx} className={cn(size, "fill-amber")} />;
        }
        return <Star key={idx} className={cn(size, "opacity-25")} />;
      })}
    </div>
  );
}
