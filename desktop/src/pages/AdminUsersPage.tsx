/**
 * Phase 4 port of ui/admin_dashboard/pages/users.py.
 *
 * Admin-only user management: list every user, search by username/team, add
 * new accounts, edit existing ones (password reset, role swap, team
 * reassignment). Non-admin users are bounced back to the dashboard.
 */

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import {
  AlertTriangle,
  Loader2,
  Pencil,
  Search,
  ShieldCheck,
  UserPlus,
} from "lucide-react";

import {
  ApiError,
  api,
  type AdminUser,
  type EditAdminUser,
  type Team,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useTeams } from "@/lib/use-teams";
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";

export function AdminUsersPage() {
  const role = useAuthStore((s) => s.role);
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [creatingOpen, setCreatingOpen] = useState(false);

  const users = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api.adminListUsers(),
    enabled: role === "admin",
  });
  const teams = useTeams({ enabled: role === "admin" });

  // Set of team_ids already taken by an owner -- used to mark options
  // in the dropdown so the admin doesn't pick a conflict by mistake.
  const ownedTeamIds = useMemo(() => {
    const set = new Set<string>();
    for (const u of users.data?.users ?? []) {
      if (u.role === "owner" && u.team_id) set.add(u.team_id);
    }
    return set;
  }, [users.data]);

  const filtered = useMemo(() => {
    if (!users.data) return [];
    const needle = search.trim().toLowerCase();
    if (!needle) return users.data.users;
    return users.data.users.filter(
      (u) =>
        (u.display_name || u.username).toLowerCase().includes(needle) ||
        u.username.toLowerCase().includes(needle) ||
        (u.team_id || "").toLowerCase().includes(needle),
    );
  }, [users.data, search]);

  if (role !== "admin") {
    return <Navigate to="/home" replace />;
  }

  return (
    <AppShell
      title="Users"
      subtitle="Manage who can sign in and what team they own."
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <Input
            className="pl-9"
            placeholder="Search by name or team…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Button onClick={() => setCreatingOpen(true)}>
          <UserPlus className="h-4 w-4" />
          Add user
        </Button>
      </div>

      {users.isLoading ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10">
            <Loader2 className="h-5 w-5 animate-spin text-amber" />
            <span className="text-sm text-muted">Loading users…</span>
          </CardContent>
        </Card>
      ) : users.isError ? (
        <Card>
          <CardContent className="flex items-center gap-3 py-10 text-danger">
            <AlertTriangle className="h-5 w-5" />
            <span className="text-sm">{(users.error as Error).message}</span>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Accounts</CardTitle>
              <CardDescription>
                {filtered.length} of {users.data?.count ?? 0}
              </CardDescription>
            </div>
            <Badge tone="amber">
              <ShieldCheck className="h-3 w-3" /> Admin view
            </Badge>
          </CardHeader>
          <CardContent className="p-0">
            {filtered.length === 0 ? (
              <div className="px-6 py-8 text-sm text-muted">
                No users match that search.
              </div>
            ) : (
              <div className="overflow-x-auto"><table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/60 text-[11px] uppercase tracking-wider text-muted">
                    <th className="px-6 py-2 text-left font-semibold">Name</th>
                    <th className="px-3 py-2 text-left font-semibold">Role</th>
                    <th className="px-3 py-2 text-left font-semibold">Team</th>
                    <th className="px-6 py-2 text-right font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((user) => (
                    <tr
                      key={user.username}
                      className="border-b border-border/40 last:border-b-0 hover:bg-surfaceAlt/40"
                    >
                      <td className="px-6 py-2">
                        <div className="font-semibold">
                          {user.display_name || user.username}
                        </div>
                        {user.display_name &&
                          user.display_name !== user.username && (
                            <div
                              className="max-w-[18rem] truncate font-mono text-[10px] text-muted"
                              title={user.username}
                            >
                              {user.username}
                            </div>
                          )}
                      </td>
                      <td className="px-3 py-2">
                        <Badge
                          tone={user.role === "admin" ? "amber" : "neutral"}
                        >
                          {user.role}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-xs font-mono text-muted">
                        {user.team_id || "—"}
                      </td>
                      <td className="px-6 py-2 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setEditing(user)}
                        >
                          <Pencil className="h-3 w-3" /> Edit
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            )}
          </CardContent>
        </Card>
      )}

      <CreateUserDialog
        open={creatingOpen}
        onOpenChange={setCreatingOpen}
        teams={teams.data ?? []}
        ownedTeamIds={ownedTeamIds}
        onCreated={() => queryClient.invalidateQueries({ queryKey: ["admin-users"] })}
      />
      <EditUserDialog
        user={editing}
        teams={teams.data ?? []}
        ownedTeamIds={ownedTeamIds}
        onOpenChange={(open) => !open && setEditing(null)}
        onSaved={() => {
          setEditing(null);
          queryClient.invalidateQueries({ queryKey: ["admin-users"] });
        }}
      />
    </AppShell>
  );
}

// -------------------------------------------------------------------------

function CreateUserDialog({
  open,
  onOpenChange,
  onCreated,
  teams,
  ownedTeamIds,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
  teams: Team[];
  ownedTeamIds: Set<string>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "owner">("owner");
  const [teamId, setTeamId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const usernameRef = useRef<HTMLInputElement>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.adminCreateUser({ username, password, role, team_id: teamId }),
    onSuccess: () => {
      onCreated();
      setUsername("");
      setPassword("");
      setRole("owner");
      setTeamId("");
      setError(null);
      onOpenChange(false);
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : "Failed to create user.");
    },
  });

  function handleSubmit(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    setError(null);
    mutation.mutate();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          usernameRef.current?.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>Add user</DialogTitle>
          <DialogDescription>
            Create a new account. Owners should be assigned to exactly one team.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="new-username">Username</Label>
            <Input
              id="new-username"
              ref={usernameRef}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-password">Password</Label>
            <Input
              id="new-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Role</Label>
              <div className="flex rounded-lg border border-border bg-surfaceAlt p-1">
                {(["owner", "admin"] as const).map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setRole(r)}
                    className={cn(
                      "flex-1 rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                      role === r
                        ? "bg-amber text-espresso"
                        : "text-muted hover:bg-surface hover:text-ink",
                    )}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-team">Team</Label>
              <TeamSelect
                id="new-team"
                value={teamId}
                onChange={setTeamId}
                teams={teams}
                ownedTeamIds={ownedTeamIds}
                placeholder={
                  role === "owner" ? "Select a team…" : "Optional"
                }
              />
            </div>
          </div>

          {error && (
            <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="ghost"
              type="button"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Create
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// -------------------------------------------------------------------------

function EditUserDialog({
  user,
  onOpenChange,
  onSaved,
  teams,
  ownedTeamIds,
}: {
  user: AdminUser | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
  teams: Team[];
  ownedTeamIds: Set<string>;
}) {
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "owner">("owner");
  const [teamId, setTeamId] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Sync form when the target user changes.
  useEffect(() => {
    setPassword("");
    setRole(user?.role === "admin" ? "admin" : "owner");
    setTeamId(user?.team_id ?? "");
    setError(null);
  }, [user?.username, user?.role, user?.team_id]);

  const mutation = useMutation({
    mutationFn: () => {
      if (!user) return Promise.reject(new Error("No user"));
      const body: EditAdminUser = {};
      if (password) body.password = password;
      if (role !== user.role) body.role = role;
      if (teamId !== user.team_id) body.team_id = teamId;
      return api.adminEditUser(user.username, body);
    },
    onSuccess: () => onSaved(),
    onError: (err) => {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Update failed.");
      }
    },
  });

  return (
    <Dialog open={!!user} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit {user?.username}</DialogTitle>
          <DialogDescription>
            Leave password empty to keep the current one.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            mutation.mutate();
          }}
          className="space-y-4"
        >
          <div className="space-y-1.5">
            <Label htmlFor="edit-password">New password</Label>
            <Input
              id="edit-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Leave blank to keep current"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Role</Label>
              <div className="flex rounded-lg border border-border bg-surfaceAlt p-1">
                {(["owner", "admin"] as const).map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setRole(r)}
                    className={cn(
                      "flex-1 rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition",
                      role === r
                        ? "bg-amber text-espresso"
                        : "text-muted hover:bg-surface hover:text-ink",
                    )}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-team">Team</Label>
              <TeamSelect
                id="edit-team"
                value={teamId}
                onChange={setTeamId}
                teams={teams}
                ownedTeamIds={ownedTeamIds}
                currentOwnerTeamId={user?.team_id ?? ""}
                placeholder={role === "owner" ? "Select a team…" : "Optional"}
              />
            </div>
          </div>

          {error && (
            <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="ghost"
              type="button"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={mutation.isPending}>
              {mutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// -------------------------------------------------------------------------

/**
 * Team picker that lists every team in the league and labels ones that are
 * already owned, so the admin doesn't accidentally pick a conflict. The
 * `currentOwnerTeamId` prop keeps the user's existing team picklable when
 * editing (it's "owned" by them, not by someone else).
 */
function TeamSelect({
  id,
  value,
  onChange,
  teams,
  ownedTeamIds,
  currentOwnerTeamId = "",
  placeholder,
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  teams: Team[];
  ownedTeamIds: Set<string>;
  currentOwnerTeamId?: string;
  placeholder?: string;
}) {
  const sorted = [...teams].sort((a, b) =>
    `${a.city} ${a.name}`.localeCompare(`${b.city} ${b.name}`),
  );
  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-10 w-full rounded-lg border border-border bg-canvas/60 px-3 text-sm text-ink focus:border-amber focus:outline-none focus:ring-2 focus:ring-amber/40"
    >
      <option value="">{placeholder ?? "— select —"}</option>
      {sorted.map((t) => {
        const owned =
          ownedTeamIds.has(t.team_id) && t.team_id !== currentOwnerTeamId;
        return (
          <option key={t.team_id} value={t.team_id}>
            {t.city} {t.name} ({t.abbreviation})
            {owned ? " — owned" : ""}
          </option>
        );
      })}
    </select>
  );
}

