/**
 * Live consequences of a contract offer for the team's books: payroll before →
 * after, luxury-tax estimate (when payroll rules are on), cash left after the
 * bonus, and the Opening-Day solvency gate. Numbers come from the same policy
 * math settlement uses. Shared by the Free-Agency offer dialog and the
 * player-profile extend/re-sign dialog (#10).
 *
 * When payroll enforcement is off but finance is on (impact.info), this renders
 * an informational payroll view (no threshold/tax lines).
 */

import type { PayrollOutlook } from "@/lib/api";
import { formatMoneyCompact } from "@/lib/format";
import { cn } from "@/lib/cn";

export function OfferImpactPanel({ impact }: { impact: PayrollOutlook }) {
  const before = impact.payroll ?? 0;
  const after = impact.projected_payroll ?? before;
  const threshold = impact.threshold ?? 0;
  const overAfter = impact.over_threshold ?? 0;
  const tax = impact.estimated_tax ?? 0;
  const wasOver = threshold > 0 && before > threshold;
  const crosses = !wasOver && overAfter > 0;
  const bonus = impact.signing_bonus ?? 0;
  const cashAfter = impact.cash_after_bonus ?? impact.cash_on_hand ?? 0;
  const solvent = impact.opening_day_solvent ?? true;
  const feeLabel = impact.level === "mlb_like" ? "luxury tax" : "overage fee";
  // Enforcement (threshold/tax/headroom) only exists when payroll rules are on;
  // otherwise this is an informational payroll view.
  const active = !!impact.active;

  return (
    <div className="rounded-md border border-border bg-surfaceAlt/40 px-3 py-2 text-xs">
      <div className="font-semibold uppercase tracking-wider text-muted">
        Your team&apos;s books
      </div>
      <div className="mt-1 space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-muted">Payroll</span>
          <span className="tabular-nums">
            {formatMoneyCompact(before)}{" "}
            <span className="text-muted">→</span>{" "}
            <span
              className={cn(
                "font-semibold",
                overAfter > 0 ? "text-danger" : "text-success",
              )}
            >
              {formatMoneyCompact(after)}
            </span>{" "}
            {active && threshold > 0 && (
              <span className="text-muted">
                (threshold {formatMoneyCompact(threshold)})
              </span>
            )}
          </span>
        </div>
        {active &&
          (overAfter > 0 ? (
            <div className="flex items-center justify-between text-danger">
              <span>
                {crosses
                  ? "Crosses the luxury threshold"
                  : "Already over threshold"}
              </span>
              <span className="tabular-nums font-semibold">
                est. {formatMoneyCompact(tax)} {feeLabel}
              </span>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <span className="text-muted">Headroom after signing</span>
              <span className="tabular-nums font-semibold text-success">
                {formatMoneyCompact(impact.headroom ?? 0)}
              </span>
            </div>
          ))}
        {bonus > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-muted">Cash after bonus</span>
            <span
              className={cn(
                "tabular-nums font-semibold",
                cashAfter < 0 ? "text-danger" : "text-ink",
              )}
            >
              {formatMoneyCompact(cashAfter)}
              {cashAfter < 0 ? " (accrues as debt)" : ""}
            </span>
          </div>
        )}
        {!solvent && (
          <div className="mt-1 rounded border border-danger/40 bg-danger/10 px-2 py-1 text-danger">
            <span className="font-semibold">Opening Day risk:</span> projected
            debt {formatMoneyCompact(impact.projected_debt ?? 0)} would exceed
            the {formatMoneyCompact(impact.debt_cap ?? 0)} cap — the season
            can&apos;t start until resolved.
          </div>
        )}
      </div>
    </div>
  );
}
