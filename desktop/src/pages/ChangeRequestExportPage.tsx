/**
 * Owner-side change request export — port of ui/change_request_export_dialog.py.
 *
 * Lets an owner bundle up their roster/lineup/pitching-staff/depth-chart
 * files into a ZIP that can be sent to the commissioner. Also lists their
 * previously exported requests with a cancel-export action.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Inbox,
  Loader2,
  Send,
  XCircle,
} from "lucide-react";

import { api } from "@/lib/api";
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
  Input,
  Label,
} from "@/components/ui";

const SECTION_DEFS = [
  { id: "roster" as const, label: "Roster (ACT/AAA/LOW/DL/IR)" },
  { id: "lineups" as const, label: "Lineups (vs LHP/RHP)" },
  { id: "pitching" as const, label: "Pitching staff roles" },
  { id: "depth" as const, label: "Depth chart" },
];

export function ChangeRequestExportPage() {
  const user = useAuthStore();
  const teamId = user.selectedTeamId ?? user.teamId ?? null;

  if (!teamId) {
    return (
      <AppShell title="Change Requests">
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <AlertTriangle className="h-5 w-5 text-warning" />
            <span className="text-sm">
              You need a team assignment to submit change requests.
            </span>
          </CardContent>
        </Card>
      </AppShell>
    );
  }

  return (
    <AppShell
      title="Submit Change Request"
      subtitle={`Team ${teamId} · bundle changes for commissioner approval`}
    >
      <ExportEditor teamId={teamId} />
    </AppShell>
  );
}

function ExportEditor({ teamId }: { teamId: string }) {
  const queryClient = useQueryClient();
  const authToken = useAuthStore((s) => s.token);

  const requestsQuery = useQuery({
    queryKey: ["team-change-requests", teamId],
    queryFn: () => api.teamChangeRequests(teamId),
  });

  const [ownerName, setOwnerName] = useState(teamId);
  const [note, setNote] = useState("");
  const [sections, setSections] = useState<Record<string, boolean>>({
    roster: true,
    lineups: true,
    pitching: true,
    depth: true,
  });

  const exportMut = useMutation({
    mutationFn: () =>
      api.exportTeamChangeRequest(teamId, {
        owner_name: ownerName,
        note,
        sections: {
          roster: !!sections.roster,
          lineups: !!sections.lineups,
          pitching: !!sections.pitching,
          depth: !!sections.depth,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["team-change-requests", teamId],
      });
    },
  });

  const cancelMut = useMutation({
    mutationFn: (requestId: string) =>
      api.cancelTeamChangeRequest(teamId, requestId, ownerName),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["team-change-requests", teamId],
      });
    },
  });

  async function downloadBundle(filename: string) {
    const { apiBaseUrl, launchToken } = getBridge();
    const token = authToken ?? launchToken;
    const url = api.changeRequestDownloadUrl(teamId, filename);
    const res = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!res.ok) {
      alert(`Download failed: ${res.status}`);
      return;
    }
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objUrl);
  }

  const exported = (requestsQuery.data?.requests ?? []).filter(
    (r) => String(r.status) === "exported",
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Send className="h-4 w-4 text-amber" /> New export
          </CardTitle>
          <CardDescription>
            Bundle the selected files into a ZIP. Send the ZIP to your
            commissioner — they apply it from the admin Change Requests page.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <Label htmlFor="owner">Owner name</Label>
              <Input
                id="owner"
                value={ownerName}
                onChange={(e) => setOwnerName(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="note">Note (optional)</Label>
              <Input
                id="note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Context for the commissioner…"
              />
            </div>
          </div>

          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-muted">
              Sections to include
            </div>
            {SECTION_DEFS.map((s) => (
              <label key={s.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!sections[s.id]}
                  onChange={(e) =>
                    setSections({ ...sections, [s.id]: e.target.checked })
                  }
                />
                {s.label}
              </label>
            ))}
          </div>

          <div className="flex items-center justify-end">
            <Button
              onClick={() => exportMut.mutate()}
              disabled={
                exportMut.isPending ||
                !Object.values(sections).some(Boolean)
              }
              size="sm"
            >
              {exportMut.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Send className="mr-1 h-4 w-4" />
              )}
              Export request
            </Button>
          </div>

          {exportMut.isSuccess && exportMut.data && (
            <div className="flex items-center justify-between rounded-md border border-success/40 bg-success/10 p-3 text-sm">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-success" />
                Exported {exportMut.data.filename} ({exportMut.data.file_count} files)
              </div>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => downloadBundle(exportMut.data.filename)}
              >
                <Download className="mr-1 h-4 w-4" /> Download ZIP
              </Button>
            </div>
          )}

          {exportMut.isError && (
            <div className="flex items-center gap-2 rounded-md border border-danger/40 bg-danger/10 p-3 text-sm">
              <AlertTriangle className="h-4 w-4 text-danger" />
              {(exportMut.error as Error).message}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Inbox className="h-4 w-4 text-amber" /> Previously exported
          </CardTitle>
          <CardDescription>
            Pending commissioner review. Export a cancel bundle to withdraw a
            request before it's applied.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {requestsQuery.isLoading && (
            <div className="flex items-center gap-2 py-3 text-sm text-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </div>
          )}
          {exported.length === 0 && !requestsQuery.isLoading && (
            <div className="py-3 text-sm italic text-muted">
              No exported requests.
            </div>
          )}
          {exported.map((req) => {
            const reqId = String(req.request_id ?? "");
            const summary = String(req.summary ?? "");
            const created = String(req.created_at ?? "");
            return (
              <div
                key={reqId}
                className="flex items-center justify-between rounded-md border border-border bg-surface px-3 py-2 text-sm"
              >
                <div>
                  <div className="font-semibold">{summary || reqId}</div>
                  <div className="text-[11px] text-muted">
                    {reqId} · {created}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone="amber">exported</Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => cancelMut.mutate(reqId)}
                    disabled={cancelMut.isPending}
                  >
                    <XCircle className="mr-1 h-4 w-4" />
                    Export cancel
                  </Button>
                </div>
              </div>
            );
          })}
          {cancelMut.isSuccess && cancelMut.data && (
            <div className="flex items-center justify-between rounded-md border border-success/40 bg-success/10 p-3 text-sm">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-success" />
                Cancel exported: {cancelMut.data.filename}
              </div>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => downloadBundle(cancelMut.data.filename)}
              >
                <Download className="mr-1 h-4 w-4" /> Download ZIP
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
