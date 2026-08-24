/**
 * Utilities page:
 * - Live sidecar diagnostics at the top.
 * - Asset generation + report/almanac/snapshot exports that POST to the
 *   real `/exports/*` endpoints (admin-only). Each button captures a
 *   per-action result so the operator can see what was produced.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileDown,
  FileSpreadsheet,
  Image as ImageIcon,
  Loader2,
  Lock,
  Package,
  Palette,
  Play,
  Server,
  ShieldCheck,
  Trophy,
  UserSquare2,
} from "lucide-react";

import { api, runExportJob, type ExportJobStatus, type HealthPayload } from "@/lib/api";
import { getBridge } from "@/lib/bridge";
import { useAuthStore } from "@/lib/auth-store";
import { useConfirmDialog } from "@/lib/use-confirm";
import { AppShell } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@/components/ui";

interface ActionResult {
  ok: boolean;
  message: string;
}

interface ActionProgress {
  done: number;
  total: number;
  phase?: string;
}

export function UtilitiesPage() {
  const user = useAuthStore();
  const role = user.role;
  const isAdmin = role === "admin";
  const [results, setResults] = useState<Record<string, ActionResult>>({});
  const [progress, setProgress] = useState<Record<string, ActionProgress>>({});
  const { confirm, dialog: confirmDialog } = useConfirmDialog();
  // Which specific tile triggered the in-flight mutation. Logos + avatars
  // each have two sibling tiles that share the same useMutation, so the
  // "is this running" signal needs a finer key than the mutation itself.
  const [activeAction, setActiveAction] = useState<string | null>(null);

  const health = useQuery({
    queryKey: ["healthz"],
    queryFn: () => api.health(),
    refetchInterval: 15_000,
  });

  function recordResult(key: string, ok: boolean, message: string) {
    setResults((prev) => ({ ...prev, [key]: { ok, message } }));
  }

  function recordProgress(key: string, status: ExportJobStatus) {
    setProgress((prev) => ({
      ...prev,
      [key]: { done: status.done, total: status.total, phase: status.phase },
    }));
  }

  function clearProgress(key: string) {
    setProgress((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  const bumpLogoVersion = useAuthStore((s) => s.bumpLogoVersion);
  const logos = useMutation({
    mutationFn: (args: { tileKey: string; engine: "openai" | "auto_logo" }) =>
      runExportJob(
        () => api.generateLogos({ force_engine: args.engine }),
        (status) => recordProgress(args.tileKey, status),
      ),
    onSuccess: (res, args) => {
      clearProgress(args.tileKey);
      setActiveAction(null);
      const engine = (res.result?.engine as string | undefined) ?? "auto_logo";
      const engineLabel =
        engine === "vertex"
          ? "Vertex AI Imagen (detailed)"
          : engine === "openai"
            ? "OpenAI gpt-image-1 (detailed)"
            : "auto_logo fallback (simple vector)";
      recordResult(
        args.tileKey,
        true,
        `Wrote ${res.output_dir ?? "(unknown)"} — engine: ${engineLabel}`,
      );
      bumpLogoVersion();
    },
    onError: (e, args) => {
      clearProgress(args.tileKey);
      setActiveAction(null);
      recordResult(args.tileKey, false, e instanceof Error ? e.message : String(e));
    },
  });
  const normalizeLogos = useMutation({
    mutationFn: () =>
      runExportJob(
        () => api.normalizeLogos(),
        (status) => recordProgress("logos-normalize", status),
      ),
    onSuccess: () => {
      clearProgress("logos-normalize");
      setActiveAction(null);
      recordResult("logos-normalize", true, "Logo framing normalized.");
      bumpLogoVersion();
    },
    onError: (e) => {
      clearProgress("logos-normalize");
      setActiveAction(null);
      recordResult("logos-normalize", false, e instanceof Error ? e.message : String(e));
    },
  });
  const avatars = useMutation({
    mutationFn: (args: {
      tileKey: string;
      initial: boolean;
      engine?: "ai" | "template";
      onlyFailed?: boolean;
    }) =>
      runExportJob(
        () => api.generateAvatars(args.initial, args.engine, args.onlyFailed),
        (status) => recordProgress(args.tileKey, status),
      ),
    onSuccess: (_res, args) => {
      clearProgress(args.tileKey);
      setActiveAction(null);
      recordResult(
        args.tileKey,
        true,
        args.initial
          ? "Initial creation complete — all avatars regenerated."
          : args.onlyFailed
            ? "Filled in template/missing avatars with AI portraits."
            : "Avatars generated for players missing one.",
      );
    },
    onError: (e, args) => {
      clearProgress(args.tileKey);
      setActiveAction(null);
      recordResult(args.tileKey, false, e instanceof Error ? e.message : String(e));
    },
  });
  const reportsHtml = useMutation({
    mutationFn: () => api.exportReports("html"),
    onSuccess: (res) =>
      recordResult(
        "reports-html",
        true,
        `HTML report bundle → ${String(res.output_dir ?? "ok")}`,
      ),
    onError: (e) =>
      recordResult(
        "reports-html",
        false,
        e instanceof Error ? e.message : String(e),
      ),
  });
  const reportsCsv = useMutation({
    mutationFn: () => api.exportReports("csv"),
    onSuccess: (res) =>
      recordResult(
        "reports-csv",
        true,
        `CSV reports → ${String(res.output_dir ?? "ok")}`,
      ),
    onError: (e) =>
      recordResult(
        "reports-csv",
        false,
        e instanceof Error ? e.message : String(e),
      ),
  });
  const almanac = useMutation({
    mutationFn: () => api.exportAlmanac(),
    onSuccess: (res) =>
      recordResult(
        "almanac",
        true,
        `Almanac → ${String((res as { output_dir?: string }).output_dir ?? "ok")}`,
      ),
    onError: (e) =>
      recordResult("almanac", false, e instanceof Error ? e.message : String(e)),
  });

  return (
    <AppShell
      title="Utilities"
      subtitle="Diagnostics + asset and export jobs"
    >
      <div className="space-y-6">
        {!isAdmin && <AdminElevateCard currentUsername={user.username} />}

        <DiagnosticsCard
          health={health.data}
          isLoading={health.isLoading}
          isError={health.isError}
          error={health.error}
          user={user}
        />

        {isAdmin && <AiStatusCard />}

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Assets</CardTitle>
              <CardDescription>
                Bulk image generation — heavy. Logos + avatars run on the
                sidecar's torch/diffusers stack.
              </CardDescription>
            </div>
            <Badge tone="amber">
              <ImageIcon className="h-3 w-3" /> Admin
            </Badge>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <ActionTile
              icon={<Palette className="h-5 w-5" />}
              title="Detailed Logos (AI)"
              description="Uses Vertex AI Imagen (cloud) or OpenAI gpt-image-1 (local) with a rich per-team prompt. Falls back to simple vector logos if neither is configured."
              pending={activeAction === "logos-openai"}
              progress={progress["logos-openai"]}
              result={results["logos-openai"]}
              disabled={!isAdmin || activeAction !== null}
              onRun={() => {
                setActiveAction("logos-openai");
                logos.mutate({ tileKey: "logos-openai", engine: "openai" });
              }}
            />
            <ActionTile
              icon={<Palette className="h-5 w-5" />}
              title="Simple Logos (fallback)"
              description="Uses the built-in vector renderer. No network call; runs offline."
              pending={activeAction === "logos-auto"}
              progress={progress["logos-auto"]}
              result={results["logos-auto"]}
              disabled={!isAdmin || activeAction !== null}
              onRun={() => {
                setActiveAction("logos-auto");
                logos.mutate({ tileKey: "logos-auto", engine: "auto_logo" });
              }}
            />
            <ActionTile
              icon={<Palette className="h-5 w-5" />}
              title="Tighten logo framing"
              description="No AI: trims the background margin off existing logos so every team's mascot fills the frame consistently. Keeps the current artwork."
              pending={activeAction === "logos-normalize"}
              progress={progress["logos-normalize"]}
              result={results["logos-normalize"]}
              disabled={!isAdmin || activeAction !== null}
              onRun={() => {
                setActiveAction("logos-normalize");
                normalizeLogos.mutate();
              }}
            />
            <ActionTile
              icon={<UserSquare2 className="h-5 w-5" />}
              title="Fill missing / template avatars (AI)"
              description="AI-generates a unique portrait for any player who doesn't have one yet OR is still showing a generic template — leaves real AI avatars untouched. Only bills for the players that need one."
              pending={activeAction === "avatars-fill"}
              progress={progress["avatars-fill"]}
              result={results["avatars-fill"]}
              disabled={!isAdmin || activeAction !== null}
              onRun={() => {
                setActiveAction("avatars-fill");
                avatars.mutate({
                  tileKey: "avatars-fill",
                  initial: false,
                  engine: "ai",
                  onlyFailed: true,
                });
              }}
            />
            <ActionTile
              icon={<UserSquare2 className="h-5 w-5" />}
              title="Regenerate all avatars (AI)"
              description="Wipes every avatar and AI-generates all from scratch. Slow + bills per image for the whole league."
              pending={activeAction === "avatars-regen"}
              progress={progress["avatars-regen"]}
              result={results["avatars-regen"]}
              disabled={!isAdmin || activeAction !== null}
              onRun={async () => {
                if (
                  await confirm({
                    title: "Regenerate EVERY player avatar with AI?",
                    description:
                      "Deletes every avatar (Template + default.png kept) and AI-generates the whole league from scratch — slow and bills per image. 'Fill missing' is usually what you want.",
                    confirmLabel: "Regenerate all",
                    danger: true,
                  })
                ) {
                  setActiveAction("avatars-regen");
                  avatars.mutate({
                    tileKey: "avatars-regen",
                    initial: true,
                    engine: "ai",
                  });
                }
              }}
            />
            <ActionTile
              icon={<UserSquare2 className="h-5 w-5" />}
              title="Simple avatars (templates)"
              description="Free + instant: recolors bundled face templates to team colors. Faces repeat by ethnicity. Fills players missing an avatar."
              pending={activeAction === "avatars-template"}
              progress={progress["avatars-template"]}
              result={results["avatars-template"]}
              disabled={!isAdmin || activeAction !== null}
              onRun={() => {
                setActiveAction("avatars-template");
                avatars.mutate({
                  tileKey: "avatars-template",
                  initial: false,
                  engine: "template",
                });
              }}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Exports</CardTitle>
              <CardDescription>
                One-click report + almanac bundles for offline use.
              </CardDescription>
            </div>
            <Badge tone="amber">
              <FileDown className="h-3 w-3" /> Admin
            </Badge>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <ActionTile
              icon={<FileDown className="h-5 w-5" />}
              title="Export Reports (HTML)"
              description="Browsable HTML bundle with summary."
              pending={reportsHtml.isPending}
              result={results["reports-html"]}
              disabled={!isAdmin}
              onRun={() => reportsHtml.mutate()}
            />
            <ActionTile
              icon={<FileSpreadsheet className="h-5 w-5" />}
              title="Export Reports (CSV)"
              description="Flat CSV exports for spreadsheets."
              pending={reportsCsv.isPending}
              result={results["reports-csv"]}
              disabled={!isAdmin}
              onRun={() => reportsCsv.mutate()}
            />
            <ActionTile
              icon={<Trophy className="h-5 w-5" />}
              title="Export Almanac"
              description="Historical multi-page league almanac."
              pending={almanac.isPending}
              result={results["almanac"]}
              disabled={!isAdmin}
              onRun={() => almanac.mutate()}
            />
          </CardContent>
        </Card>

      </div>
      {confirmDialog}
    </AppShell>
  );
}

function ActionTile({
  icon,
  title,
  description,
  pending,
  progress,
  result,
  disabled,
  onRun,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  pending: boolean;
  progress?: ActionProgress;
  result: ActionResult | undefined;
  disabled?: boolean;
  onRun: () => void;
}) {
  const showBar = pending && progress && progress.total > 0;
  const pct = showBar
    ? Math.min(100, Math.round((progress.done / progress.total) * 100))
    : 0;
  return (
    <div className="flex items-start gap-3 rounded-xl border border-border bg-surfaceAlt/40 p-3">
      <div className="rounded-lg border border-border bg-surface p-2 text-amber">
        {icon}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold">{title}</div>
        <div className="mt-1 text-xs text-muted">{description}</div>
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={onRun}
          disabled={disabled || pending}
          title={disabled ? "Admin only" : undefined}
        >
          {pending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Play className="h-3 w-3" />
          )}
          Run
        </Button>
        {pending && (
          <div className="mt-2">
            <div className="h-2 w-full overflow-hidden rounded-full border border-border bg-surface">
              <div
                className="h-full bg-amber transition-[width] duration-150 ease-out"
                style={{ width: showBar ? `${pct}%` : "25%" }}
              />
            </div>
            <div className="mt-1 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted">
              <span>
                {showBar
                  ? `${progress.done} / ${progress.total}`
                  : progress?.phase || "Starting…"}
              </span>
              {showBar && <span>{pct}%</span>}
            </div>
          </div>
        )}
        {result && (
          <div
            className={
              result.ok
                ? "mt-2 flex items-start gap-1 text-[11px] text-success"
                : "mt-2 flex items-start gap-1 text-[11px] text-danger"
            }
          >
            {result.ok ? (
              <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0" />
            ) : (
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            )}
            {result.ok ? (
              <span className="truncate" title={result.message}>
                {result.message}
              </span>
            ) : (
              // Errors can be multi-line tracebacks; render them full
              // width with a max height so long stacks are scrollable
              // rather than truncated to a single line.
              <pre className="max-h-40 flex-1 overflow-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-tight">
                {result.message}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
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
            Live status of the Python FastAPI sidecar.
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

/**
 * Shows whether the detailed AI renderer (OpenAI gpt-image-1) is configured,
 * and lets admins paste / save an API key without editing config.ini by hand.
 * Replaces the silent-fallback behaviour that made "Generate Logos" look
 * broken when the key was missing.
 */
function AiStatusCard() {
  const status = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api.aiStatus(),
  });
  const [key, setKey] = useState("");
  const saveKey = useMutation({
    mutationFn: (k: string) => api.setOpenAiKey(k),
    onSuccess: () => {
      setKey("");
      status.refetch();
    },
  });

  const openaiOk = status.data?.openai?.ok ?? status.data?.ok ?? false;
  const vertex = status.data?.vertex;
  const vertexOk = vertex?.ok ?? false;
  const rendererOk = status.data?.renderer_ok ?? (openaiOk || vertexOk);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Palette className="h-4 w-4 text-amber" /> AI Renderer Status
          </CardTitle>
          <CardDescription>
            Detailed logos/avatars use Google Vertex AI Imagen in the cloud
            (no key needed) or OpenAI gpt-image-1 locally. If neither is ready,
            the "Detailed Logos" button falls back to the simple vector renderer.
          </CardDescription>
        </div>
        {status.isLoading ? (
          <Badge tone="neutral">
            <Loader2 className="h-3 w-3 animate-spin" /> Checking
          </Badge>
        ) : rendererOk ? (
          <Badge tone="success">
            <CheckCircle2 className="h-3 w-3" /> Ready
          </Badge>
        ) : (
          <Badge tone="warning">
            <AlertTriangle className="h-3 w-3" /> Not configured
          </Badge>
        )}
      </CardHeader>
      <CardContent>
        {/* Per-engine status */}
        <div className="mb-3 space-y-1.5">
          <div className="flex items-center gap-2 text-xs">
            {vertexOk ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-success" />
            ) : (
              <AlertTriangle className="h-3.5 w-3.5 text-muted" />
            )}
            <span className="font-medium">Vertex AI Imagen</span>
            <span className="text-muted">
              {vertex?.message ?? "Status unavailable."}
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            {openaiOk ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-success" />
            ) : (
              <AlertTriangle className="h-3.5 w-3.5 text-muted" />
            )}
            <span className="font-medium">OpenAI gpt-image-1</span>
            <span className="text-muted">
              {status.data?.openai?.message ??
                status.data?.message ??
                "Not configured."}
            </span>
          </div>
        </div>
        {!openaiOk && status.data?.openai?.message && !rendererOk && (
          <div className="mb-3 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-3 text-xs text-warning">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{status.data.openai.message}</span>
          </div>
        )}
        <form
          className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            if (key.trim()) saveKey.mutate(key.trim());
          }}
        >
          <div>
            <Label htmlFor="openai-key">OpenAI API key</Label>
            <Input
              id="openai-key"
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={openaiOk ? "Key configured — paste to replace" : "sk-..."}
              autoComplete="off"
            />
          </div>
          <div className="flex items-end">
            <Button
              type="submit"
              disabled={!key.trim() || saveKey.isPending}
            >
              {saveKey.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-1 h-4 w-4" />
              )}
              Save &amp; reload
            </Button>
          </div>
        </form>
        {saveKey.isSuccess && (
          <div className="mt-2 flex items-center gap-2 text-xs text-success">
            <CheckCircle2 className="h-3 w-3" /> Key saved. Client reloaded.
          </div>
        )}
        {saveKey.isError && (
          <div className="mt-2 flex items-center gap-2 text-xs text-danger">
            <AlertTriangle className="h-3 w-3" />
            {(saveKey.error as Error).message}
          </div>
        )}
        <div className="mt-3 text-[11px] text-muted">
          The key is written to <code>config.ini</code> under{" "}
          <code>[OpenAIkey]</code> and never echoed back by the sidecar.
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * When an owner lands on Utilities the buttons below are disabled because
 * the underlying endpoints require an admin bearer token. This card lets
 * them swap their session in place (without logging out first) by
 * re-authenticating as an admin. We remember the owner identity so they
 * can restore it with one click afterwards.
 */
function AdminElevateCard({ currentUsername }: { currentUsername: string | null }) {
  // Use ``elevateSession`` (not ``setSession``) so the current owner
  // identity is captured as ``previousSession`` and the header banner
  // can offer a one-click switch back. Owners no longer have to type
  // their password again to return to My Team.
  const elevateSession = useAuthStore((s) => s.elevateSession);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loginMut = useMutation({
    mutationFn: ({ u, p }: { u: string; p: string }) => api.login(u, p),
    onSuccess: (data) => {
      if (data.role !== "admin") {
        setError(
          `That account is signed in but its role is "${data.role}" — you need an admin account to use these tools.`,
        );
        return;
      }
      setError(null);
      elevateSession({
        token: data.token,
        username: data.username,
        role: data.role,
        teamId: data.team_id,
      });
    },
    onError: (err) =>
      setError(err instanceof Error ? err.message : String(err)),
  });

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-amber" /> Elevate to admin
          </CardTitle>
          <CardDescription>
            {currentUsername
              ? `You're signed in as "${currentUsername}". Sign in as an admin to run the utilities below.`
              : "Sign in as an admin to run the utilities below."}
          </CardDescription>
        </div>
        <Badge tone="warning">
          <Lock className="h-3 w-3" /> Owner session
        </Badge>
      </CardHeader>
      <CardContent>
        <form
          className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            if (!username || !password) return;
            loginMut.mutate({ u: username, p: password });
          }}
        >
          <div>
            <Label htmlFor="admin-username">Admin username</Label>
            <Input
              id="admin-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
            />
          </div>
          <div>
            <Label htmlFor="admin-password">Password</Label>
            <Input
              id="admin-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          <div className="flex items-end">
            <Button
              type="submit"
              disabled={!username || !password || loginMut.isPending}
            >
              {loginMut.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="mr-1 h-4 w-4" />
              )}
              Sign in as admin
            </Button>
          </div>
        </form>
        {error && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
            <AlertTriangle className="h-4 w-4" />
            {error}
          </div>
        )}
        <div className="mt-3 text-[11px] text-muted">
          Your session token is swapped in place. Click the sign-out icon in
          the header to return to the login screen, or log back in as your
          owner account when you're done.
        </div>
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

