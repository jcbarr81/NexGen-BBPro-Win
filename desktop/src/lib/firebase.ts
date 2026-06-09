/**
 * Firebase Authentication for the cloud (multi-tenant) build.
 *
 * Provides email/password + Google sign-in and exposes the current user's ID
 * token, which `api.ts` sends as the bearer for cloud requests. Initializes
 * lazily and only when a Firebase config is present (the Electron / local build
 * has none and keeps using the legacy sidecar login).
 */

import { initializeApp, type FirebaseApp } from "firebase/app";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  getRedirectResult,
  onAuthStateChanged,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  signInWithPopup,
  signInWithRedirect,
  signOut as fbSignOut,
  type Auth,
  type User,
} from "firebase/auth";

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
  messagingSenderId: import.meta.env.VITE_FIREBASE_SENDER_ID as string | undefined,
};

let _app: FirebaseApp | null = null;
let _auth: Auth | null = null;

/** True when a Firebase config is present (i.e. the cloud build). */
export function firebaseEnabled(): boolean {
  return Boolean(config.apiKey && config.authDomain && config.projectId);
}

export function auth(): Auth {
  if (!_auth) {
    _app = initializeApp(config as Record<string, string>);
    _auth = getAuth(_app);
  }
  return _auth;
}

export function currentUser(): User | null {
  return firebaseEnabled() ? auth().currentUser : null;
}

/** Fresh ID token for the signed-in user (auto-refreshes); null if signed out. */
export async function getIdToken(): Promise<string | null> {
  const u = currentUser();
  return u ? u.getIdToken() : null;
}

export function onUser(cb: (user: User | null) => void): () => void {
  if (!firebaseEnabled()) {
    cb(null);
    return () => {};
  }
  return onAuthStateChanged(auth(), cb);
}

export async function signUpEmail(email: string, password: string): Promise<User> {
  const cred = await createUserWithEmailAndPassword(auth(), email, password);
  return cred.user;
}

export async function signInEmail(email: string, password: string): Promise<User> {
  const cred = await signInWithEmailAndPassword(auth(), email, password);
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
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  try {
    const cred = await signInWithPopup(auth(), provider);
    return cred.user;
  } catch (err) {
    const code = (err as { code?: string })?.code ?? "";
    // Surface the real cause in the console regardless of how we recover.
    console.error("[firebase] signInWithPopup failed:", describeAuthError(err));
    if (POPUP_FALLBACK_CODES.has(code)) {
      // Full-page redirect: navigates away (no return value). On the way back,
      // completeGoogleRedirect()/onAuthStateChanged finishes the sign-in.
      await signInWithRedirect(auth(), provider);
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
  try {
    const cred = await getRedirectResult(auth());
    return cred?.user ?? null;
  } catch (err) {
    console.error("[firebase] getRedirectResult failed:", describeAuthError(err));
    throw err;
  }
}

export async function resetPassword(email: string): Promise<void> {
  await sendPasswordResetEmail(auth(), email);
}

export async function signOut(): Promise<void> {
  if (firebaseEnabled()) await fbSignOut(auth());
}
