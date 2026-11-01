/**
 * How a free-agent bid stands and when the player decides (8.8.0), in the
 * words every page uses. The server works both out
 * (services/fa_negotiations.team_standing / decision_timing) by the rule the
 * signing itself uses: the player signs the biggest total among the offers
 * he would accept, so a bigger total he would turn down never "leads".
 */

import type { FaDecision, FaStanding } from "@/lib/api";

export type StandingTone = "success" | "danger" | "warning" | "neutral";

export const STANDING: Record<FaStanding, { label: string; tone: StandingTone; hint: string }> = {
  leading: {
    label: "Leading",
    tone: "success",
    hint: "He would sign your offer if he decided now.",
  },
  outbid: {
    label: "Outbid",
    tone: "danger",
    hint: "Another club's offer, one he would take, has a bigger total. Raise yours to pass it.",
  },
  below_ask: {
    label: "Below his ask",
    tone: "warning",
    hint: "Below his asking price: he may not take it. An offer at his ask is sure to be accepted.",
  },
  too_long: {
    label: "Too long",
    tone: "danger",
    hint: "Longer than he will sign for at his age. Shorten it, or he will not sign it.",
  },
  wont_accept: {
    label: "He won't sign",
    tone: "danger",
    hint: "Below what he takes: raise it, or he will not sign it.",
  },
};

/** "Decides at the end of day 9 of 14", or the like. */
export function decisionText(decision: FaDecision | null | undefined, deadline?: string): string {
  if (!decision) return deadline ? `Decides by ${deadline}` : "";
  switch (decision.kind) {
    case "window_day":
      return `Decides at the end of day ${decision.day} of ${decision.total}`;
    case "today":
      return decision.day >= decision.total
        ? "Decides when today ends (the last day)"
        : "Could sign when today ends";
    case "next_sim_day":
      return "Decides on the next sim day";
    case "date":
      return decision.date ? `Decides by ${decision.date}` : "";
  }
}
