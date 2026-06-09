/** Helpers for the cloud (Firebase) multi-tenant auth flow. */

import { firebaseEnabled, signOut as fbSignOut } from "./firebase";
import { useAuthStore } from "./auth-store";

/** True in the cloud build (Firebase config present); false in Electron/local. */
export function isCloud(): boolean {
  return firebaseEnabled();
}

export async function cloudLogout(): Promise<void> {
  try {
    await fbSignOut();
  } catch {
    /* ignore */
  }
  useAuthStore.getState().clear();
}
