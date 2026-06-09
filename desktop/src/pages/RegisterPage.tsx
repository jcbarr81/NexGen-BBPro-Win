import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { currentUser, signInGoogle, signUpEmail } from "@/lib/firebase";
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
import { cn } from "@/lib/cn";

const FIREBASE_ERRORS: Record<string, string> = {
  "auth/email-already-in-use": "That email is already registered — try signing in instead.",
  "auth/invalid-email": "That email address looks invalid.",
  "auth/weak-password": "Password must be at least 6 characters.",
  "auth/popup-closed-by-user": "Google sign-in was cancelled.",
  "auth/popup-blocked": "Your browser blocked the Google popup — allow popups and retry.",
  "auth/cancelled-popup-request": "Google sign-in was cancelled.",
};

function humanize(err: unknown): string {
  const code = (err as { code?: string })?.code;
  return (
    (code && FIREBASE_ERRORS[code]) ||
    (err instanceof Error ? err.message : "Sign-up failed.")
  );
}

export function RegisterPage() {
  const navigate = useNavigate();
  const setFirebaseAccount = useAuthStore((s) => s.setFirebaseAccount);
  // If they're already signed in (e.g. came in via Google) we only need a profile.
  const existing = currentUser();

  const [pkg, setPkg] = useState<"commissioner" | "owner">("owner");
  const [handle, setHandle] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function finish(uid: string, em: string | null) {
    const res = await api.accountSignup(handle.trim(), pkg);
    setFirebaseAccount({ uid, email: em, handle: res.handle, pkg });
    navigate("/my-leagues", { replace: true });
  }

  function requireHandle(): boolean {
    if (!handle.trim()) {
      setError("Choose a display name first.");
      return false;
    }
    return true;
  }

  async function withEmail(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!requireHandle()) return;
    setPending(true);
    try {
      const user = existing ?? (await signUpEmail(email.trim(), password));
      await finish(user.uid, user.email);
    } catch (err) {
      setError(humanize(err));
    } finally {
      setPending(false);
    }
  }

  async function withGoogle() {
    setError(null);
    if (!requireHandle()) return;
    setPending(true);
    try {
      const user = existing ?? (await signInGoogle());
      await finish(user.uid, user.email);
    } catch (err) {
      setError(humanize(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="relative z-10 flex h-full items-center justify-center bg-canvas">
      <div className="w-full max-w-md animate-fade-in space-y-6 px-6 py-8">
        <div className="flex justify-center">
          <Brand />
        </div>
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Create your account</CardTitle>
              <CardDescription>
                {existing
                  ? "Finish setting up your account."
                  : "Pick how you want to play, then sign up."}
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <form onSubmit={withEmail} className="space-y-4" autoComplete="off">
              <div className="space-y-1.5">
                <Label>I want to…</Label>
                <div className="grid grid-cols-2 gap-2">
                  {(
                    [
                      ["commissioner", "Run a league", "Commissioner"],
                      ["owner", "Join a league", "Owner"],
                    ] as const
                  ).map(([val, sub, title]) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setPkg(val)}
                      className={cn(
                        "rounded-lg border p-3 text-left transition",
                        pkg === val
                          ? "border-amber bg-amber/10"
                          : "border-border hover:border-amber/50",
                      )}
                    >
                      <div className="text-sm font-semibold">{title}</div>
                      <div className="text-xs text-muted">{sub}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="handle">Display name</Label>
                <Input
                  id="handle"
                  value={handle}
                  onChange={(e) => setHandle(e.target.value)}
                  placeholder="e.g. SkipperJoe"
                  autoFocus
                />
              </div>

              {!existing && (
                <>
                  <div className="space-y-1.5">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
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
                </>
              )}

              {error && (
                <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                  {error}
                </p>
              )}

              <Button type="submit" disabled={pending} size="lg" className="w-full">
                {pending && <Loader2 className="h-4 w-4 animate-spin" />}
                {existing ? "Finish setup" : "Create account"}
              </Button>

              {!existing && (
                <>
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
                    Already have an account?{" "}
                    <button
                      type="button"
                      className="text-amber hover:underline"
                      onClick={() => navigate("/login")}
                    >
                      Sign in
                    </button>
                  </p>
                </>
              )}
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
