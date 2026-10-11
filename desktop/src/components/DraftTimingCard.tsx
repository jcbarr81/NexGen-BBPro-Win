/**
 * Commissioner setting: when the amateur draft runs.
 *
 * Mid-season (the third Tuesday in July; the regular season pauses for it)
 * or in the preseason, before spring training, so the draft class gets a
 * training camp and no regular-season sim waits on a draft. A change
 * applies to the next draft that has not been held; the card says what that
 * means before the commissioner saves. Shown on the Commissioner page and on
 * the Draft page's Admin tab.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, Loader2, Save } from "lucide-react";

import {
  api,
  type DraftTiming,
  type DraftTimingChange,
  type DraftTimingOption,
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

function changeMessage(change: DraftTimingChange | undefined): string {
  if (!change) return "Saved.";
  if (change.applies === "now") {
    return "Saved. This year's draft is open now — spring training follows the last pick.";
  }
  if (change.preseason_draft?.error) {
    return `Saved. The draft could not be opened now (${change.preseason_draft.error}); it stays where it was for this year.`;
  }
  if (change.draft_pool?.seeded) {
    return "Saved. Next year's draft class is ready to scout on the Draft page.";
  }
  return "Saved. It applies to the next draft.";
}

export function DraftTimingCard() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["draft-settings"],
    queryFn: () => api.draftSettings(),
  });
  const saved: DraftTiming = settings.data?.timing ?? "midseason";
  const [timing, setTiming] = useState<DraftTiming>(saved);

  useEffect(() => {
    setTiming(saved);
  }, [saved]);

  const mutation = useMutation({
    mutationFn: () => api.saveDraftTiming(timing),
    onSuccess: () => {
      // The draft may have opened: the season phase, the draft state and the
      // preseason checklist all follow from this setting.
      for (const key of ["draft-settings", "draft-state", "season-state"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
  });

  const options = settings.data?.timing_options?.length
    ? settings.data.timing_options
    : FALLBACK_OPTIONS;
  const dirty = timing !== saved;
  const selected = options.find((o) => o.id === timing);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Amateur draft timing</CardTitle>
          <CardDescription>
            When the league holds its amateur draft each year
          </CardDescription>
        </div>
        <Badge tone={saved === "preseason" ? "amber" : "neutral"}>
          <CalendarClock className="h-3 w-3" />{" "}
          {saved === "preseason" ? "Preseason" : "Mid-season"}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-1 rounded-lg border border-border bg-surfaceAlt p-1 sm:flex-row">
          {options.map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => setTiming(opt.id)}
              disabled={settings.isLoading}
              className={cn(
                "flex-1 rounded-md px-3 py-1.5 text-xs font-semibold tracking-wide transition",
                timing === opt.id
                  ? "bg-amber text-espresso"
                  : "text-muted hover:bg-surface hover:text-ink",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
        {selected && <p className="text-xs text-muted">{selected.description}</p>}
        <p className="text-xs text-muted">
          Either way the draft order is the reverse of last season&apos;s
          records, the pick clock and auto-draft work the same, and draft
          picks go to Low-A. A new league&apos;s first draft comes after its
          first completed season.
        </p>
        {dirty && (
          <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              {timing === "preseason"
                ? "This applies to the next draft. A regular season already under way keeps its July draft. If the league is in the preseason and spring training has not run, this year's draft opens as soon as you save."
                : "This applies to the next draft. A preseason draft already held or under way is not repeated in July."}
            </span>
          </div>
        )}
        {mutation.isError && (
          <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {(mutation.error as Error).message}
          </div>
        )}
        {mutation.isSuccess && !dirty && (
          <div className="rounded-md border border-success/40 bg-success/10 px-3 py-2 text-sm text-success">
            {changeMessage(mutation.data?.timing_change)}
          </div>
        )}
        <div className="flex justify-end">
          <Button
            onClick={() => mutation.mutate()}
            disabled={!dirty || mutation.isPending}
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
