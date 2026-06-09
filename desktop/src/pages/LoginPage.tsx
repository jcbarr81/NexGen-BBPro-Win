import { FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { ApiError, api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { isCloud } from "@/lib/cloud-auth";
import { currentUser, resetPassword, signInEmail, signInGoogle } from "@/lib/firebase";
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
import { toast } from "@/lib/toast-store";
import type { User } from "firebase/auth";

const FIREBASE_ERRORS: Record<string, string> = {
  "auth/invalid-credential": "Wrong email or password.",
  "auth/user-not-found": "No account with that email.",
  "auth/wrong-password": "Wrong email or password.",
  "auth/invalid-email": "That email address looks invalid.",
  "auth/too-many-requests": "Too many attempts — try again in a bit.",
  "auth/popup-closed-by-user": "Google sign-in was cancelled.",
  "auth/popup-blocked": "Your browser blocked the Google popup — allow popups and retry.",
};

function humanize(err: unknown): string {
  const code = (err as { code?: string })?.code;
  return (
    (code && FIREBASE_ERRORS[code]) ||
    (err instanceof Error ? err.message : "Sign-in failed.")
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="relative z-10 flex h-full items-center justify-center bg-canvas"
      style={{
        backgroundImage: [
          "radial-gradient(circle at 50% 110%, hsl(var(--ballpark) / 0.25), transparent 60%)",
          "radial-gradient(circle at 50% 140%, hsl(var(--clay) / 0.15), transparent 55%)",
        ].join(","),
      }}
    >
      <div className="w-full max-w-md animate-fade-in space-y-6 px-6">
        <div className="flex justify-center">
          <Brand />
        </div>
        {children}
      </div>
    </div>
  );
}

function CloudLogin() {
  const navigate = useNavigate();
  const setFirebaseAccount = useAuthStore((s) => s.setFirebaseAccount);
  const firebaseReady = useAuthStore((s) => s.firebaseReady);
  const uid = useAuthStore((s) => s.uid);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const forwarded = useRef(false);

  // If we land here already signed in — e.g. returning from a full-page Google
  // redirect — forward the user onward instead of showing the login form again.
  useEffect(() => {
    if (forwarded.current || !firebaseReady || !uid) return;
    const user = currentUser();
    if (!user) return;
    forwarded.current = true;
    setPending(true);
    void routeAfter(user);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firebaseReady, uid]);

  async function routeAfter(user: User) {
    setFirebaseAccount({ uid: user.uid, email: user.email });
    try {
      const me = await api.accountMe();
      if (me.account?.package) {
        setFirebaseAccount({
          uid: user.uid,
          email: user.email,
          handle: me.account.handle ?? null,
          pkg: me.account.package as "commissioner" | "owner",
        });
        navigate("/my-leagues", { replace: true });
        return;
      }
    } catch {
      /* no profile yet */
    }
    navigate("/register", { replace: true });
  }

  async function withEmail(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await routeAfter(await signInEmail(email.trim(), password));
    } catch (err) {
      setError(humanize(err));
      setPending(false);
    }
  }

  async function withGoogle() {
    setError(null);
    setPending(true);
    try {
      await routeAfter(await signInGoogle());
    } catch (err) {
      setError(humanize(err));
      setPending(false);
    }
  }

  async function forgot() {
    if (!email.trim()) {
      setError("Enter your email above first, then click Forgot password.");
      return;
    }
    try {
      await resetPassword(email.trim());
      toast.success("Password reset sent", {
        description: `Check ${email.trim()} for a reset link.`,
      });
    } catch (err) {
      setError(humanize(err));
    }
  }

  // Returning from a Google redirect (or already authed): show a spinner while
  // routeAfter() decides where to send the user, instead of the login form.
  if (forwarded.current) {
    return (
      <Shell>
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-muted">
            <Loader2 className="h-6 w-6 animate-spin text-amber" />
            <span className="text-sm">Signing you in…</span>
          </CardContent>
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Welcome back</CardTitle>
            <CardDescription>Sign in to your account.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={withEmail} className="space-y-4" autoComplete="off">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
                <button
                  type="button"
                  className="text-xs text-muted hover:text-amber"
                  onClick={forgot}
                >
                  Forgot password?
                </button>
              </div>
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
            <Button type="submit" disabled={pending} size="lg" className="w-full">
              {pending && <Loader2 className="h-4 w-4 animate-spin" />}
              Sign in
            </Button>
            <div className="flex items-center gap-3 text-xs text-muted">
              <div className="h-px flex-1 bg-border" /> or{" "}
              <div className="h-px flex-1 bg-border" />
            </div>
            <Button
              type="button"
              variant="outline"
              size="lg"
              className="w-full"
              disabled={pending}
              onClick={withGoogle}
            >
              Continue with Google
            </Button>
            <p className="text-center text-sm text-muted">
              New here?{" "}
              <button
                type="button"
                className="text-amber hover:underline"
                onClick={() => navigate("/register")}
              >
                Create an account
              </button>
            </p>
          </form>
        </CardContent>
      </Card>
    </Shell>
  );
}

function LegacyLogin() {
  const setSession = useAuthStore((s) => s.setSession);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const nextPath = params.get("next");
  const requireRole = params.get("require");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .leaguesFirstRun()
      .then((info) => {
        if (!cancelled && !info.has_leagues) {
          navigate("/leagues/new?first-run=1", { replace: true });
        }
      })
      .catch(() => {});
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
        setError(`This action requires the ${requireRole} role.`);
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
    <Shell>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>
              {requireRole === "admin" ? "Sign in as admin" : "Welcome back"}
            </CardTitle>
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
            <Button type="submit" disabled={pending} size="lg" className="w-full">
              {pending && <Loader2 className="h-4 w-4 animate-spin" />}
              {pending ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </Shell>
  );
}

export function LoginPage() {
  return isCloud() ? <CloudLogin /> : <LegacyLogin />;
}
