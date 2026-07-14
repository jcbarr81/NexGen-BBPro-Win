/**
 * Shared number/money formatting for finance surfaces.
 *
 * Every finance page previously rolled its own formatter (full-precision
 * `$220,000,000` strings, bare ratios, `5.032` service time). These helpers
 * standardize on compact, scannable output so payroll/threshold/cash values
 * read the same everywhere.
 */

/** Compact money: $1.4B / $220M / $12.5M / $850K / $500. Negative → -$3M. */
export function formatMoneyCompact(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "$0";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${sign}$${trimZero((abs / 1_000_000_000).toFixed(2))}B`;
  if (abs >= 1_000_000) return `${sign}$${trimZero((abs / 1_000_000).toFixed(1))}M`;
  if (abs >= 1_000) return `${sign}$${trimZero((abs / 1_000).toFixed(0))}K`;
  return `${sign}$${abs.toLocaleString()}`;
}

/** Full-precision money for ledgers/tables: $12,500,000. Negative → -$3,000,000. */
export function formatMoneyFull(value: number | null | undefined): string {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n)) return "$0";
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(Math.round(n)).toLocaleString()}`;
}

/** Annual salary with cadence: "$8.5M/yr". */
export function formatSalary(annual: number | null | undefined): string {
  return `${formatMoneyCompact(annual)}/yr`;
}

/**
 * Contract shorthand: "$8.5M/yr × 3 yrs ($25.5M total)".
 * Single-year deals omit the redundant total.
 */
export function formatContract(
  annual: number | null | undefined,
  years: number | null | undefined,
): string {
  const yrs = Math.max(1, Number(years ?? 1));
  if (yrs === 1) return formatSalary(annual);
  const total = Number(annual ?? 0) * yrs;
  return `${formatSalary(annual)} × ${yrs} yrs (${formatMoneyCompact(total)} total)`;
}

/** Service time from "years.days" numeric encoding → "5 yrs, 32 days". */
export function formatServiceTime(
  years: number | null | undefined,
  days?: number | null,
): string {
  const y = Math.max(0, Math.floor(Number(years ?? 0)));
  const d = Math.max(0, Math.floor(Number(days ?? 0)));
  if (y <= 0 && d <= 0) return "0 days";
  if (d <= 0) return `${y} yr${y === 1 ? "" : "s"}`;
  if (y <= 0) return `${d} day${d === 1 ? "" : "s"}`;
  return `${y} yr${y === 1 ? "" : "s"}, ${d} day${d === 1 ? "" : "s"}`;
}

function trimZero(s: string): string {
  return s.replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
}
