import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
} from "@/components/ui";
import { Brand } from "@/components/layout/Brand";

export function LoginPage() {
  const setSession = useAuthStore((s) => s.setSession);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // ``?next=`` lets a previous page send the user here for auth and then
  // continue to a specific destination on success (e.g. clicking
  // "Create new league" pre-login routes to /login?next=/leagues/new).
  const nextPath = params.get("next");
  const requireRole = params.get("require"); // "admin" → reject non-admin
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // First-run detection: if the sidecar has no leagues registered, skip
  // straight into the setup wizard. The wizard handles admin-password
  // bootstrap as its first step. The picker is the user's normal entry,
  // but if someone deep-links to /login on a fresh install we still want
  // to bounce them through setup.
  useEffect(() => {
    let cancelled = false;
    api
      .leaguesFirstRun()
      .then((info) => {
        if (!cancelled && !info.has_leagues) {
          navigate("/leagues/new?first-run=1", { replace: true });
        }
      })
      .catch(() => {
        /* endpoint optional; ignore */
      });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const session = await api.login(username, password);
      if (requireRole && session.role !== requireRole) {
        setError(
          `This action requires the ${requireRole} role. Sign in with an ${requireRole} account.`,
        );
        setPending(false);
        return;
      }
      setSession({
        token: session.token,
        username: session.username,
        role: session.role,
        teamId: session.team_id,
      });
      navigate(nextPath || "/home", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Invalid username or password.");
      } else {
        setError(err instanceof Error ? err.message : "Login failed.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div
      className="relative z-10 flex h-full items-center justify-center bg-canvas"
      style={{
        backgroundImage: [
          // Subtle field-green glow rising from the bottom — reads as
          // "night game at the ballpark" without being noisy.
          "radial-gradient(circle at 50% 110%, hsl(var(--ballpark) / 0.25), transparent 60%)",
          "radial-gradient(circle at 50% 140%, hsl(var(--clay) / 0.15), transparent 55%)",
        ].join(","),
      }}
    >
      <div className="w-full max-w-md animate-fade-in space-y-6 px-6">
        <div className="flex justify-center">
          <Brand />
        </div>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>
                {requireRole === "admin"
                  ? "Sign in as admin"
                  : "Welcome back"}
              </CardTitle>
              <CardDescription>
                {requireRole === "admin"
                  ? "Creating a new league requires the admin role."
                  : "Sign in to continue to your league."}
              </CardDescription>
            </div>
          </CardHeader>

          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4" autoComplete="off">
              <div className="space-y-1.5">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoFocus
                  spellCheck={false}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>

              {error && (
                <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                  {error}
                </p>
              )}

              <Button
                type="submit"
                disabled={pending}
                size="lg"
                className="w-full"
              >
                {pending && <Loader2 className="h-4 w-4 animate-spin" />}
                {pending ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
