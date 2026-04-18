/**
 * Helpers for deriving WCAG-safe accent styles from a team's primary and
 * secondary hex colors. Used by team-specific pages so the hero card, stat
 * cards, and standings row pick up team color without torching readability.
 *
 * The luminance check is the standard sRGB relative-luminance formula; we
 * pair it with a cream/espresso fallback so high-luminance team colors
 * (yellows, near-white secondaries) still get legible text on top.
 */

import { useMemo } from "react";

import type { Team } from "@/lib/api";

export interface TeamAccent {
  /** Raw hex strings (lowercased, with leading #). */
  primary: string;
  secondary: string;
  /** Text color that meets contrast on a solid primary-color background. */
  primaryInk: string;
  /** 10–18% alpha tint, safe for subtle panel backgrounds. */
  softTint: string;
  /** Slightly stronger tint for hover / selected states. */
  mediumTint: string;
  /** Border-weight accent, ~55% alpha. */
  borderAccent: string;
  /** Full-saturation stripe accent (1-px). */
  stripe: string;
  /** Diagonal wash layered over canvas — use as a hero card background. */
  heroGradient: string;
}

const NEUTRAL_PRIMARY = "#462d0d"; // mahogany
const NEUTRAL_SECONDARY = "#fffdf0"; // cream
const CREAM_FALLBACK = "#fffdf0";
const ESPRESSO_FALLBACK = "#1e1207";

function clampHex(input: string | undefined, fallback: string): string {
  const raw = (input ?? "").trim().toLowerCase();
  if (!/^#([0-9a-f]{6})$/.test(raw)) return fallback;
  return raw;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace("#", "");
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  };
}

function rgbToRgba({ r, g, b }: { r: number; g: number; b: number }, alpha: number): string {
  const a = Math.max(0, Math.min(1, alpha));
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/** Relative luminance per WCAG 2.1. 0 = pure black, 1 = pure white. */
function relativeLuminance(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  const channel = (value: number) => {
    const v = value / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/**
 * Pick a readable text color for the given solid background. Uses a
 * luminance threshold that matches WCAG's "use dark text on light bg"
 * rule of thumb.
 */
function readableOn(hex: string): string {
  return relativeLuminance(hex) > 0.5 ? ESPRESSO_FALLBACK : CREAM_FALLBACK;
}

export function deriveTeamAccent(team: Team | null | undefined): TeamAccent {
  const primary = clampHex(team?.primary_color, NEUTRAL_PRIMARY);
  const secondary = clampHex(team?.secondary_color, NEUTRAL_SECONDARY);

  const primaryRgb = hexToRgb(primary);

  return {
    primary,
    secondary,
    primaryInk: readableOn(primary),
    softTint: rgbToRgba(primaryRgb, 0.12),
    mediumTint: rgbToRgba(primaryRgb, 0.22),
    borderAccent: rgbToRgba(primaryRgb, 0.55),
    stripe: primary,
    heroGradient: [
      `linear-gradient(135deg, ${rgbToRgba(primaryRgb, 0.18)}, transparent 60%)`,
      "radial-gradient(circle at 50% 140%, hsl(var(--clay) / 0.3), transparent 55%)",
      "radial-gradient(circle at 50% 180%, hsl(var(--ballpark-deep) / 0.55), transparent 60%)",
    ].join(","),
  };
}

export function useTeamAccent(team: Team | null | undefined): TeamAccent {
  return useMemo(() => deriveTeamAccent(team), [team?.primary_color, team?.secondary_color]);
}

export const NEUTRAL_ACCENT: TeamAccent = deriveTeamAccent(null);

/**
 * Convenience hook for the many team-specific pages that need only the
 * primary-color stripe on AppShell. Looks up the current team in the
 * cached teams list by the given id.
 */
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export function useActiveTeamColor(teamId: string | null | undefined): string | undefined {
  const teams = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams(),
    enabled: !!teamId,
  });
  const match = teamId
    ? teams.data?.find((t) => t.team_id === teamId)
    : undefined;
  return match?.primary_color;
}
