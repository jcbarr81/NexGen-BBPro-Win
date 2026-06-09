import { create } from "zustand";

export interface SessionPayload {
  token: string;
  username: string;
  role: string;
  teamId: string;
}

export interface AuthState {
  token: string | null;
  username: string | null;
  role: string | null;
  teamId: string | null;
  /** Firebase account (cloud multi-tenant). uid present = signed in via Firebase. */
  uid: string | null;
  email: string | null;
  handle: string | null;
  pkg: "commissioner" | "owner" | null;
  /** True once Firebase has reported its initial auth state (or in non-cloud). */
  firebaseReady: boolean;
  /** Currently-active league id (mirrors sidecar state after selection). */
  activeLeagueId: string | null;
  /** Team id the dashboard should render for. Defaults to the owner's team;
   *  admins can pick any team from the teams list. */
  selectedTeamId: string | null;
  /** Incrementing version number used to invalidate cached team-logo blobs
   *  after a bulk regenerate. Bumped from the Utilities page. */
  logoVersion: number;
  /** Previous session captured by ``elevateSession`` — populated when the
   *  owner clicks "Sign in as admin" on the Utilities page (or any other
   *  in-place elevation entry point). The header banner uses this to
   *  offer a one-click switch back. Tokens have a 12h TTL on the sidecar
   *  so the saved token is still valid for the rest of the work session. */
  previousSession: SessionPayload | null;

  setSession: (session: SessionPayload) => void;
  /** Save the current session as ``previousSession``, then replace it
   *  with ``next``. Used by the AdminElevateCard so the owner can come
   *  back to their team without re-typing their password. */
  elevateSession: (next: SessionPayload) => void;
  /** Restore ``previousSession`` to current and clear it. Returns false
   *  if there's no previous session to switch back to. */
  switchBackToPrevious: () => boolean;
  setActiveLeague: (leagueId: string | null) => void;
  setSelectedTeam: (teamId: string | null) => void;
  /** Set the caller's role + team for the league they just entered (cloud
   *  multi-tenant). ``teamId`` empty = no team claimed yet. Seeds
   *  ``selectedTeamId`` so team-scoped pages render the right team (or none). */
  setLeagueIdentity: (role: string | null, teamId: string | null) => void;
  bumpLogoVersion: () => void;
  /** Set/clear the Firebase account profile (cloud multi-tenant). */
  setFirebaseAccount: (
    account: {
      uid: string;
      email?: string | null;
      handle?: string | null;
      pkg?: "commissioner" | "owner" | null;
    } | null,
  ) => void;
  setFirebaseReady: (ready: boolean) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  username: null,
  role: null,
  teamId: null,
  uid: null,
  email: null,
  handle: null,
  pkg: null,
  firebaseReady: false,
  activeLeagueId: null,
  selectedTeamId: null,
  logoVersion: 0,
  previousSession: null,

  setSession: (session) =>
    set((state) => {
      // If the new session matches a saved previousSession (the user
      // came back manually via the login screen), drop the previous —
      // no banner needed, they've already returned to their owner role.
      const prev = state.previousSession;
      const matchesPrevious =
        prev && prev.username === session.username && prev.role === session.role;
      return {
        token: session.token,
        username: session.username,
        role: session.role,
        teamId: session.teamId,
        selectedTeamId: session.teamId || null,
        previousSession: matchesPrevious ? null : state.previousSession,
      };
    }),
  elevateSession: (next) =>
    set((state) => {
      // Capture the current session if any, so the banner can offer
      // "Switch back to <username>" until the user explicitly logs out
      // or returns to the previous identity.
      const current: SessionPayload | null = state.token
        ? {
            token: state.token,
            username: state.username ?? "",
            role: state.role ?? "",
            teamId: state.teamId ?? "",
          }
        : null;
      // Avoid stacking — if we're elevating from already-elevated state,
      // keep the original previousSession (it's the "real" owner login).
      const previousSession =
        current && current.username !== next.username
          ? state.previousSession ?? current
          : state.previousSession;
      return {
        token: next.token,
        username: next.username,
        role: next.role,
        teamId: next.teamId,
        selectedTeamId: next.teamId || null,
        previousSession,
      };
    }),
  switchBackToPrevious: () => {
    const prev = get().previousSession;
    if (!prev) return false;
    set({
      token: prev.token,
      username: prev.username,
      role: prev.role,
      teamId: prev.teamId,
      selectedTeamId: prev.teamId || null,
      previousSession: null,
    });
    return true;
  },
  setActiveLeague: (leagueId) => set({ activeLeagueId: leagueId }),
  setSelectedTeam: (teamId) => set({ selectedTeamId: teamId }),
  setLeagueIdentity: (role, teamId) =>
    set({ role, teamId, selectedTeamId: teamId || null }),
  bumpLogoVersion: () => set((s) => ({ logoVersion: s.logoVersion + 1 })),
  setFirebaseAccount: (account) =>
    set(
      account
        ? {
            uid: account.uid,
            email: account.email ?? null,
            handle: account.handle ?? null,
            pkg: account.pkg ?? null,
          }
        : { uid: null, email: null, handle: null, pkg: null },
    ),
  setFirebaseReady: (ready) => set({ firebaseReady: ready }),
  clear: () =>
    set({
      token: null,
      username: null,
      role: null,
      teamId: null,
      uid: null,
      email: null,
      handle: null,
      pkg: null,
      activeLeagueId: null,
      selectedTeamId: null,
      previousSession: null,
    }),
}));
