/**
 * Minimal fetch wrapper for the FastAPI sidecar.
 *
 * Every call automatically attaches the current bearer token -- either the
 * user session issued by `/auth/login` (preferred) or the per-launch Electron
 * token as a fallback for pre-login health checks.
 */

import { getBridge } from "./bridge";
import { useAuthStore } from "./auth-store";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message: string,
  ) {
    super(message);
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { apiBaseUrl, launchToken } = getBridge();
  const sessionToken = useAuthStore.getState().token;
  const token = opts.token ?? sessionToken ?? launchToken;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${apiBaseUrl}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  if (!res.ok) {
    const text = await res.text();
    let parsed: unknown = text;
    try {
      parsed = JSON.parse(text);
    } catch {
      /* keep as text */
    }
    const detail =
      (typeof parsed === "object" && parsed && "detail" in parsed && (parsed as any).detail) ||
      text ||
      res.statusText;
    throw new ApiError(res.status, parsed, `${res.status} ${detail}`);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface HealthPayload {
  status: string;
  version: string;
  data_root: string;
  active_league: string | null;
}

export interface LoginPayload {
  token: string;
  username: string;
  role: string;
  team_id: string;
}

export interface League {
  id: string;
  display_name: string;
  mode: string;
  status: string;
  created_at: string;
  last_opened_at: string | null;
  version_created?: string | null;
  version_last_opened?: string | null;
}

export interface Team {
  team_id: string;
  name: string;
  city: string;
  abbreviation: string;
  division: string;
  stadium: string;
  primary_color: string;
  secondary_color: string;
  owner_id: string;
}

export interface TeamSnapshot {
  team_id: string;
  record: string;
  run_diff: string;
  streak: string;
  last10: string;
  next_opponent: string;
  next_date: string;
  injuries: number;
  prob_sp: string | null;
}

export interface DivisionStanding {
  team_id: string;
  label: string;
  name: string;
  wins: number;
  losses: number;
  pct: number;
  gb: string;
  streak: string;
  last10: string;
  is_current: boolean;
}

export interface DivisionStandings {
  division: string;
  teams: DivisionStanding[];
}

export type RosterLevel = "ACT" | "AAA" | "LOW" | "DL" | "IR";

export interface RosterPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  primary_position: string;
  other_positions: string;
  bats: string;
  role: string;
  is_pitcher: boolean;
  injured: boolean;
  injury_description: string;
  level: RosterLevel;
  dl_tier: string | null;
  ratings: Record<string, number | string | null>;
}

export interface TeamRoster {
  team_id: string;
  active_size: number;
  levels: Record<RosterLevel, RosterPlayer[]>;
}

export interface LeagueStandingsRow {
  team_id: string;
  name: string;
  city: string;
  abbreviation: string;
  primary_color: string;
  wins: number;
  losses: number;
  pct: number;
  runs_for: number;
  runs_against: number;
  run_diff: number;
  streak: string;
  last10: string;
  gb: string;
}

export interface LeagueStandingsDivision {
  division: string;
  teams: LeagueStandingsRow[];
}

export interface LeagueStandings {
  divisions: LeagueStandingsDivision[];
}

export interface ScheduleGame {
  date: string;
  home: string;
  away: string;
  result: string | null;
  played: boolean;
  boxscore: string | null;
  is_home?: boolean;
  opponent?: string;
}

export interface ScheduleList {
  games: ScheduleGame[];
  count: number;
}

// --- Live simulation WebSocket events ---

export interface SimStartEvent {
  type: "start";
  game_id: string;
  away: string;
  home: string;
  park: string | null;
  total_pitches: number;
}

export interface SimPitchData {
  count?: string;
  pitch_count?: number;
  pitcher_id?: string;
  batter_id?: string;
  runner_event?: string;
  outcome?: string;
  pitch_type?: string;
  zone?: string;
  [key: string]: unknown;
}

export interface SimPitchEvent {
  type: "pitch";
  seq: number;
  total: number;
  data: SimPitchData;
}

export interface SimFinalEvent {
  type: "final";
  totals: Record<string, number>;
  metadata: Record<string, unknown>;
}

export interface SimErrorEvent {
  type: "error";
  message: string;
}

export type SimEvent = SimStartEvent | SimPitchEvent | SimFinalEvent | SimErrorEvent;

// --- Trades ---

export interface TradePlayer {
  player_id: string;
  name: string;
  position: string;
  is_pitcher: boolean;
}

export interface TradeRecord {
  trade_id: string;
  from_team: string;
  to_team: string;
  status: string;
  give_players: TradePlayer[];
  receive_players: TradePlayer[];
  give_picks: string[];
  receive_picks: string[];
}

export interface TradeList {
  count: number;
  trades: TradeRecord[];
  grouped: Record<string, TradeRecord[]>;
}

// --- Draft ---

export interface DraftSelection {
  overall: number;
  round: number;
  team_id: string;
  player_id: string;
}

export interface DraftState {
  year: number;
  round: number;
  overall_pick: number;
  seed: number | null;
  order: string[];
  selected: DraftSelection[];
  exists: boolean;
}

export interface DraftResults {
  year: number;
  count: number;
  picks: DraftSelection[];
}

// --- Playoffs ---

export interface PlayoffSeed {
  team_id: string;
  seed: number;
  league: string;
  wins: number;
  run_diff: number;
}

export interface PlayoffGame {
  home: string;
  away: string;
  date: string | null;
  result: string | null;
  boxscore: string | null;
  meta?: Record<string, unknown>;
}

export interface PlayoffMatchup {
  high: PlayoffSeed;
  low: PlayoffSeed;
  config: { length: number; pattern?: number[] };
  games: PlayoffGame[];
  winner?: string | null;
}

export interface PlayoffRound {
  name: string;
  matchups: PlayoffMatchup[];
}

export interface Playoffs {
  schema_version: number;
  year: number;
  champion: string | null;
  runner_up: string | null;
  seeds: Record<string, PlayoffSeed[]>;
  rounds: PlayoffRound[];
}

export interface PlayoffYears {
  years: number[];
  latest: number | null;
}

// --- Finance ---

export interface FinanceSnapshot {
  team_id: string;
  cash_on_hand: number;
  debt: number;
  revenue_totals: Record<string, number>;
  expense_totals: Record<string, number>;
  budgets: Record<string, number>;
  projected_revenue: Record<string, number>;
  projected_expenses: Record<string, number>;
  projected_budgets: Record<string, number>;
  projected_net: number;
  financials_enabled: boolean;
  preset: string;
}

export interface FinanceTransaction {
  [key: string]: string | number | boolean | null;
}

export interface FinanceTransactions {
  team_id: string;
  count: number;
  transactions: FinanceTransaction[];
}

// --- Admin ---

export interface AdminUser {
  username: string;
  role: string;
  team_id: string;
}

export interface AdminUsers {
  count: number;
  users: AdminUser[];
}

export interface NewAdminUser {
  username: string;
  password: string;
  role: "admin" | "owner";
  team_id?: string;
}

export interface EditAdminUser {
  password?: string;
  role?: "admin" | "owner";
  team_id?: string;
}

// --- Lineup + pitching staff ---

export type LineupVs = "lhp" | "rhp";

export interface LineupRow {
  order: number;
  player_id: string;
  position: string;
}

export interface Lineup {
  team_id: string;
  vs: LineupVs;
  exists: boolean;
  lineup: LineupRow[];
}

export interface PitchingStaffEntry {
  player_id: string;
  role: string;
}

export interface PitchingStaff {
  team_id: string;
  exists: boolean;
  staff: PitchingStaffEntry[];
}

// --- League leaders ---

export interface LeaderRow {
  rank: number;
  player: {
    player_id: string;
    first_name: string;
    last_name: string;
    team_id: string;
  };
  value: number | string;
}

export interface LeaderBoard {
  label: string;
  key: string;
  decimals: number;
  descending: boolean;
  leaders: LeaderRow[];
}

// --- Team injuries ---

export interface TeamInjuryEntry {
  player_id: string;
  first_name: string;
  last_name: string;
  primary_position: string;
  is_pitcher: boolean;
  level: "DL" | "IR" | "ACT";
  dl_tier: string | null;
  list_label: string;
  injury_description: string;
  return_date: string;
  injury_eligible_date: string;
  injury_start_date: string;
  injury_minimum_days: string | number;
  rehab_assignment: boolean;
  rehab_days: number;
  days_remaining: number | null;
  dl_eligible: boolean;
}

// --- Player profile ---

export interface PlayerProfileNote {
  title: string;
  detail: string;
}

export interface PlayerProfileTrainingFocus {
  source_text: string;
  hitters_text: string;
  pitchers_text: string;
}

export interface PlayerProfile {
  player_id: string;
  full_name: string;
  initials: string;
  team_id: string;
  is_pitcher: boolean;
  positions_text: string;
  age_text: string;
  height_text: string;
  weight_text: string;
  bats_text: string;
  throws_text: string;
  role_text: string;
  overall_display: number | null;
  overall_stars_text: string;
  scouting_summary: string;
  scouting_confidence_text: string;
  health_status: string;
  header_metrics: Array<[string, string]>;
  defense_ratings: Array<[string, string]>;
  overview_ratings: Array<[string, string]>;
  training_focus: PlayerProfileTrainingFocus | null;
  recent_training_entries: PlayerProfileNote[];
  injury_history: PlayerProfileNote[];
  stats_rows: Array<[string, Record<string, unknown>]>;
  stats_columns: string[];
  overall_details: Array<[string, string]>;
  contract_details: Array<[string, string]>;
}

// --- Team settings ---

export interface StrategyOption {
  id: string;
  label: string;
  description: string;
}

export interface TeamSettings {
  team_id: string;
  name: string;
  city: string;
  abbreviation: string;
  division: string;
  stadium: string;
  primary_color: string;
  secondary_color: string;
  strategy: {
    profile: string;
    label: string;
    description: string;
    source: string;
  };
  auto_reassign: { enabled: boolean; source: string };
  options: {
    strategies: StrategyOption[];
    default_strategy: string;
    ballparks: string[];
  };
}

export interface TeamSettingsPatch {
  primary_color?: string;
  secondary_color?: string;
  stadium?: string;
  strategy?: string;
  auto_reassign?: "enabled" | "disabled" | "default" | null;
}

// --- Training focus ---

export interface TrainingFocus {
  team_id: string;
  source: "team" | "defaults";
  league_id: string;
  tracks: { hitters: string[]; pitchers: string[] };
  hitters: Record<string, number>;
  pitchers: Record<string, number>;
  defaults: {
    hitters: Record<string, number>;
    pitchers: Record<string, number>;
  };
}

// --- Season progression ---

export type SeasonPhase =
  | "PRESEASON"
  | "REGULAR_SEASON"
  | "AMATEUR_DRAFT"
  | "PLAYOFFS"
  | "OFFSEASON";

export interface SeasonState {
  phase: SeasonPhase;
  current_date: string | null;
  draft_date: string | null;
  days_total: number;
  days_played: number;
  days_remaining: number;
  mid_remaining: number;
  all_star_played: boolean;
  draft_triggered: boolean;
  played_dates?: string[];
  errors?: string[];
  new_phase?: SeasonPhase;
}

export const api = {
  health: () => apiRequest<HealthPayload>("/healthz"),
  login: (username: string, password: string) =>
    apiRequest<LoginPayload>("/auth/login", {
      method: "POST",
      body: { username, password },
    }),
  listLeagues: () => apiRequest<League[]>("/leagues"),
  getActiveLeague: () => apiRequest<{ league_id: string | null }>("/leagues/active"),
  setActiveLeague: (leagueId: string) =>
    apiRequest<{ league_id: string | null }>(`/leagues/active/${encodeURIComponent(leagueId)}`, {
      method: "POST",
    }),
  listTeams: () => apiRequest<Team[]>("/teams"),
  getTeam: (teamId: string) =>
    apiRequest<Team>(`/teams/${encodeURIComponent(teamId)}`),
  teamSnapshot: (teamId: string) =>
    apiRequest<TeamSnapshot>(`/teams/${encodeURIComponent(teamId)}/snapshot`),
  teamDivision: (teamId: string) =>
    apiRequest<DivisionStandings>(`/teams/${encodeURIComponent(teamId)}/division`),
  teamRoster: (teamId: string) =>
    apiRequest<TeamRoster>(`/teams/${encodeURIComponent(teamId)}/roster`),
  moveRoster: (
    teamId: string,
    payload: { player_id: string; to: RosterLevel; dl_tier?: "dl15" | "dl45" },
  ) =>
    apiRequest<TeamRoster>(
      `/teams/${encodeURIComponent(teamId)}/roster/move`,
      { method: "POST", body: payload },
    ),
  cutRoster: (teamId: string, player_id: string) =>
    apiRequest<TeamRoster>(
      `/teams/${encodeURIComponent(teamId)}/roster/cut`,
      { method: "POST", body: { player_id } },
    ),
  getLineup: (teamId: string, vs: LineupVs) =>
    apiRequest<Lineup>(
      `/teams/${encodeURIComponent(teamId)}/lineup/${vs}`,
    ),
  saveLineup: (teamId: string, vs: LineupVs, lineup: LineupRow[]) =>
    apiRequest<Lineup>(
      `/teams/${encodeURIComponent(teamId)}/lineup/${vs}`,
      { method: "PUT", body: { lineup } },
    ),
  autofillLineup: (teamId: string) =>
    apiRequest<{ team_id: string; lhp: Lineup; rhp: Lineup }>(
      `/teams/${encodeURIComponent(teamId)}/lineup/autofill`,
      { method: "POST" },
    ),
  getPitchingStaff: (teamId: string) =>
    apiRequest<PitchingStaff>(`/teams/${encodeURIComponent(teamId)}/pitching`),
  savePitchingStaff: (teamId: string, staff: PitchingStaffEntry[]) =>
    apiRequest<PitchingStaff>(
      `/teams/${encodeURIComponent(teamId)}/pitching`,
      { method: "PUT", body: { staff } },
    ),
  leagueStandings: () => apiRequest<LeagueStandings>("/standings/league"),
  leagueHistory: () =>
    apiRequest<{
      count: number;
      seasons: Array<{
        season_id: string;
        league_year: string;
        ended_on: string;
        archived_on: string;
        champion: string;
        runner_up: string;
        series_result: string;
        mvp: string;
        cy_young: string;
        artifacts: Record<string, string>;
      }>;
    }>("/league/history"),
  browsePlayers: (
    params: {
      q?: string;
      teamId?: string;
      position?: string;
      role?: "Hitters" | "Pitchers" | "All";
      freeAgentsOnly?: boolean;
      limit?: number;
    } = {},
  ) => {
    const qp = new URLSearchParams();
    if (params.q) qp.set("q", params.q);
    if (params.teamId) qp.set("team_id", params.teamId);
    if (params.position) qp.set("position", params.position);
    if (params.role) qp.set("role", params.role);
    if (params.freeAgentsOnly) qp.set("free_agents_only", "true");
    if (params.limit !== undefined) qp.set("limit", String(params.limit));
    const qs = qp.toString();
    return apiRequest<{
      count: number;
      players: Array<{
        player_id: string;
        first_name: string;
        last_name: string;
        primary_position: string;
        is_pitcher: boolean;
        bats: string;
        role: string;
        ratings: Record<string, number | string | null>;
        team_id: string;
        level: "ACT" | "AAA" | "LOW" | "DL" | "IR" | "FA";
      }>;
    }>(`/players/browse${qs ? `?${qs}` : ""}`);
  },
  leagueStats: () =>
    apiRequest<{
      columns: { batters: string[]; pitchers: string[]; teams: string[] };
      batters: Array<{
        player_id: string;
        first_name: string;
        last_name: string;
        primary_position: string;
        is_pitcher: boolean;
        stats: Record<string, number | string | null>;
      }>;
      pitchers: Array<{
        player_id: string;
        first_name: string;
        last_name: string;
        primary_position: string;
        is_pitcher: boolean;
        stats: Record<string, number | string | null>;
      }>;
      teams: Array<{
        team_id: string;
        stats: Record<string, number | string | null>;
      }>;
    }>("/league/stats"),
  leaders: (limit = 5) =>
    apiRequest<{
      qualifiers: { min_pa: number; min_ip: number; max_team_games: number };
      batting: LeaderBoard[];
      pitching: LeaderBoard[];
    }>(`/league/leaders?limit=${limit}`),
  freeAgents: (limit = 1000) =>
    apiRequest<{
      count: number;
      limit: number;
      free_agents: Array<{
        player_id: string;
        first_name: string;
        last_name: string;
        primary_position: string;
        other_positions: string;
        bats: string;
        is_pitcher: boolean;
        role: string;
        ratings: Record<string, number | string | null>;
      }>;
    }>(`/free-agents?limit=${limit}`),
  signFreeAgent: (
    teamId: string,
    payload: { player_id: string; level: "ACT" | "AAA" | "LOW" },
  ) =>
    apiRequest<{
      team_id: string;
      player_id: string;
      level: string;
      signed: boolean;
    }>(`/teams/${encodeURIComponent(teamId)}/sign`, {
      method: "POST",
      body: payload,
    }),
  teamInjuries: (teamId: string) =>
    apiRequest<{
      team_id: string;
      counts: {
        dl: number;
        ir: number;
        day_to_day: number;
        eligible_to_activate: number;
      };
      dl: TeamInjuryEntry[];
      ir: TeamInjuryEntry[];
      day_to_day: TeamInjuryEntry[];
    }>(`/teams/${encodeURIComponent(teamId)}/injuries`),
  news: (
    params: { q?: string; teamId?: string; category?: string; limit?: number } = {},
  ) => {
    const qp = new URLSearchParams();
    if (params.q) qp.set("q", params.q);
    if (params.teamId) qp.set("team_id", params.teamId);
    if (params.category) qp.set("category", params.category);
    if (params.limit !== undefined) qp.set("limit", String(params.limit));
    const qs = qp.toString();
    return apiRequest<{
      count: number;
      items: Array<{
        timestamp: string;
        category: string;
        team: string;
        message: string;
        raw: string;
      }>;
    }>(`/news${qs ? `?${qs}` : ""}`);
  },
  activity: (
    params: { teamId?: string; action?: string; limit?: number } = {},
  ) => {
    const q = new URLSearchParams();
    if (params.teamId) q.set("team_id", params.teamId);
    if (params.action) q.set("action", params.action);
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    const qs = q.toString();
    return apiRequest<{
      count: number;
      transactions: Array<Record<string, string>>;
    }>(`/activity${qs ? `?${qs}` : ""}`);
  },
  boxscore: (path: string) =>
    apiRequest<{ path: string; filename: string; html: string }>(
      `/boxscore?path=${encodeURIComponent(path)}`,
    ),
  playerProfile: (playerId: string) =>
    apiRequest<PlayerProfile>(
      `/players/${encodeURIComponent(playerId)}/profile`,
    ),
  getTeamSettings: (teamId: string) =>
    apiRequest<TeamSettings>(`/teams/${encodeURIComponent(teamId)}/settings`),
  saveTeamSettings: (teamId: string, payload: TeamSettingsPatch) =>
    apiRequest<TeamSettings>(`/teams/${encodeURIComponent(teamId)}/settings`, {
      method: "PUT",
      body: payload,
    }),
  getTraining: (teamId: string) =>
    apiRequest<TrainingFocus>(`/teams/${encodeURIComponent(teamId)}/training`),
  saveTraining: (
    teamId: string,
    payload: { hitters: Record<string, number>; pitchers: Record<string, number> },
  ) =>
    apiRequest<TrainingFocus>(`/teams/${encodeURIComponent(teamId)}/training`, {
      method: "PUT",
      body: payload,
    }),
  resetTraining: (teamId: string) =>
    apiRequest<TrainingFocus>(`/teams/${encodeURIComponent(teamId)}/training`, {
      method: "DELETE",
    }),
  seasonState: () => apiRequest<SeasonState>("/season/state"),
  seasonSimulateDay: () =>
    apiRequest<SeasonState>("/season/simulate/day", { method: "POST" }),
  seasonSimulateWeek: () =>
    apiRequest<SeasonState>("/season/simulate/week", { method: "POST" }),
  seasonSimulateMonth: () =>
    apiRequest<SeasonState>("/season/simulate/month", { method: "POST" }),
  seasonSimulateDays: (n: number) =>
    apiRequest<SeasonState>("/season/simulate/days", {
      method: "POST",
      body: { n },
    }),
  seasonSimulateToDraft: () =>
    apiRequest<SeasonState>("/season/simulate/to-draft", { method: "POST" }),
  seasonSimulateToPlayoffs: () =>
    apiRequest<SeasonState>("/season/simulate/to-playoffs", { method: "POST" }),
  seasonAdvancePhase: () =>
    apiRequest<SeasonState>("/season/advance-phase", { method: "POST" }),
  adminListUsers: () => apiRequest<AdminUsers>("/admin/users"),
  adminCreateUser: (payload: NewAdminUser) =>
    apiRequest<AdminUser>("/admin/users", { method: "POST", body: payload }),
  adminEditUser: (username: string, payload: EditAdminUser) =>
    apiRequest<AdminUser>(`/admin/users/${encodeURIComponent(username)}`, {
      method: "PATCH",
      body: payload,
    }),
  financeSnapshot: (teamId: string) =>
    apiRequest<FinanceSnapshot>(
      `/teams/${encodeURIComponent(teamId)}/finance/snapshot`,
    ),
  financeTransactions: (teamId: string, limit = 50) =>
    apiRequest<FinanceTransactions>(
      `/teams/${encodeURIComponent(teamId)}/finance/transactions?limit=${limit}`,
    ),
  playoffYears: () => apiRequest<PlayoffYears>("/playoffs/years"),
  playoffs: (year?: number) => {
    const qs = year ? `?year=${year}` : "";
    return apiRequest<Playoffs>(`/playoffs${qs}`);
  },
  draftState: (year?: number) => {
    const qs = year ? `?year=${year}` : "";
    return apiRequest<DraftState>(`/draft/state${qs}`);
  },
  draftResults: (year?: number) => {
    const qs = year ? `?year=${year}` : "";
    return apiRequest<DraftResults>(`/draft/results${qs}`);
  },
  proposeTrade: (payload: {
    from_team: string;
    to_team: string;
    give_player_ids: string[];
    receive_player_ids: string[];
    give_pick_ids?: string[];
    receive_pick_ids?: string[];
  }) =>
    apiRequest<{ trade_id: string; from_team: string; to_team: string; status: string }>(
      "/trades",
      { method: "POST", body: payload },
    ),
  acceptTrade: (tradeId: string) =>
    apiRequest<{ trade_id: string; status: string }>(
      `/trades/${encodeURIComponent(tradeId)}/accept`,
      { method: "POST" },
    ),
  rejectTrade: (tradeId: string) =>
    apiRequest<{ trade_id: string; status: string }>(
      `/trades/${encodeURIComponent(tradeId)}/reject`,
      { method: "POST" },
    ),
  withdrawTrade: (tradeId: string) =>
    apiRequest<{ trade_id: string; withdrawn: boolean }>(
      `/trades/${encodeURIComponent(tradeId)}`,
      { method: "DELETE" },
    ),
  trades: (params: { teamId?: string; status?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.teamId) q.set("team_id", params.teamId);
    if (params.status) q.set("status", params.status);
    const qs = q.toString();
    return apiRequest<TradeList>(`/trades${qs ? `?${qs}` : ""}`);
  },
  schedule: (params: {
    teamId?: string;
    start?: string;
    end?: string;
    played?: boolean;
    limit?: number;
  } = {}) => {
    const q = new URLSearchParams();
    if (params.teamId) q.set("team_id", params.teamId);
    if (params.start) q.set("start", params.start);
    if (params.end) q.set("end", params.end);
    if (params.played !== undefined) q.set("played", String(params.played));
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    const qs = q.toString();
    return apiRequest<ScheduleList>(`/schedule${qs ? `?${qs}` : ""}`);
  },
};
