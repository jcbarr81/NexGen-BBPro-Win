import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, Loader2, Ticket, Trash2 } from "lucide-react";

import { api } from "@/lib/api";
import { useTeams } from "@/lib/use-teams";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { toast } from "@/lib/toast-store";

function TeamSelect({
  value,
  onChange,
  teams,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  teams: Array<{ team_id: string; name: string; city: string }>;
  placeholder: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
    >
      <option value="">{placeholder}</option>
      {teams.map((t) => (
        <option key={t.team_id} value={t.team_id}>
          {t.city} {t.name} ({t.team_id})
        </option>
      ))}
    </select>
  );
}

export function CommissionerMembersPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const teamsQ = useTeams();
  const invitesQ = useQuery({ queryKey: ["invites"], queryFn: () => api.listInvites() });
  const requestsQ = useQuery({
    queryKey: ["join-requests"],
    queryFn: () => api.listJoinRequests(),
  });
  const teams = teamsQ.data ?? [];
  const invites = invitesQ.data?.invites ?? [];
  const requests = requestsQ.data?.requests ?? [];

  const [inviteTeam, setInviteTeam] = useState("");
  const [approveTeam, setApproveTeam] = useState<Record<string, string>>({});

  const genInvite = useMutation({
    mutationFn: () => api.generateInvite(inviteTeam || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["invites"] });
      toast.success("Invite created");
    },
  });
  const revoke = useMutation({
    mutationFn: (code: string) => api.revokeInvite(code),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invites"] }),
  });
  const approve = useMutation({
    mutationFn: (v: { id: string; team: string }) =>
      api.approveJoinRequest(v.id, v.team),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["join-requests"] });
      toast.success("Owner approved");
    },
  });
  const deny = useMutation({
    mutationFn: (id: string) => api.denyJoinRequest(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["join-requests"] }),
  });

  function copy(code: string) {
    navigator.clipboard?.writeText(code);
    toast.success("Code copied", { description: code });
  }

  return (
    <div className="h-full overflow-auto bg-canvas">
      <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        <div className="flex items-center justify-between">
          <h1 className="font-display text-2xl">Members &amp; Invites</h1>
          <Button variant="ghost" size="sm" onClick={() => navigate("/home")}>
            <ArrowLeft className="h-4 w-4" /> Back to league
          </Button>
        </div>

        {/* Invites */}
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Invite codes</CardTitle>
              <CardDescription>
                Share a code so owners can join instantly. Optionally tie it to a team.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2">
              <TeamSelect
                value={inviteTeam}
                onChange={setInviteTeam}
                teams={teams}
                placeholder="Any team (assign later)"
              />
              <Button onClick={() => genInvite.mutate()} disabled={genInvite.isPending}>
                {genInvite.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Ticket className="h-4 w-4" />
                )}
                Generate invite
              </Button>
            </div>
            {invites.filter((i) => i.status === "open").length === 0 ? (
              <p className="text-sm text-muted">No open invites.</p>
            ) : (
              <div className="space-y-2">
                {invites
                  .filter((i) => i.status === "open")
                  .map((i) => (
                    <div
                      key={i.code}
                      className="flex items-center justify-between rounded-md border border-border px-3 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm tracking-widest">{i.code}</span>
                        {i.team_id && <Badge tone="amber">{i.team_id}</Badge>}
                      </div>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" onClick={() => copy(i.code)}>
                          <Copy className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => revoke.mutate(i.code)}
                        >
                          <Trash2 className="h-4 w-4 text-danger" />
                        </Button>
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Join requests */}
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Join requests</CardTitle>
              <CardDescription>
                Owners who asked to join your public league. Assign a team to approve.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {requests.length === 0 ? (
              <p className="text-sm text-muted">No pending requests.</p>
            ) : (
              <div className="space-y-2">
                {requests.map((r) => (
                  <div
                    key={r.request_id}
                    className="flex items-center justify-between rounded-md border border-border px-3 py-2"
                  >
                    <div>
                      <div className="text-sm font-semibold">{r.handle}</div>
                      {r.note && <div className="text-xs text-muted">"{r.note}"</div>}
                    </div>
                    <div className="flex items-center gap-2">
                      <TeamSelect
                        value={approveTeam[r.request_id] ?? ""}
                        onChange={(v) =>
                          setApproveTeam((s) => ({ ...s, [r.request_id]: v }))
                        }
                        teams={teams}
                        placeholder="Pick a team"
                      />
                      <Button
                        size="sm"
                        disabled={!approveTeam[r.request_id] || approve.isPending}
                        onClick={() =>
                          approve.mutate({
                            id: r.request_id,
                            team: approveTeam[r.request_id],
                          })
                        }
                      >
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => deny.mutate(r.request_id)}
                      >
                        Deny
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
