/**
 * Auto-launches the tutorial matched to the current route on first visit.
 *
 * Mount this once at the AppShell level — it reads the current route,
 * looks up the tutorial in the server catalog that pairs with that
 * route (via the ``route`` field each tutorial declares), and opens
 * the TutorialDialog on first visit. Fires once per browser profile
 * per tutorial_id, and respects the global opt-out toggle.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";

import { api } from "@/lib/api";
import { useTutorialStore } from "@/lib/tutorial-store";
import { TutorialDialog, type TutorialStep } from "@/components/help/TutorialDialog";

interface TutorialPayload {
  tutorial_id: string;
  title: string;
  summary: string;
  route?: string | null;
  steps: TutorialStep[];
}

/** Normalize a pathname so routes like ``/roster/`` still match ``/roster``. */
function normalizeRoute(path: string): string {
  if (!path) return "/";
  const trimmed = path.replace(/\/+$/g, "");
  return trimmed || "/";
}

export function FirstVisitTutorialAutoLauncher() {
  const enabled = useTutorialStore((s) => s.enabled);
  const resetCounter = useTutorialStore((s) => s.resetCounter);
  const wasSeen = useTutorialStore((s) => s.wasSeen);
  const markSeen = useTutorialStore((s) => s.markSeen);
  const location = useLocation();

  // Pull the catalog once per mount — tiny payload, cached by react-query.
  const catalog = useQuery({
    queryKey: ["help-tutorials"],
    queryFn: () => api.helpTutorials(),
    enabled,
    staleTime: 5 * 60_000,
  });

  const match = useMemo<TutorialPayload | null>(() => {
    if (!enabled || !catalog.data) return null;
    const current = normalizeRoute(location.pathname);
    const found = catalog.data.tutorials.find(
      (t) => t.route && normalizeRoute(t.route) === current,
    );
    return found ?? null;
  }, [enabled, catalog.data, location.pathname]);

  const [open, setOpen] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);

  // Re-evaluate whenever the route changes, the catalog lands, or
  // "Restart tutorials" is pressed.
  useEffect(() => {
    if (!match) {
      setOpen(false);
      setActiveId(null);
      return;
    }
    if (wasSeen(match.tutorial_id)) return;
    setActiveId(match.tutorial_id);
    setOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match?.tutorial_id, resetCounter]);

  if (!match || !activeId) return null;

  return (
    <TutorialDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next && activeId) markSeen(activeId);
      }}
      title={match.title}
      summary={match.summary}
      steps={match.steps}
    />
  );
}
