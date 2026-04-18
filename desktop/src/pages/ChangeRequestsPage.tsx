/**
 * Phase 4 port of ui/change_requests_window.py.
 *
 * Admin queue for owner-submitted change requests (bundle imports).
 * Shows every pending/resolved request with status pills and per-row
 * approve / reject / re-queue actions.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Inbox,
  Loader2,
  RefreshCw,
  RotateCcw,
  XCircle,
} from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
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

const STATUS_FILTERS = [
  { key: "", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "applied", label: "Applied" },
];

export function ChangeRequestsPage() {
  const role = useAuthStore((s) => s.role);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");

  const requests = useQuery({
    queryKey: ["change-requests", filter],
    queryFn: () => api.changeRequests(filter || undefined),
    enabled: role === "admin",
  });

  const mutation = useMutation({
    mutationFn: (payload: {
      request_id: string;
      status: string;
      note?: string;
    }) => api.updateChangeRequest(payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["change-requests"] }),
  });

  if (role !== "admin") return <Navigate to="/home" replace />;

  return (
    <AppShell
      title="Change Requests"
      subtitle="Owner-submitted change bundles awaiting commissioner action"
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-border bg-surfaceAlt p-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.key || "all"}
              type="button"
              onClick={() => setFilter(f.key)}
              className={cn(
                "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                filter === f.key
                  ? "bg-amber text-espresso"
                  : "text-muted hover:bg-surface hover:text-ink",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {requests.data && (
            <span className="text-xs text-muted">
              {requests.data.count} requests
            </span>
          )}
          <Button
            variant="ghost"
            size="icon"
            aria-label="Refresh"
            onClick={() => requests.refetch()}
          >
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {mutation.isError && (
        <div className="mb-4 flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <AlertTriangle className="h-4 w-4" />
          {(mutation.error as Error).message}
        </div>
      )}

      {requests.isLoading ? (
        <LoadingCard />
      ) : requests.isError ? (
        <ErrorCard message={(requests.error as Error).message} />
      ) : !requests.data || requests.data.count === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <Inbox className="h-10 w-10 text-amber" />
            <h2 className="font-display text-xl">Inbox empty</h2>
            <p className="max-w-sm text-sm text-muted">
              No change requests match this filter.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {requests.data.requests.map((row, i) => (
            <RequestCard
              key={String(row.request_id ?? i)}
              row={row}
              pending={mutation.isPending}
              onAction={(status) =>
                mutation.mutate({
                  request_id: String(row.request_id),
                  status,
                })
              }
            />
          ))}
        </div>
      )}
    </AppShell>
  );
}

function RequestCard({
  row,
  pending,
  onAction,
}: {
  row: Record<string, unknown>;
  pending: boolean;
  onAction: (status: string) => void;
}) {
  const status = String(row.status ?? "pending");
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="text-base">
            {String(row.summary ?? row.request_id ?? "Untitled")}
          </CardTitle>
          <CardDescription>
            {row.team_id ? `${row.team_id} · ` : ""}
            {row.owner_name ? `${row.owner_name} · ` : ""}
            {row.created_at ? String(row.created_at) : ""}
          </CardDescription>
        </div>
        <Badge tone={statusTone(status)}>{status}</Badge>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-3">
        <div className="text-xs text-muted">
          {String(row.note ?? "")}
        </div>
        <div className="flex items-center gap-1">
          {status !== "approved" && status !== "applied" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onAction("approved")}
              disabled={pending}
            >
              <CheckCircle2 className="h-3 w-3 text-success" /> Approve
            </Button>
          )}
          {status !== "rejected" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onAction("rejected")}
              disabled={pending}
            >
              <XCircle className="h-3 w-3 text-danger" /> Reject
            </Button>
          )}
          {status !== "pending" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onAction("pending")}
              disabled={pending}
            >
              <RotateCcw className="h-3 w-3" /> Re-queue
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function statusTone(status: string): "amber" | "success" | "danger" | "neutral" {
  const s = status.toLowerCase();
  if (s === "pending") return "amber";
  if (s === "approved" || s === "applied") return "success";
  if (s === "rejected") return "danger";
  return "neutral";
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-10">
        <Loader2 className="h-5 w-5 animate-spin text-amber" />
        <span className="text-sm text-muted">Loading change requests…</span>
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
