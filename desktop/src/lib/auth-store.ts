import { create } from "zustand";

export interface AuthState {
  token: string | null;
  username: string | null;
  role: string | null;
  teamId: string | null;
  /** Currently-active league id (mirrors sidecar state after selection). */
  activeLeagueId: string | null;
  /** Team id the dashboard should render for. Defaults to the owner's team;
   *  admins can pick any team from the teams list. */
  selectedTeamId: string | null;
  /** Incrementing version number used to invalidate cached team-logo blobs
   *  after a bulk regenerate. Bumped from the Utilities page. */
  logoVersion: number;

  setSession: (session: {
    token: string;
    username: string;
    role: string;
    teamId: string;
  }) => void;
  setActiveLeague: (leagueId: string | null) => void;
  setSelectedTeam: (teamId: string | null) => void;
  bumpLogoVersion: () => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  username: null,
  role: null,
  teamId: null,
  activeLeagueId: null,
  selectedTeamId: null,
  logoVersion: 0,

  setSession: (session) =>
    set({
      token: session.token,
      username: session.username,
      role: session.role,
      teamId: session.teamId,
      selectedTeamId: session.teamId || null,
    }),
  setActiveLeague: (leagueId) => set({ activeLeagueId: leagueId }),
  setSelectedTeam: (teamId) => set({ selectedTeamId: teamId }),
  bumpLogoVersion: () => set((s) => ({ logoVersion: s.logoVersion + 1 })),
  clear: () =>
    set({
      token: null,
      username: null,
      role: null,
      teamId: null,
      activeLeagueId: null,
      selectedTeamId: null,
    }),
}));
