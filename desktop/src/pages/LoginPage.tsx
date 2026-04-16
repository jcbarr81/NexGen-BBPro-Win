import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const session = await api.login(username, password);
      setSession({
        token: session.token,
        username: session.username,
        role: session.role,
        teamId: session.team_id,
      });
      navigate("/select-league", { replace: true });
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
    <div className="relative z-10 flex h-full items-center justify-center bg-canvas">
      <div className="w-full max-w-md animate-fade-in space-y-6 px-6">
        <div className="flex justify-center">
          <Brand />
        </div>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Welcome back</CardTitle>
              <CardDescription>Sign in to continue to your league.</CardDescription>
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
