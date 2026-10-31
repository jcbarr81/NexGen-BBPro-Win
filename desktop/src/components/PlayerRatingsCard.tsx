/**
 * A player's ratings at a glance: the compact line the draft board (8.7.2)
 * and the depth chart (8.7.3) show on every row, and the card that opens
 * when an owner clicks a name. A draft prospect has no player page until he
 * is drafted, so the card is built from the row the page already has (a
 * ``DraftProspect`` or a ``RosterPlayer``), not from the profile endpoint.
 */

import { Link } from "react-router-dom";

import { type RosterPlayer } from "@/lib/api";
import { cn } from "@/lib/cn";
import { ratingTone } from "@/lib/rating-tone";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";

/** What the card needs: a ``DraftProspect`` fits as it is, a
 *  ``RosterPlayer`` through ``rosterCardPlayer``. */
export interface CardPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  primary_position: string;
  other_positions?: string;
  is_pitcher: boolean;
  bats: string;
  throws?: string;
  age?: number | null;
  overall?: number | null;
  ratings: Record<string, number | string | null>;
}

export function rosterCardPlayer(p: RosterPlayer): CardPlayer {
  return { ...p, overall: p.overall_display ?? null };
}

type RatingCol = { key: string; label: string; name: string };

const HITTING: RatingCol[] = [
  { key: "ch", label: "CH", name: "Contact" },
  { key: "ph", label: "PH", name: "Power" },
  { key: "sp", label: "SP", name: "Speed" },
  { key: "eye", label: "EYE", name: "Eye" },
  { key: "fa", label: "FA", name: "Fielding" },
  { key: "arm", label: "ARM", name: "Arm" },
];
const PITCHING: RatingCol[] = [
  { key: "endurance", label: "EN", name: "Endurance" },
  { key: "control", label: "CTRL", name: "Control" },
  { key: "movement", label: "MOV", name: "Movement" },
  { key: "arm", label: "AS", name: "Arm strength" },
  { key: "fa", label: "FA", name: "Fielding" },
];
const PITCHES: RatingCol[] = [
  { key: "fb", label: "FB", name: "Fastball" },
  { key: "sl", label: "SL", name: "Slider" },
  { key: "cu", label: "CU", name: "Changeup" },
  { key: "cb", label: "CB", name: "Curveball" },
  { key: "si", label: "SI", name: "Sinker" },
  { key: "scb", label: "SCB", name: "Screwball" },
  { key: "kn", label: "KN", name: "Knuckleball" },
];

function ratingNumber(p: CardPlayer, key: string): number | null {
  const raw = p.ratings[key];
  if (raw == null || raw === "") return null;
  const n = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(n) ? Math.round(n) : null;
}

/** The pitches he throws (a zero rating means he doesn't throw it). */
function pitchesThrown(p: CardPlayer): RatingCol[] {
  return PITCHES.filter((c) => (ratingNumber(p, c.key) ?? 0) > 0);
}

/** The ratings worth a glance: a hitter's six, or a pitcher's endurance,
 *  control, movement and the pitches he throws. */
export function keyRatings(p: CardPlayer): RatingCol[] {
  return p.is_pitcher ? [...PITCHING.slice(0, 3), ...pitchesThrown(p)] : HITTING;
}

export function RatingLine({ player }: { player: CardPlayer }) {
  return (
    <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] tabular-nums">
      {keyRatings(player).map((c) => {
        const v = ratingNumber(player, c.key);
        return (
          <span key={c.key} title={c.name} className="whitespace-nowrap">
            <span className="text-muted">{c.label}</span>{" "}
            <span className={cn("font-semibold", v != null && ratingTone(v))}>{v ?? "—"}</span>
          </span>
        );
      })}
    </div>
  );
}

function RatingGrid({ player, cols }: { player: CardPlayer; cols: RatingCol[] }) {
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
      {cols.map((c) => {
        const v = ratingNumber(player, c.key);
        return (
          <div
            key={c.key}
            className="rounded-md border border-border/60 bg-surfaceAlt/40 px-2 py-1.5"
            title={c.name}
          >
            <div className="text-[10px] uppercase tracking-wider text-muted">{c.name}</div>
            <div className={cn("text-lg font-semibold tabular-nums", v != null && ratingTone(v))}>
              {v ?? "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</div>
      {children}
    </div>
  );
}

export function PlayerRatingsDialog({
  player,
  pageLink,
  onClose,
}: {
  player: CardPlayer | null;
  /** Shown beside a link to his player page; null when he has none yet
   *  (an undrafted prospect). */
  pageLink?: string | null;
  onClose: () => void;
}) {
  const p = player;
  const pitches = p ? pitchesThrown(p) : [];
  const otherPositions = (p?.other_positions ?? "")
    .split(/[,;|\s]+/)
    .map((s) => s.trim())
    .filter((s) => s && s !== p?.primary_position);
  return (
    <Dialog open={p != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-xl">
        {p && (
          <>
            <DialogHeader>
              <DialogTitle>
                {p.first_name} {p.last_name}
              </DialogTitle>
              <DialogDescription>
                {[
                  p.primary_position || (p.is_pitcher ? "P" : null),
                  otherPositions.length > 0 ? `also ${otherPositions.join(", ")}` : null,
                  p.age != null ? `Age ${p.age}` : null,
                  `Bats ${p.bats || "—"} / Throws ${p.throws || "—"}`,
                  `Overall ${p.overall ?? "—"}`,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              {p.is_pitcher ? (
                <>
                  <Section title="Pitching">
                    <RatingGrid player={p} cols={PITCHING} />
                  </Section>
                  <Section title="Pitches">
                    {pitches.length > 0 ? (
                      <RatingGrid player={p} cols={pitches} />
                    ) : (
                      <div className="text-xs text-muted">No pitches rated.</div>
                    )}
                  </Section>
                  <Section title="Hitting">
                    <RatingGrid player={p} cols={HITTING.slice(0, 4)} />
                  </Section>
                </>
              ) : (
                <Section title="Hitting and fielding">
                  <RatingGrid player={p} cols={HITTING} />
                </Section>
              )}
              {pageLink != null && (
                <div className="flex items-center justify-between border-t border-border/60 pt-3 text-sm">
                  <span className="text-muted">{pageLink}</span>
                  <Link
                    to={`/player/${encodeURIComponent(p.player_id)}`}
                    className="font-semibold text-amber-text hover:underline"
                  >
                    Open player page
                  </Link>
                </div>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
