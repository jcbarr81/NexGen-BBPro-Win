/**
 * Deadline formatting shared by the Season page (progression + FA-window
 * schedules) and the dashboard Spotlight.
 */

/** "in 2d 4h" / "in 35m" / "3h 10m ago" for an ISO instant ("" when none). */
export function formatCountdown(iso: string | null | undefined): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "";
  const abs = Math.abs(ms);
  const mins = Math.round(abs / 60000);
  const h = Math.floor(mins / 60);
  const d = Math.floor(h / 24);
  let rel: string;
  if (d >= 1) rel = `${d}d ${h % 24}h`;
  else if (h >= 1) rel = `${h}h ${mins % 60}m`;
  else rel = `${mins}m`;
  return ms >= 0 ? `in ${rel}` : `${rel} ago`;
}

/** Format a stored deadline (ISO) as local time; a legacy free-form label is
 *  shown as-is. */
export function formatDeadlineLocal(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
}
