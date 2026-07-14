/**
 * Firebase Authentication for the cloud (multi-tenant) build.
 *
 * Provides email/password + Google sign-in and exposes the current user's ID
 * token, which `api.ts` sends as the bearer for cloud requests.
 *
 * The firebase SDK (~580 KB of source) is loaded **lazily via dynamic
 * import** the first time an auth operation runs — it must never be pinned
 * into the entry chunk, because the Electron/local build (no Firebase
 * config) pays the download for nothing. `firebaseEnabled()` is a pure env
 * check and stays synchronous.
 */

// Type-only imports are erased at build time — they don't pull the SDK in.
import type { Auth, User } from "firebase/auth";

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
  messagingSenderId: import.meta.env.VITE_FIREBASE_SENDER_ID as string | undefined,
};

/** True when a Firebase config is present (i.e. the cloud build). */
export function firebaseEnabled(): boolean {
  return Boolean(config.apiKey && config.authDomain && config.projectId);
}

// Lazily-initialized singletons. `_authInstance` doubles as the sync
// "has the SDK loaded yet?" signal for `currentUser()`.
let _authInstance: Auth | null = null;
let _loading: Promise<Auth> | null = null;

async function loadAuth(): Promise<Auth> {
  if (_authInstance) return _authInstance;
  if (!_loading) {
    _loading = (async () => {
      const [{ initializeApp }, authMod] = await Promise.all([
        import("firebase/app"),
        import("firebase/auth"),
      ]);
      const app = initializeApp(config as Record<string, string>);
      _authInstance = authMod.getAuth(app);
      return _authInstance;
    })();
  }
  return _loading;
}

/**
 * Synchronous current-user accessor. Returns null until the SDK has loaded
 * and Firebase has restored the session — the same observable behavior as
 * before (Firebase restores auth asynchronously anyway); callers already
 * gate on the auth store's `firebaseReady`/`uid`.
 */
export function currentUser(): User | null {
  return _authInstance?.currentUser ?? null;
}

/** Fresh ID token for the signed-in user (auto-refreshes); null if signed out. */
export async function getIdToken(): Promise<string | null> {
  if (!firebaseEnabled()) return null;
  const auth = await loadAuth();
  return auth.currentUser ? auth.currentUser.getIdToken() : null;
}

/**
 * Subscribe to auth-state changes. Kicks off the lazy SDK load; the
 * unsubscribe function works whether or not the load has finished.
 */
export function onUser(cb: (user: User | null) => void): () => void {
  if (!firebaseEnabled()) {
    cb(null);
    return () => {};
  }
  let unsub: () => void = () => {};
  let cancelled = false;
  void (async () => {
    const [auth, mod] = await Promise.all([loadAuth(), import("firebase/auth")]);
    if (cancelled) return;
    unsub = mod.onAuthStateChanged(auth, cb);
  })();
  return () => {
    cancelled = true;
    unsub();
  };
}

export async function signUpEmail(email: string, password: string): Promise<User> {
  const [auth, mod] = await Promise.all([loadAuth(), import("firebase/auth")]);
  const cred = await mod.createUserWithEmailAndPassword(auth, email, password);
  return cred.user;
}

export async function signInEmail(email: string, password: string): Promise<User> {
  const [auth, mod] = await Promise.all([loadAuth(), import("firebase/auth")]);
  const cred = await mod.signInWithEmailAndPassword(auth, email, password);
  return cred.user;
}

/** Pull as much detail as possible out of a Firebase Auth error for logging. */
function describeAuthError(err: unknown): string {
  const e = err as {
    code?: string;
    message?: string;
    customData?: { _serverResponse?: unknown; serverResponse?: unknown };
  };
  let detail = "";
  try {
    const sr =
      (e?.customData?._serverResponse ?? e?.customData?.serverResponse) ?? null;
    if (sr) detail = ` serverResponse=${JSON.stringify(sr)}`;
  } catch {
    /* ignore */
  }
  return `${e?.code ?? "unknown"}: ${e?.message ?? String(err)}${detail}`;
}

/** Error codes where the popup itself is the problem → retry via full-page redirect. */
const POPUP_FALLBACK_CODES = new Set([
  "auth/internal-error",
  "auth/popup-blocked",
  "auth/popup-closed-by-user",
  "auth/cancelled-popup-request",
  "auth/operation-not-supported-in-this-environment",
  "auth/web-storage-unsupported",
  "auth/missing-or-invalid-nonce",
]);

export async function signInGoogle(): Promise<User> {
  const [auth, mod] = await Promise.all([loadAuth(), import("firebase/auth")]);
  const provider = new mod.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  try {
    const cred = await mod.signInWithPopup(auth, provider);
    return cred.user;
  } catch (err) {
    const code = (err as { code?: string })?.code ?? "";
    // Surface the real cause in the console regardless of how we recover.
    console.error("[firebase] signInWithPopup failed:", describeAuthError(err));
    if (POPUP_FALLBACK_CODES.has(code)) {
      // Full-page redirect: navigates away (no return value). On the way back,
      // completeGoogleRedirect()/onAuthStateChanged finishes the sign-in.
      await mod.signInWithRedirect(auth, provider);
      // signInWithRedirect never resolves to a user (the page unloads); keep the
      // caller's promise pending until navigation happens.
      return new Promise<User>(() => {});
    }
    throw err;
  }
}

/**
 * Completes a redirect-based Google sign-in when the app reloads after the
 * round-trip. Returns the user on success, null if there was no pending
 * redirect. Logs (and re-throws) the real error so it isn't swallowed.
 */
export async function completeGoogleRedirect(): Promise<User | null> {
  if (!firebaseEnabled()) return null;
  const [auth, mod] = await Promise.all([loadAuth(), import("firebase/auth")]);
  try {
    const cred = await mod.getRedirectResult(auth);
    return cred?.user ?? null;
  } catch (err) {
    console.error("[firebase] getRedirectResult failed:", describeAuthError(err));
    throw err;
  }
}

export async function resetPassword(email: string): Promise<void> {
  const [auth, mod] = await Promise.all([loadAuth(), import("firebase/auth")]);
  await mod.sendPasswordResetEmail(auth, email);
}

export async function signOut(): Promise<void> {
  if (!firebaseEnabled()) return;
  const [auth, mod] = await Promise.all([loadAuth(), import("firebase/auth")]);
  await mod.signOut(auth);
}
