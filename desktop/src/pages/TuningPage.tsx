/**
 * Phase 4 port of ui/playbalance_editor.py.
 *
 * Full physics-tuning editor: every section + every slider the PyQt
 * editor exposes, driven by the spec list shared via /tuning. Overrides
 * save through services.physics_tuning_settings so both UIs agree.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import {
  AlertTriangle,
  Loader2,
  RotateCcw,
  Save,
  Sliders,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useConfirmDialog } from "@/lib/use-confirm";
import { cn } from "@/lib/cn";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";

interface SliderSpec {
  key: string;
  label: string;
  description: string;
  min_value: number;
  max_value: number;
  step: number;
  fmt: string;
}

interface Section {
  label: string;
  sliders: SliderSpec[];
}

export function TuningPage() {
  const role = useAuthStore((s) => s.role);
  const queryClient = useQueryClient();
  const { confirm, dialog: confirmDialog } = useConfirmDialog();

  const tuning = useQuery({
    queryKey: ["tuning"],
    queryFn: () => api.tuning(),
    enabled: role === "admin",
  });

  const [draft, setDraft] = useState<Record<string, number>>({});

  useEffect(() => {
    if (tuning.data) {
      // Draft always starts from `overrides` merged over `defaults` so
      // the UI reflects the effective value for every knob even if the
      // override file is partial.
      setDraft({
        ...tuning.data.defaults,
        ...tuning.data.overrides,
      });
    }
  }, [tuning.data]);

  const save = useMutation({
    mutationFn: (payload: Record<string, number>) => api.saveTuning(payload),
    onSuccess: (data) =>
      queryClient.setQueryData(["tuning"], {
        ...tuning.data,
        ...data,
      }),
  });
  const reset = useMutation({
    mutationFn: () => api.resetTuning(),
    onSuccess: (data) =>
      queryClient.setQueryData(["tuning"], {
        ...tuning.data,
        ...data,
      }),
  });

  const dirty = useMemo(() => {
    if (!tuning.data) return false;
    const merged = { ...tuning.data.defaults, ...tuning.data.overrides };
    for (const [k, v] of Object.entries(draft)) {
      if (Math.abs(Number(v) - Number(merged[k] ?? 0)) > 1e-9) return true;
    }
    return false;
  }, [draft, tuning.data]);

  if (role !== "admin") return <Navigate to="/home" replace />;

  return (
    <AppShell
      title="Physics Tuning"
      subtitle="Every knob from the legacy play-balance editor"
    >
      <div className="mb-4 flex items-center justify-end gap-2">
        <Button
          variant="ghost"
          onClick={async () => {
            if (
              !(await confirm({
                title: "Reset tuning overrides?",
                description: "Every override reverts to the engine default.",
                confirmLabel: "Reset all",
                danger: true,
              }))
            )
              return;
            reset.mutate();
          }}
          disabled={reset.isPending}
        >
          {reset.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RotateCcw className="h-4 w-4" />
          )}
          Reset all
        </Button>
        <Button
          onClick={() => {
            if (!tuning.data) return;
            // Only persist knobs that actually differ from the default.
            const diff: Record<string, number> = {};
            for (const [k, v] of Object.entries(draft)) {
              if (
                Math.abs(Number(v) - Number(tuning.data.defaults[k] ?? 0)) >
                1e-9
              ) {
                diff[k] = Number(v);
              }
            }
            save.mutate(diff);
          }}
          disabled={!dirty || save.isPending}
        >
          {save.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          Save overrides
        </Button>
      </div>

      {(save.isError || reset.isError) && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="h-4 w-4" />
          {((save.error || reset.error) as Error).message}
        </div>
      )}

      {tuning.isLoading ? (
        <LoadingCard />
      ) : tuning.isError ? (
        <ErrorCard message={(tuning.error as Error).message} />
      ) : tuning.data ? (
        <div className="space-y-6">
          {tuning.data.sections.map((section: Section) => (
            <SectionCard
              key={section.label}
              section={section}
              draft={draft}
              defaults={tuning.data!.defaults}
              overrides={tuning.data!.overrides}
              onChange={(key, value) =>
                setDraft((prev) => ({ ...prev, [key]: value }))
              }
              onReset={(key) =>
                setDraft((prev) => ({
                  ...prev,
                  [key]: Number(tuning.data!.defaults[key] ?? 0),
                }))
              }
            />
          ))}
        </div>
      ) : null}
      {confirmDialog}
    </AppShell>
  );
}

function SectionCard({
  section,
  draft,
  defaults,
  overrides,
  onChange,
  onReset,
}: {
  section: Section;
  draft: Record<string, number>;
  defaults: Record<string, number>;
  overrides: Record<string, number>;
  onChange: (key: string, value: number) => void;
  onReset: (key: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{section.label}</CardTitle>
          <CardDescription>{section.sliders.length} knobs</CardDescription>
        </div>
        <Badge tone="amber">
          <Sliders className="h-3 w-3" />
        </Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {section.sliders.map((spec) => (
          <SliderRow
            key={spec.key}
            spec={spec}
            value={Number(draft[spec.key] ?? defaults[spec.key] ?? 0)}
            isOverridden={
              Object.prototype.hasOwnProperty.call(overrides, spec.key)
            }
            defaultValue={Number(defaults[spec.key] ?? 0)}
            onChange={(v) => onChange(spec.key, v)}
            onReset={() => onReset(spec.key)}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function SliderRow({
  spec,
  value,
  isOverridden,
  defaultValue,
  onChange,
  onReset,
}: {
  spec: SliderSpec;
  value: number;
  isOverridden: boolean;
  defaultValue: number;
  onChange: (v: number) => void;
  onReset: () => void;
}) {
  const fmt = (v: number) => {
    // The server spec uses Python format strings (e.g. "{:.2f}"). Translate
    // the common precision cases; fall back to toFixed(2).
    const m = spec.fmt.match(/\{:\.(\d+)f\}/);
    if (m) return v.toFixed(Number(m[1]));
    return v.toFixed(2);
  };
  const diff = Math.abs(value - defaultValue) > 1e-9;
  return (
    <div className="rounded-xl border border-border bg-surfaceAlt/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold">{spec.label}</span>
            {isOverridden && <Badge tone="amber">override</Badge>}
            {diff && !isOverridden && <Badge tone="warning">unsaved</Badge>}
          </div>
          <p className="text-xs text-muted">{spec.description}</p>
        </div>
        <span
          className={cn(
            "ml-2 shrink-0 font-mono text-sm font-semibold",
            diff ? "text-amber-text" : "text-ink",
          )}
        >
          {fmt(value)}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <input
          type="range"
          min={spec.min_value}
          max={spec.max_value}
          step={spec.step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 accent-amber"
        />
        <input
          type="number"
          min={spec.min_value}
          max={spec.max_value}
          step={spec.step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-8 w-20 rounded-md border border-border bg-canvas/60 px-2 text-right text-xs tabular-nums focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
        />
        <Button
          variant="ghost"
          size="icon"
          title={`Reset to default (${fmt(defaultValue)})`}
          disabled={!diff}
          onClick={onReset}
        >
          <RotateCcw className="h-3 w-3" />
        </Button>
      </div>
      <div className="mt-1 flex justify-between text-[10px] uppercase tracking-wider text-muted">
        <span>{fmt(spec.min_value)}</span>
        <span>default {fmt(defaultValue)}</span>
        <span>{fmt(spec.max_value)}</span>
      </div>
    </div>
  );
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading tuning…</span>
      </CardContent>
    </Card>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10 text-danger">
        <AlertTriangle className="h-5 w-5" />
        <span className="text-sm">{message}</span>
      </CardContent>
    </Card>
  );
}
