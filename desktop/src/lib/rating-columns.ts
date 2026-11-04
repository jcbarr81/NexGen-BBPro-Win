/**
 * Table columns an owner can choose (backlog #69, 8.10.0).
 *
 * Every player table (Roster, Free Agency, Players, Position Players,
 * Pitchers, the Lineup pools) shows its default columns until the owner
 * picks others with the ColumnPicker; the choice is kept per table in
 * localStorage. Pages build their catalogue from the shared definitions
 * below so a rating reads the same everywhere.
 */

import { useMemo } from "react";

import { useStoredPreference } from "@/lib/use-persisted-state";

export type ColumnDef = {
  key: string;
  /** Short header label ("FB"). */
  label: string;
  /** Full name, shown in the picker ("Fastball"). */
  name?: string;
  /** Picker section ("Ratings", "Pitches"). */
  group?: string;
};

const RATING_DEFS: Record<string, ColumnDef> = {
  ch: { key: "ch", label: "CH", name: "Contact", group: "Ratings" },
  ph: { key: "ph", label: "PH", name: "Power", group: "Ratings" },
  sp: { key: "sp", label: "SP", name: "Speed", group: "Ratings" },
  eye: { key: "eye", label: "EYE", name: "Eye", group: "Ratings" },
  fa: { key: "fa", label: "FA", name: "Fielding", group: "Ratings" },
  arm: { key: "arm", label: "ARM", name: "Arm", group: "Ratings" },
  endurance: { key: "endurance", label: "EN", name: "Endurance", group: "Ratings" },
  control: { key: "control", label: "CTRL", name: "Control", group: "Ratings" },
  movement: { key: "movement", label: "MOV", name: "Movement", group: "Ratings" },
  fb: { key: "fb", label: "FB", name: "Fastball", group: "Pitches" },
  sl: { key: "sl", label: "SL", name: "Slider", group: "Pitches" },
  cu: { key: "cu", label: "CU", name: "Changeup", group: "Pitches" },
  cb: { key: "cb", label: "CB", name: "Curveball", group: "Pitches" },
  si: { key: "si", label: "SI", name: "Sinker", group: "Pitches" },
  scb: { key: "scb", label: "SCB", name: "Screwball", group: "Pitches" },
  kn: { key: "kn", label: "KN", name: "Knuckleball", group: "Pitches" },
};

/** A pitcher's arm reads "AS" (arm strength), as on his ratings card. */
const PITCHER_ARM: ColumnDef = {
  key: "arm",
  label: "AS",
  name: "Arm strength",
  group: "Ratings",
};

export const HITTER_RATING_KEYS = ["ch", "ph", "sp", "eye", "fa", "arm"];
export const PITCHER_RATING_KEYS = ["control", "movement", "endurance", "arm", "fa"];
export const PITCH_KEYS = ["fb", "sl", "cu", "cb", "si", "scb", "kn"];

const PITCH_KEY_SET = new Set(PITCH_KEYS);

/**
 * A page's catalogue: its default columns first, in the order it shows
 * them today, then every other rating of that kind.
 */
export function ratingCatalog(
  kind: "hitters" | "pitchers",
  defaults: string[],
): ColumnDef[] {
  const all = kind === "hitters" ? HITTER_RATING_KEYS : [...PITCHER_RATING_KEYS, ...PITCH_KEYS];
  const order = [...defaults, ...all.filter((k) => !defaults.includes(k))];
  return order.flatMap((k) => {
    const def = kind === "pitchers" && k === "arm" ? PITCHER_ARM : RATING_DEFS[k];
    return def ? [def] : [];
  });
}

/** The value a rating cell shows: a pitch rated 0 is one he doesn't
 *  throw, so it reads "—" like a missing rating. */
export function ratingValue(
  ratings: Record<string, number | string | null | undefined>,
  key: string,
): number | string | null | undefined {
  const raw = ratings[key];
  if (PITCH_KEY_SET.has(key) && (raw === 0 || raw === "0")) return null;
  return raw;
}

export type ColumnChoice<C extends ColumnDef = ColumnDef> = {
  /** Every column the owner can pick, in table order. */
  catalog: C[];
  /** The columns to show, in table order. */
  columns: C[];
  isShown: (key: string) => boolean;
  toggle: (key: string) => void;
  reset: () => void;
  isDefault: boolean;
};

/**
 * The columns a table shows: the owner's pick (kept under ``id``), else the
 * page's defaults. Unknown stored keys are ignored, so a catalogue change
 * never breaks a saved choice; the last column can't be unticked.
 */
export function useColumnChoice<C extends ColumnDef>(
  id: string,
  catalog: C[],
  defaults: string[],
): ColumnChoice<C> {
  const [stored, setStored] = useStoredPreference<string[] | null>(
    `columns:${id}`,
    null,
  );
  return useMemo(() => {
    const known = new Set(catalog.map((c) => c.key));
    const picked = (stored ?? defaults).filter((k) => known.has(k));
    const shown = new Set(picked.length ? picked : defaults);
    const columns = catalog.filter((c) => shown.has(c.key));
    return {
      catalog,
      columns,
      isShown: (key: string) => shown.has(key),
      toggle: (key: string) => {
        const next = new Set(shown);
        if (next.has(key)) {
          if (next.size <= 1) return;
          next.delete(key);
        } else {
          next.add(key);
        }
        setStored(catalog.map((c) => c.key).filter((k) => next.has(k)));
      },
      reset: () => setStored(null),
      isDefault: stored == null,
    };
    // defaults is a module constant per page; catalog likewise.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stored, catalog]);
}
