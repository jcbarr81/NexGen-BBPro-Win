/**
 * Keeps the auth-store in sync with Firebase's current user (cloud build).
 * On sign-in it records the uid and fetches the account profile (handle +
 * package); on sign-out it clears. Sets ``firebaseReady`` once the initial
 * auth state is known so the entry router doesn't redirect prematurely.
 */

import { useEffect } from "react";

import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { isCloud } from "@/lib/cloud-auth";
import { completeGoogleRedirect, onUser } from "@/lib/firebase";

export function FirebaseAuthSync() {
  const setFirebaseAccount = useAuthStore((s) => s.setFirebaseAccount);
  const setFirebaseReady = useAuthStore((s) => s.setFirebaseReady);

  useEffect(() => {
    if (!isCloud()) {
      setFirebaseReady(true);
      return;
    }
    // If we're returning from a full-page Google redirect, finish it (and let
    // any error surface in the console rather than being silently dropped).
    completeGoogleRedirect().catch(() => {
      /* logged inside completeGoogleRedirect; onUser stays the source of truth */
    });
    const unsub = onUser(async (user) => {
      if (!user) {
        setFirebaseAccount(null);
        setFirebaseReady(true);
        return;
      }
      // Record uid immediately so API calls carry the token + we know we're authed.
      setFirebaseAccount({ uid: user.uid, email: user.email });
      try {
        const me = await api.accountMe();
        setFirebaseAccount({
          uid: user.uid,
          email: user.email,
          handle: me.account?.handle ?? null,
          pkg: (me.account?.package as "commissioner" | "owner" | undefined) ?? null,
        });
      } catch {
        /* signed in but no account profile yet — they must finish /register */
      } finally {
        setFirebaseReady(true);
      }
    });
    return unsub;
  }, [setFirebaseAccount, setFirebaseReady]);

  return null;
}
