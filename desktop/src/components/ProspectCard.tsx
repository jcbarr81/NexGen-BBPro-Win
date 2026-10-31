/**
 * A draft prospect's ratings (8.7.2): the compact line the draft board shows
 * on every row, and the card that opens when an owner clicks a prospect's
 * name. A prospect has no player page until he is drafted, so the card is
 * built from the draft pool's own row (``DraftProspect``).
 */

import { Link } from "react-router-dom";

import { type DraftProspect } from "@/lib/api";
import { cn } from "@/lib/cn";
import { ratingTone } from "@/lib/rating-tone";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";

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

function ratingNumber(p: DraftProspect, key: string): number | null {
  const raw = p.ratings[key];
  if (raw == null || raw === "") return null;
  const n = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(n) ? Math.round(n) : null;
}

/** The pitches he throws (a zero rating means he doesn't throw it). */
function pitchesThrown(p: DraftProspect): RatingCol[] {
  return PITCHES.filter((c) => (ratingNumber(p, c.key) ?? 0) > 0);
}

/** The ratings worth a glance on the board: a hitter's six, or a
 *  pitcher's endurance, control, movement and the pitches he throws. */
export function keyRatings(p: DraftProspect): RatingCol[] {
  return p.is_pitcher ? [...PITCHING.slice(0, 3), ...pitchesThrown(p)] : HITTING;
}

export function ProspectRatingLine({ prospect }: { prospect: DraftProspect }) {
  return (
    <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] tabular-nums">
      {keyRatings(prospect).map((c) => {
        const v = ratingNumber(prospect, c.key);
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

function RatingGrid({ prospect, cols }: { prospect: DraftProspect; cols: RatingCol[] }) {
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
      {cols.map((c) => {
        const v = ratingNumber(prospect, c.key);
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

export function ProspectCardDialog({
  prospect,
  takenBy,
  onClose,
}: {
  prospect: DraftProspect | null;
  /** Set once he has been drafted: he has a player page from then on. */
  takenBy?: string | null;
  onClose: () => void;
}) {
  const p = prospect;
  const pitches = p ? pitchesThrown(p) : [];
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
                    <RatingGrid prospect={p} cols={PITCHING} />
                  </Section>
                  <Section title="Pitches">
                    {pitches.length > 0 ? (
                      <RatingGrid prospect={p} cols={pitches} />
                    ) : (
                      <div className="text-xs text-muted">No pitches rated.</div>
                    )}
                  </Section>
                  <Section title="Hitting">
                    <RatingGrid prospect={p} cols={HITTING.slice(0, 4)} />
                  </Section>
                </>
              ) : (
                <Section title="Hitting and fielding">
                  <RatingGrid prospect={p} cols={HITTING} />
                </Section>
              )}
              {takenBy && (
                <div className="flex items-center justify-between border-t border-border/60 pt-3 text-sm">
                  <span className="text-muted">Drafted by {takenBy}</span>
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
