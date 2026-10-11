/**
 * Commissioner setting: when the amateur draft runs.
 *
 * Mid-season (the third Tuesday in July; the regular season pauses for it)
 * or in the preseason, before spring training, so the draft class gets a
 * training camp and no regular-season sim waits on a draft. A change
 * applies to the next draft that has not been held; the card says what that
 * means for this league right now before the commissioner saves. Shown on
 * the Commissioner page and on the Draft page's Admin tab.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, Loader2, Save } from "lucide-react";

import {
  api,
  type DraftTiming,
  type DraftTimingChange,
  type DraftTimingOption,
  type SeasonState,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

const FALLBACK_OPTIONS: DraftTimingOption[] = [
  {
    id: "midseason",
    label: "Mid-season (July)",
    description:
      "The draft is held on the third Tuesday in July. The regular season pauses until the last pick is made.",
  },
  {
    id: "preseason",
    label: "Preseason (before spring training)",
    description:
      "The draft is held when the new season begins, before spring training, so the draft class gets a training camp and no regular-season sim waits on the draft.",
  },
];

/** Everything that reads the draft timing or the phase it can change. */
const AFFECTED_QUERIES = [
  "draft-settings",
  "draft-state",
  "draft-pool",
  "season-state",
  "season-readiness",
  "schedule",
  "command-center",
  "news",
];

/** What saving did, in the commissioner's terms. */
function changeMessage(
  timing: DraftTiming,
  change: DraftTimingChange | undefined,
): { text: string; tone: "success" | "warning" } {
  if (!change) return { text: "Saved.", tone: "success" };
  if (change.applies === "now") {
    return {
      text: "Saved. This year's draft is open now — spring training follows the last pick.",
      tone: "success",
    };
  }
  const draft = change.preseason_draft;
  if (draft?.error) {
    return {
      text: `Saved, but this year's draft could not be opened: ${draft.error}`,
      tone: "warning",
    };
  }
  if (change.error) {
    return {
      text: `Saved, but the league could not be updated right away: ${change.error}`,
      tone: "warning",
    };
  }
  if (change.draft_pool?.error) {
    return {
      text: `Saved. Next year's draft class could not be generated yet (${change.draft_pool.error}); it will be created when the draft opens.`,
      tone: "warning",
    };
  }
  if (change.draft_pool?.seeded) {
    return {
      text: "Saved. Next year's draft class is ready to scout on the Draft page.",
      tone: "success",
    };
  }
  if (timing === "preseason") {
    if (draft?.reason === "after_training_camp") {
      return {
        text: "Saved. Spring training has already run, so this year's draft stays in July; the preseason draft starts next year.",
        tone: "success",
      };
    }
    if (draft?.reason === "first_season") {
      return {
        text: "Saved. There is no draft this season: a new league's first draft follows its first completed season, so it opens next preseason.",
        tone: "success",
      };
    }
    if (draft?.reason === "completed") {
      return {
        text: "Saved. This year's draft has already been held; the preseason draft starts next year.",
        tone: "success",
      };
    }
    if (change.phase === "REGULAR_SEASON" || change.phase === "AMATEUR_DRAFT") {
      return {
        text: "Saved. This season keeps its July draft; the preseason draft starts next year.",
        tone: "success",
      };
    }
    return {
      text: "Saved. The next draft opens in the preseason, before spring training.",
      tone: "success",
    };
  }
  if (change.phase === "AMATEUR_DRAFT") {
    return {
      text: "Saved. The draft under way carries on to its last pick; next year's draft is held in July.",
      tone: "success",
    };
  }
  return {
    text: "Saved. It applies to the next draft that has not been held.",
    tone: "success",
  };
}

/** What choosing `timing` will do, given where the league is right now. */
function previewMessage(timing: DraftTiming, season: SeasonState | undefined): string {
  const phase = season?.phase;
  const campDone = !!season?.preseason_done?.training_camp;
  const draftDone = !!season?.draft_completed;
  if (timing === "preseason") {
    if (phase === "PRESEASON" && !campDone && !draftDone) {
      return "The league is in the preseason and spring training has not run, so this year's draft opens as soon as you save. (A brand-new league has no draft until after its first season.)";
    }
    if (phase === "PRESEASON") {
      return "This year's draft is not moved: it stays in July. The preseason draft starts next year.";
    }
    if (phase === "REGULAR_SEASON" || phase === "AMATEUR_DRAFT") {
      return "The season under way keeps its July draft. The preseason draft starts next year.";
    }
    if (phase === "OFFSEASON") {
      return "The next draft opens when the preseason begins. Saving also puts next year's draft class on the Draft page to scout.";
    }
    return "This applies to the next draft that has not been held. A regular season already under way keeps its July draft.";
  }
  if (phase === "AMATEUR_DRAFT") {
    return "The draft under way carries on to its last pick. From next year the draft is held in July.";
  }
  if (season?.draft_skipped) {
    return "This season has no draft as things stand. Switching back gives it a July draft.";
  }
  return "This applies to the next draft that has not been held. A preseason draft already held this year is not repeated in July.";
}

export function DraftTimingCard() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["draft-settings"],
    queryFn: () => api.draftSettings(),
  });
  const season = useQuery({
    queryKey: ["season-state"],
    queryFn: () => api.seasonState(),
    staleTime: 60_000,
  });
  const saved: DraftTiming = settings.data?.timing ?? "midseason";
  const [timing, setTiming] = useState<DraftTiming>(saved);

  useEffect(() => {
    setTiming(saved);
  }, [saved]);

  const mutation = useMutation({
    mutationFn: (next: DraftTiming) => api.saveDraftTiming(next),
    onSuccess: () => {
      // The draft may have opened: the season phase, the draft state, the
      // calendar and the preseason checklist all follow from this setting.
      for (const key of AFFECTED_QUERIES) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
  });

  const options = settings.data?.timing_options?.length
    ? settings.data.timing_options
    : FALLBACK_OPTIONS;
  const dirty = timing !== saved;
  const selected = options.find((o) => o.id === timing);
  // Without the saved value the card would show "Mid-season" for a league
  // that drafts in the preseason, and a save could silently flip it.
  const unavailable = settings.isLoading || settings.isError;
  const result =
    mutation.isSuccess && !dirty
      ? changeMessage(mutation.variables ?? saved, mutation.data?.timing_change)
      : null;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Amateur draft timing</CardTitle>
          <CardDescription>
            When the league holds its amateur draft each year
          </CardDescription>
        </div>
        {!unavailable && (
          <Badge tone={saved === "preseason" ? "amber" : "neutral"}>
            <CalendarClock className="h-3 w-3" />{" "}
            {saved === "preseason" ? "Preseason" : "Mid-season"}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {settings.isError && (
          <div className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              The current draft timing could not be loaded (
              {(settings.error as Error).message}).{" "}
              <button
                type="button"
                className="font-semibold underline underline-offset-2"
                onClick={() => settings.refetch()}
              >
                Try again
              </button>
            </span>
          </div>
        )}
        <div
          role="group"
          aria-label="Amateur draft timing"
          className="flex flex-col gap-1 rounded-lg border border-border bg-surfaceAlt p-1 sm:flex-row"
        >
          {options.map((opt) => (
            <button
              key={opt.id}
              type="button"
              aria-pressed={timing === opt.id}
              onClick={() => setTiming(opt.id)}
              disabled={unavailable || mutation.isPending}
              className={cn(
                "flex-1 rounded-md px-3 py-1.5 text-xs font-semibold tracking-wide transition disabled:cursor-not-allowed disabled:opacity-60",
                timing === opt.id && !unavailable
                  ? "bg-amber text-espresso"
                  : "text-muted hover:bg-surface hover:text-ink",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {selected && !unavailable && (
          <p className="text-xs text-muted">{selected.description}</p>
        )}
        <p className="text-xs text-muted">
          Either way the pick clock and auto-draft work the same, draft picks
          go to Low-A, and free-agent signings and contract extensions pause
          while a draft is open. A preseason draft is ordered by the reverse
          of last season&apos;s records, so a brand-new league that drafts in
          the preseason has no draft in its first season: its first draft
          opens the following preseason.
        </p>
        {dirty && (
          <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{previewMessage(timing, season.data)}</span>
          </div>
        )}
        {mutation.isError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {(mutation.error as Error).message}
          </div>
        )}
        {result && (
          <div
            className={cn(
              "rounded-md border px-3 py-2 text-sm",
              result.tone === "warning"
                ? "border-warning/40 bg-warning/10 text-warning"
                : "border-success/40 bg-success/10 text-success",
            )}
          >
            {result.text}
          </div>
        )}
        <div className="flex justify-end">
          <Button
            onClick={() => {
              if (!mutation.isPending) mutation.mutate(timing);
            }}
            disabled={!dirty || unavailable || mutation.isPending}
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save draft timing
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
