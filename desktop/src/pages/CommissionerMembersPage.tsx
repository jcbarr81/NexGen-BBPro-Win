import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Copy,
  Loader2,
  Mail,
  Send,
  Ticket,
  Trash2,
  XCircle,
} from "lucide-react";

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
  Input,
} from "@/components/ui";
import { toast } from "@/lib/toast-store";

function parseEmails(raw: string): string[] {
  return raw
    .split(/[,\s]+/)
    .map((x) => x.trim())
    .filter(Boolean);
}

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

type EmailResult = {
  email: string;
  team_id: string;
  code: string | null;
  sent: boolean;
  error: string | null;
};

function EmailInvitesCard({
  teams,
}: {
  teams: Array<{ team_id: string; name: string; city: string }>;
}) {
  const qc = useQueryClient();
  const statusQ = useQuery({
    queryKey: ["invite-email-status"],
    queryFn: () => api.inviteEmailStatus(),
  });
  const recipientsQ = useQuery({
    queryKey: ["invite-recipients"],
    queryFn: () => api.inviteRecipients(),
    enabled: statusQ.data?.configured === true,
  });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [extra, setExtra] = useState("");
  const [team, setTeam] = useState("");
  const [results, setResults] = useState<EmailResult[] | null>(null);

  const send = useMutation({
    mutationFn: () => {
      const emails = Array.from(
        new Set([...selected, ...parseEmails(extra)]),
      );
      return api.emailInvites({
        team_id: team || undefined,
        recipients: emails,
      });
    },
    onSuccess: (data) => {
      setResults(data.results);
      qc.invalidateQueries({ queryKey: ["invites"] });
      if (data.sent_count > 0) {
        toast.success(
          `Sent ${data.sent_count} invite${data.sent_count === 1 ? "" : "s"}`,
        );
      }
      if (data.failed_count > 0) {
        toast.error(
          `${data.failed_count} invite${data.failed_count === 1 ? "" : "s"} failed`,
        );
      }
      setSelected(new Set());
      setExtra("");
    },
    onError: (err) =>
      toast.error("Couldn't send invites", {
        description: err instanceof Error ? err.message : undefined,
      }),
  });

  const totalChosen = selected.size + parseEmails(extra).length;

  // Not configured yet → show the one-time setup hint instead of a dead form.
  if (statusQ.data && !statusQ.data.configured) {
    return (
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <Mail className="h-4 w-4" /> Email invites
            </CardTitle>
            <CardDescription>
              Email invite codes straight to owners — once email is set up.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-start gap-2 rounded-md border border-amber/40 bg-amber/10 px-3 py-2 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
            <div className="space-y-1">
              <p className="font-semibold">Email isn't configured yet.</p>
              <p className="text-muted">
                Set <span className="font-mono">SENDGRID_API_KEY</span> and{" "}
                <span className="font-mono">INVITE_EMAIL_FROM</span> (a verified
                SendGrid sender) on the server, then reload. Until then you can
                still generate a code above and share it manually.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    );
  }

  const recipients = recipientsQ.data?.recipients ?? [];

  function toggle(email: string) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Mail className="h-4 w-4" /> Email invites
          </CardTitle>
          <CardDescription>
            Pick registered users (or type any email), choose a team, and each
            gets their own code by email.
            {statusQ.data?.from_address ? (
              <>
                {" "}
                Sent from{" "}
                <span className="font-mono">{statusQ.data.from_address}</span>.
              </>
            ) : null}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Registered users */}
        {recipientsQ.isLoading ? (
          <p className="text-sm text-muted">Loading users…</p>
        ) : recipients.length === 0 ? (
          <p className="text-sm text-muted">
            No registered users to list yet — use the email box below.
          </p>
        ) : (
          <div className="max-h-56 space-y-1 overflow-auto rounded-md border border-border p-2">
            {recipients.map((r) => (
              <label
                key={r.uid || r.email}
                className={
                  "flex items-center justify-between gap-2 rounded px-2 py-1.5 text-sm " +
                  (r.in_league
                    ? "opacity-50"
                    : "cursor-pointer hover:bg-surfaceAlt/60")
                }
              >
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    disabled={r.in_league}
                    checked={selected.has(r.email)}
                    onChange={() => toggle(r.email)}
                  />
                  <div>
                    <div className="font-semibold">{r.handle}</div>
                    <div className="text-xs text-muted">{r.email}</div>
                  </div>
                </div>
                {r.in_league && (
                  <Badge tone="neutral">
                    in league{r.team_id ? ` · ${r.team_id}` : ""}
                  </Badge>
                )}
              </label>
            ))}
          </div>
        )}

        {/* Free-text emails */}
        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase tracking-wider text-muted">
            Or invite by email
          </label>
          <Input
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
            placeholder="friend@example.com, another@example.com"
          />
        </div>

        {/* Team + send */}
        <div className="flex flex-wrap items-center gap-2">
          <TeamSelect
            value={team}
            onChange={setTeam}
            teams={teams}
            placeholder="Any team (assign later)"
          />
          <Button
            onClick={() => send.mutate()}
            disabled={send.isPending || totalChosen === 0}
          >
            {send.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            Send {totalChosen > 0 ? `${totalChosen} ` : ""}invite
            {totalChosen === 1 ? "" : "s"}
          </Button>
        </div>

        {/* Results */}
        {results && results.length > 0 && (
          <div className="space-y-1 rounded-md border border-border p-2 text-sm">
            {results.map((r) => (
              <div key={r.email} className="flex items-center gap-2">
                {r.sent ? (
                  <CheckCircle2 className="h-4 w-4 text-success" />
                ) : (
                  <XCircle className="h-4 w-4 text-danger" />
                )}
                <span className="font-semibold">{r.email}</span>
                {r.sent ? (
                  <span className="text-muted">
                    sent{r.team_id ? ` · ${r.team_id}` : ""}
                    {r.code ? ` · ${r.code}` : ""}
                  </span>
                ) : (
                  <span className="text-danger">{r.error}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
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

        {/* Email invites */}
        <EmailInvitesCard teams={teams} />

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
