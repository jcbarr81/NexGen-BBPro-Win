/**
 * Phase 4 port of ui/admin_dashboard/pages/utilities.py.
 *
 * Surfaces two groups of actions:
 *
 * - **Assets** (logo + avatar generation) -- lights up in Phase 6 when the
 *   AI asset pipeline gets its own endpoints.
 * - **Exports** (HTML / CSV / almanac / owner snapshot) -- lands alongside
 *   Phase 8 parity work.
 *
 * Until those ship, the buttons are disabled with tooltips pointing at the
 * phase that unlocks them. The top of the page shows live sidecar
 * diagnostics so admins can confirm everything's wired up correctly.
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Database,
  FileDown,
  FileSpreadsheet,
  Image as ImageIcon,
  Loader2,
  Package,
  Palette,
  Server,
  Trophy,
  UserSquare2,
} from "lucide-react";

import { api, type HealthPayload } from "@/lib/api";
import { getBridge } from "@/lib/bridge";
import { useAuthStore } from "@/lib/auth-store";
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

interface ActionSpec {
  label: string;
  description: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  availableIn: string;
}

const ASSET_ACTIONS: ActionSpec[] = [
  {
    label: "Generate Team Logos",
    description: "AI-generate or refresh logo images for every team.",
    Icon: Palette,
    availableIn: "Phase 6",
  },
  {
    label: "Generate Player Avatars",
    description: "Batch-generate avatar images for the active roster.",
    Icon: UserSquare2,
    availableIn: "Phase 6",
  },
];

const EXPORT_ACTIONS: ActionSpec[] = [
  {
    label: "Export Reports (HTML)",
    description: "Bundle league reports as a browsable HTML site.",
    Icon: FileDown,
    availableIn: "Phase 8",
  },
  {
    label: "Export Reports (CSV)",
    description: "Flat CSV exports for spreadsheets and analytics.",
    Icon: FileSpreadsheet,
    availableIn: "Phase 8",
  },
  {
    label: "Export Almanac (HTML)",
    description: "Historical multi-page league almanac.",
    Icon: Trophy,
    availableIn: "Phase 8",
  },
  {
    label: "Owner Snapshot Zip",
    description: "Snapshot league data for owners to sync offline.",
    Icon: Package,
    availableIn: "Phase 8",
  },
];

export function UtilitiesPage() {
  const user = useAuthStore();
  const health = useQuery({
    queryKey: ["healthz"],
    queryFn: () => api.health(),
    refetchInterval: 15_000,
  });

  return (
    <AppShell
      title="Utilities"
      subtitle="Diagnostics plus bulk asset and export jobs."
    >
      <div className="space-y-6">
        <DiagnosticsCard
          health={health.data}
          isLoading={health.isLoading}
          isError={health.isError}
          error={health.error}
          user={user}
        />
        <ActionsCard
          title="Assets"
          description="Bulk image generation. Backed by the Python sidecar's torch/diffusers stack."
          icon={<ImageIcon className="h-3 w-3" />}
          actions={ASSET_ACTIONS}
        />
        <ActionsCard
          title="Exports & Sharing"
          description="One-click bundles for outside-the-app distribution."
          icon={<FileDown className="h-3 w-3" />}
          actions={EXPORT_ACTIONS}
        />
      </div>
    </AppShell>
  );
}

function DiagnosticsCard({
  health,
  isLoading,
  isError,
  error,
  user,
}: {
  health: HealthPayload | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  user: ReturnType<typeof useAuthStore.getState>;
}) {
  const bridge = getBridge();
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Sidecar Diagnostics</CardTitle>
          <CardDescription>
            Live status of the Python FastAPI sidecar this window is talking to.
          </CardDescription>
        </div>
        {isLoading ? (
          <Badge tone="neutral">
            <Loader2 className="h-3 w-3 animate-spin" /> Checking
          </Badge>
        ) : isError ? (
          <Badge tone="danger">
            <AlertTriangle className="h-3 w-3" /> Offline
          </Badge>
        ) : (
          <Badge tone="success">
            <Server className="h-3 w-3" /> Online
          </Badge>
        )}
      </CardHeader>
      <CardContent>
        {isError ? (
          <div className="text-sm text-danger">
            {(error as Error)?.message ?? "Unknown error"}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <DiagItem
              label="Version"
              value={health?.version ?? "…"}
              Icon={Server}
            />
            <DiagItem
              label="Active League"
              value={health?.active_league ?? "—"}
              Icon={Trophy}
            />
            <DiagItem
              label="API URL"
              value={bridge.apiBaseUrl}
              Icon={Server}
              mono
            />
            <DiagItem
              label="Data Root"
              value={health?.data_root ?? "…"}
              Icon={Database}
              mono
            />
            <DiagItem
              label="Signed in as"
              value={user.username ?? "—"}
              sub={user.role ?? undefined}
              Icon={UserSquare2}
            />
            <DiagItem
              label="Shell"
              value={bridge.isPackaged ? "Packaged" : "Dev"}
              sub={bridge.source}
              Icon={Package}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DiagItem({
  label,
  value,
  sub,
  Icon,
  mono,
}: {
  label: string;
  value: string;
  sub?: string;
  Icon: React.ComponentType<React.SVGProps<SVGSVGElement>>;
  mono?: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-surfaceAlt/40 p-3">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        <Icon className="h-3 w-3" /> {label}
      </div>
      <div
        className={`mt-1 truncate text-sm font-semibold text-ink ${mono ? "font-mono text-xs" : ""}`}
        title={value}
      >
        {value}
      </div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

function ActionsCard({
  title,
  description,
  icon,
  actions,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
  actions: ActionSpec[];
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <Badge tone="neutral">{icon} Deferred</Badge>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {actions.map((action) => (
          <div
            key={action.label}
            className="flex items-start gap-3 rounded-xl border border-border bg-surfaceAlt/40 p-3"
          >
            <div className="rounded-lg border border-border bg-surface p-2 text-amber">
              <action.Icon className="h-5 w-5" aria-hidden />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <div className="truncate font-semibold">{action.label}</div>
                <Badge tone="amber">{action.availableIn}</Badge>
              </div>
              <div className="mt-1 text-xs text-muted">{action.description}</div>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                disabled
                title={`Available in ${action.availableIn}`}
              >
                Run
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
