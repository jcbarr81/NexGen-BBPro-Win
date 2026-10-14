/**
 * One colour scale for every rating and every overall the server shows.
 *
 * The thresholds are the same whatever rating scale the league is on, so the
 * client never needs to know it. On rating scale 2 (the full 1-99 scale)
 * the numbers are stored ratings: 50 is an average regular, 70 a clear
 * strength (about one player in ten), 85 and up the best few in the league,
 * and the overall is stretched onto the same reading. On scale 1 the server
 * shows the percentile-blended number these bands were first drawn for.
 */
export const RATING_TONE_BANDS = {
  elite: 85,
  good: 70,
  average: 50,
} as const;

export function ratingTone(value: number): string {
  if (value >= RATING_TONE_BANDS.elite) return "text-success";
  if (value >= RATING_TONE_BANDS.good) return "text-amber-text";
  if (value >= RATING_TONE_BANDS.average) return "text-ink";
  return "text-subtle";
}
