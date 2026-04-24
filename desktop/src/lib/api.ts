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
    const rawDetail =
      (typeof parsed === "object" && parsed && "detail" in parsed && (parsed as any).detail) ||
      text ||
      res.statusText;
    // Flatten object-shaped details so the default error text reads naturally.
    // Two shapes we know about:
    //   - validation:  {message, errors[], warnings[]}
    //   - unhandled:   {message, traceback}
    // Any other object shape falls through to JSON so nothing is lost.
    const detail =
      rawDetail && typeof rawDetail === "object" && !Array.isArray(rawDetail)
        ? [
            (rawDetail as any).message,
            ...(Array.isArray((rawDetail as any).errors)
              ? ((rawDetail as any).errors as unknown[]).map((e) => `• ${e}`)
              : []),
            (rawDetail as any).traceback
              ? `\n${(rawDetail as any).traceback}`
              : "",
          ]
            .filter(Boolean)
            .join("\n") || JSON.stringify(rawDetail)
        : rawDetail;
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

/** Response shape from POST /exports/logos and /exports/avatars — the
 *  actual generation runs in a background thread; poll ``getExportJob``
 *  for progress/result. */
export interface ExportJobStart {
  job_id: string;
  kind: "logos" | "avatars";
}

/** Response shape from GET /exports/jobs/{id}. */
export interface ExportJobStatus {
  id: string;
  kind: "logos" | "avatars";
  status: "running" | "completed" | "failed";
  done: number;
  total: number;
  phase: string;
  output_dir: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  started_at: number;
  finished_at: number | null;
}

/** Start an export job and poll until it finishes. Calls ``onProgress``
 *  after each poll tick so the UI can render a progress bar. Throws on
 *  ``failed`` with the server-side error message. */
export async function runExportJob(
  start: () => Promise<ExportJobStart>,
  onProgress?: (status: ExportJobStatus) => void,
  { pollMs = 500, signal }: { pollMs?: number; signal?: AbortSignal } = {},
): Promise<ExportJobStatus> {
  const { job_id } = await start();
  for (;;) {
    if (signal?.aborted) throw new Error("Cancelled");
    const status = await api.getExportJob(job_id);
    onProgress?.(status);
    if (status.status === "completed") return status;
    if (status.status === "failed") {
      throw new Error(status.error || "Job failed");
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }
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

// --- Commissioner settings ---

export interface CommissionerSettings {
  trade: {
    league_id: string;
    trades_enabled: boolean;
    draft_pick_trading_enabled: boolean;
    require_commissioner_approval: boolean;
    cpu_initiated_trades_enabled: boolean;
    cpu_proposal_cadence: string;
    max_pick_trade_years: number;
  };
  injury: { league_id: string; level: string };
  finance: {
    league_id: string;
    enabled: boolean;
    preset: string;
    enforcement_mode: string;
    modules: Record<string, string>;
  };
  strategy: {
    default_profile: string | null;
    teams: Record<string, string>;
  };
  auto_reassign: {
    default_enabled: boolean;
    teams: Record<string, boolean>;
  };
  options: {
    trade_cadences: string[];
    injury_levels: string[];
    finance_presets: string[];
    finance_enforcement: string[];
    strategy_profiles: Array<{
      id: string;
      label: string;
      description: string;
    }>;
  };
}

// --- Dashboard widgets ---

export interface BullpenArm {
  name?: string;
  role?: string;
  status?: string;
  days?: number;
  available_pct?: number;
  [key: string]: unknown;
}

export interface BullpenReadiness {
  ready?: number;
  limited?: number;
  rest?: number;
  total?: number;
  avg_available_pct?: number;
  probable_starter?: string | null;
  detail?: BullpenArm[];
  note?: string;
  [key: string]: unknown;
}

export interface MatchupScout {
  opponent?: string;
  venue?: string;
  opp_record?: string;
  opp_run_diff?: string;
  opp_streak?: string;
  note?: string;
  team_probable?: string;
  opp_probable?: string;
  date?: string;
  [key: string]: unknown;
}

export interface PerformerRow {
  name?: string;
  player_id?: string;
  delta_text?: string;
  summary?: string;
  [key: string]: unknown;
}

export interface Performers {
  hitters?: { hot?: PerformerRow[]; cold?: PerformerRow[] };
  pitchers?: { hot?: PerformerRow[]; cold?: PerformerRow[] };
  window?: number;
  range?: string;
  [key: string]: unknown;
}

export interface DashboardLeader {
  label?: string;
  player_id?: string;
  value_text?: string;
  value?: number | string;
  [key: string]: unknown;
}

export interface TeamWidgets {
  team_id: string;
  bullpen: BullpenReadiness;
  matchup: MatchupScout;
  performers: Performers;
  batting_leaders: DashboardLeader[];
  pitching_leaders: DashboardLeader[];
  leader_meta: Record<string, unknown>;
}

export type RosterLevel = "ACT" | "AAA" | "LOW" | "DL" | "IR";

/** Position-bucket percentile annotation for a hitter's rating, mirroring
 *  the "Top X% of <bucket> (avg Y)" tooltip from PyQt's
 *  position_players_dialog. Pitchers compare against the whole pitcher
 *  pool and don't carry this — ``ratings_context`` is absent or missing
 *  the key. */
export interface RatingContextEntry {
  top_pct: number;
  bucket: string | null;
  avg: number | null;
}

export interface RosterPlayer {
  player_id: string;
  first_name: string;
  last_name: string;
  primary_position: string;
  other_positions: string;
  bats: string;
  throws?: string;
  role: string;
  /** Pitcher-only: SP/RP preference from the generator (CL, SP, RP, etc.). */
  preferred_pitching_role?: string;
  /** ISO ``YYYY-MM-DD``; empty when unknown. */
  birthdate?: string;
  /** Years old as of today; null when birthdate is missing/unparseable. */
  age?: number | null;
  is_pitcher: boolean;
  injured: boolean;
  injury_description: string;
  level: RosterLevel;
  dl_tier: string | null;
  ratings: Record<string, number | string | null>;
  ratings_context?: Record<string, RatingContextEntry>;
  /** Raw average across component ratings (0-99). */
  overall_raw?: number | null;
  /** Overall scaled through the 35-99 display transform. */
  overall_display?: number | null;
  /** Pre-formatted star text (e.g. ``"4"`` or ``"4.5"``). */
  overall_stars_text?: string | null;
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
  /** Hydrated from players.csv by the results endpoint. Absent when the
   *  live draft state carries selections that haven't been matched to a
   *  player row yet. */
  first_name?: string;
  last_name?: string;
  primary_position?: string;
  is_pitcher?: boolean;
  overall_raw?: number | null;
  overall_display?: number | null;
  overall_stars_text?: string | null;
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
  /** Rolling metric chart data — parallel snapshots across the last ~12
   *  season_history JSON files. Hitters: AVG/OPS. Pitchers: ERA/WHIP. */
  rolling_stats?: {
    dates: string[];
    series: Record<string, number[]>;
  } | null;
  /** Per-season rating snapshot list for the Career Ledger "Ratings" tab. */
  ratings_history?: Array<{
    label: string;
    ratings: Record<string, number | null>;
  }>;
  /** Per-season awards earned. */
  awards_history?: Array<{ year: string; award: string; description: string }>;
  /** All transaction rows (signing, release, trade, DL moves). */
  transactions_log?: Array<{
    date: string;
    description: string;
    from_team: string;
    to_team: string;
  }>;
  /** Trade-only filter of transactions_log. */
  trade_log?: Array<{
    date: string;
    description: string;
    from_team: string;
    to_team: string;
  }>;
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

export interface PlayerTrainingFocus {
  player_id: string;
  team_id: string | null;
  source: "player" | "team" | "defaults";
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
  /** True when the simulator hit the draft date — owner must run the
   *  draft in /draft before any more days will advance. */
  draft_blocked?: boolean;
  /** Summary returned after each simulated batch: finance cadence,
   *  CPU trade offers, and DL activations. */
  automations?: {
    finance?: Record<string, unknown>;
    finance_error?: string;
    cpu_trades?: Record<string, unknown>;
    cpu_trades_error?: string;
    dl_updates?: { activated: number; alerts: number; blocked: number };
    dl_updates_error?: string;
  };
  /** Set when advance_phase steps into PLAYOFFS. */
  playoffs?: { saved?: boolean; path?: string; reused_existing?: boolean; teams_seeded?: number; error?: string };
  playoffs_error?: string;
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
  deleteLeague: (leagueId: string) =>
    apiRequest<{ deleted: boolean; league_id: string; active_league: string | null }>(
      `/leagues/${encodeURIComponent(leagueId)}`,
      { method: "DELETE" },
    ),
  listTeams: () => apiRequest<Team[]>("/teams"),
  getTeam: (teamId: string) =>
    apiRequest<Team>(`/teams/${encodeURIComponent(teamId)}`),
  teamSnapshot: (teamId: string) =>
    apiRequest<TeamSnapshot>(`/teams/${encodeURIComponent(teamId)}/snapshot`),
  teamDivision: (teamId: string) =>
    apiRequest<DivisionStandings>(`/teams/${encodeURIComponent(teamId)}/division`),
  teamWidgets: (teamId: string) =>
    apiRequest<TeamWidgets>(`/teams/${encodeURIComponent(teamId)}/widgets`),
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
  autofillPitchingStaff: (teamId: string) =>
    apiRequest<PitchingStaff>(
      `/teams/${encodeURIComponent(teamId)}/pitching/autofill`,
      { method: "POST" },
    ),
  leagueStandings: () => apiRequest<LeagueStandings>("/standings/league"),
  leaguesFirstRun: () =>
    apiRequest<{ has_leagues: boolean; count: number }>("/leagues/first-run"),
  leaguePresets: () =>
    apiRequest<{
      rule_presets: Array<{ preset_id: string; name: string; description: string }>;
      schedule_templates: Array<{
        template_id: string;
        name: string;
        description: string;
        games_per_team: number;
      }>;
      quickstart_presets: Array<{
        preset_id: string;
        name: string;
        description: string;
        divisions: string[];
        teams_per_division: number;
        rule_preset_id: string;
        schedule_template_id: string;
      }>;
    }>("/leagues/presets"),
  randomTeamName: () =>
    apiRequest<{ city: string; name: string }>(
      "/leagues/random-team",
      { method: "POST" },
    ),
  resetRandomPool: () =>
    apiRequest<{ status: string }>(
      "/leagues/random-team/reset",
      { method: "POST" },
    ),
  createLeague: (payload: Record<string, unknown>) =>
    apiRequest<{
      league_id: string;
      display_name: string;
      mode: string;
      data_dir: string;
      teams_total: number;
    }>("/leagues/create", { method: "POST", body: payload }),
  bootstrapAdmin: (password: string) =>
    apiRequest<{ status: string }>("/admin/bootstrap", {
      method: "POST",
      body: { password },
      token: "",
    }),
  tuning: () =>
    apiRequest<{
      sections: Array<{
        label: string;
        sliders: Array<{
          key: string;
          label: string;
          description: string;
          min_value: number;
          max_value: number;
          step: number;
          fmt: string;
        }>;
      }>;
      defaults: Record<string, number>;
      overrides: Record<string, number>;
    }>("/tuning"),
  saveTuning: (overrides: Record<string, number>) =>
    apiRequest<{
      defaults: Record<string, number>;
      overrides: Record<string, number>;
    }>("/tuning", { method: "PUT", body: { overrides } }),
  resetTuning: () =>
    apiRequest<{
      defaults: Record<string, number>;
      overrides: Record<string, number>;
    }>("/tuning/reset", { method: "POST" }),
  leagueRecords: () =>
    apiRequest<{
      records: Record<string, Array<Record<string, unknown>>>;
    }>("/league/records"),
  teamRecords: (teamId: string) =>
    apiRequest<{
      team_id: string;
      records: Array<Record<string, unknown>>;
    }>(`/teams/${encodeURIComponent(teamId)}/records`),
  exportReports: (
    format: "csv" | "html" | "both" = "csv",
    include_pdf = true,
  ) =>
    apiRequest<Record<string, unknown>>("/exports/reports", {
      method: "POST",
      body: { format, include_pdf },
    }),
  exportAlmanac: () =>
    apiRequest<Record<string, unknown>>("/exports/almanac", {
      method: "POST",
    }),
  exportSnapshot: () =>
    apiRequest<Record<string, unknown>>("/exports/snapshot", {
      method: "POST",
    }),
  generateLogos: (
    options: { force_engine?: "openai" | "auto_logo" } = {},
  ) =>
    apiRequest<ExportJobStart>("/exports/logos", {
      method: "POST",
      body: { force_engine: options.force_engine },
    }),
  aiStatus: () =>
    apiRequest<{
      status: string;
      ok: boolean;
      message: string | null;
    }>("/ai/status"),
  setOpenAiKey: (api_key: string) =>
    apiRequest<{
      status: string;
      ok: boolean;
      message: string | null;
    }>("/ai/api-key", { method: "POST", body: { api_key } }),
  generateAvatars: (initial_creation: boolean = false) =>
    apiRequest<ExportJobStart>("/exports/avatars", {
      method: "POST",
      body: { initial_creation },
    }),
  getExportJob: (jobId: string) =>
    apiRequest<ExportJobStatus>(`/exports/jobs/${encodeURIComponent(jobId)}`),
  changeRequests: (statusFilter?: string) =>
    apiRequest<{
      count: number;
      requests: Array<Record<string, unknown>>;
    }>(`/change-requests${statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : ""}`),
  updateChangeRequest: (payload: {
    request_id: string;
    status: string;
    note?: string;
  }) =>
    apiRequest<{ request: Record<string, unknown> }>(
      "/change-requests/status",
      { method: "POST", body: payload },
    ),
  hallOfFame: () =>
    apiRequest<{
      inductees: Array<Record<string, unknown>>;
      candidates: Array<Record<string, unknown>>;
    }>("/hall-of-fame"),
  hofInduct: (player_id: string, note?: string) =>
    apiRequest<{ result: Record<string, unknown> }>("/hall-of-fame/induct", {
      method: "POST",
      body: { player_id, note },
    }),
  hofRemove: (player_id: string, reason?: string) =>
    apiRequest<{ result: Record<string, unknown> }>("/hall-of-fame/remove", {
      method: "POST",
      body: { player_id, reason },
    }),
  hofRefresh: () =>
    apiRequest<{ result: Record<string, unknown> }>(
      "/hall-of-fame/refresh",
      { method: "POST" },
    ),
  hofSettings: () =>
    apiRequest<{
      min_years_retired: number;
      score_threshold: number;
      defaults: { min_years_retired: number; score_threshold: number };
    }>("/hall-of-fame/settings"),
  hofSaveSettings: (payload: {
    min_years_retired: number;
    score_threshold: number;
  }) =>
    apiRequest<{
      min_years_retired: number;
      score_threshold: number;
      defaults: { min_years_retired: number; score_threshold: number };
    }>("/hall-of-fame/settings", { method: "PUT", body: payload }),
  financeQueue: (queueType?: string) =>
    apiRequest<{ count: number; rows: Array<Record<string, unknown>> }>(
      `/finance-queue${queueType ? `?queue_type=${encodeURIComponent(queueType)}` : ""}`,
    ),
  reviewFinanceQueue: (payload: {
    team_id: string;
    queue_type: string;
    item_id: string;
    review_status: string;
    notes?: string;
  }) =>
    apiRequest<{ row: Record<string, unknown> }>(
      "/finance-queue/review",
      { method: "POST", body: payload },
    ),
  applyFinanceQueue: () =>
    apiRequest<Record<string, unknown>>("/finance-queue/apply-approved", {
      method: "POST",
    }),
  commandCenter: () =>
    apiRequest<{
      generated_at_utc: string;
      league_id: string;
      phase: string;
      sim_date: string | null;
      overview: Record<string, number>;
      cards: Array<{
        card_id: string;
        title: string;
        severity: string;
        summary: string;
        count: number;
        items: Array<Record<string, unknown>>;
        actions: string[];
      }>;
    }>("/league/command-center"),
  commissionerSettings: () =>
    apiRequest<CommissionerSettings>("/commissioner/settings"),
  saveCommishTrade: (payload: Partial<CommissionerSettings["trade"]>) =>
    apiRequest<CommissionerSettings>("/commissioner/settings/trade", {
      method: "PUT",
      body: payload,
    }),
  saveCommishInjury: (level: string) =>
    apiRequest<CommissionerSettings>("/commissioner/settings/injury", {
      method: "PUT",
      body: { level },
    }),
  saveCommishFinance: (payload: Partial<CommissionerSettings["finance"]>) =>
    apiRequest<CommissionerSettings>("/commissioner/settings/finance", {
      method: "PUT",
      body: payload,
    }),
  saveCommishStrategy: (payload: {
    default_profile?: string;
    default_auto_reassign?: boolean;
    team_strategies?: Record<string, string>;
    team_auto_reassigns?: Record<string, boolean>;
  }) =>
    apiRequest<CommissionerSettings>(
      "/commissioner/settings/strategy",
      { method: "PUT", body: payload },
    ),
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
        ratings_context?: Record<string, RatingContextEntry>;
        overall_raw?: number | null;
        overall_display?: number | null;
        overall_stars_text?: string | null;
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
  getPlayerTraining: (playerId: string, teamId?: string) => {
    const qs = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
    return apiRequest<PlayerTrainingFocus>(
      `/players/${encodeURIComponent(playerId)}/training${qs}`,
    );
  },
  savePlayerTraining: (
    playerId: string,
    payload: {
      hitters: Record<string, number>;
      pitchers: Record<string, number>;
      team_id?: string;
    },
  ) => {
    const qs = payload.team_id
      ? `?team_id=${encodeURIComponent(payload.team_id)}`
      : "";
    const { team_id: _ignored, ...body } = payload;
    return apiRequest<PlayerTrainingFocus>(
      `/players/${encodeURIComponent(playerId)}/training${qs}`,
      { method: "PUT", body },
    );
  },
  resetPlayerTraining: (playerId: string, teamId?: string) => {
    const qs = teamId ? `?team_id=${encodeURIComponent(teamId)}` : "";
    return apiRequest<PlayerTrainingFocus>(
      `/players/${encodeURIComponent(playerId)}/training${qs}`,
      { method: "DELETE" },
    );
  },
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
  adminApproveTrade: (tradeId: string, force = false) =>
    apiRequest<{
      trade_id: string;
      status: string;
      forced: boolean;
      warnings: string[];
    }>(`/trades/${encodeURIComponent(tradeId)}/admin-approve`, {
      method: "POST",
      body: { force },
    }),
  adminVetoTrade: (tradeId: string, note = "") =>
    apiRequest<{ trade_id: string; status: string; note: string }>(
      `/trades/${encodeURIComponent(tradeId)}/veto`,
      { method: "POST", body: { note } },
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
  validateLineup: (
    teamId: string,
    vs: LineupVs,
    lineup: LineupRow[],
  ) =>
    apiRequest<{ ok: boolean; errors: string[]; warnings: string[] }>(
      `/teams/${encodeURIComponent(teamId)}/lineup/${vs}/validate`,
      { method: "POST", body: { lineup } },
    ),
  validateDepthChart: (teamId: string, chart: Record<string, string[]>) =>
    apiRequest<{ ok: boolean; errors: string[]; warnings: string[] }>(
      `/teams/${encodeURIComponent(teamId)}/depth-chart/validate`,
      { method: "POST", body: { chart } },
    ),
  depthChart: (teamId: string) =>
    apiRequest<{
      team_id: string;
      positions: string[];
      max_depth: number;
      chart: Record<string, string[]>;
    }>(`/teams/${encodeURIComponent(teamId)}/depth-chart`),
  saveDepthChart: (teamId: string, chart: Record<string, string[]>) =>
    apiRequest<{
      team_id: string;
      positions: string[];
      max_depth: number;
      chart: Record<string, string[]>;
    }>(`/teams/${encodeURIComponent(teamId)}/depth-chart`, {
      method: "PUT",
      body: { chart },
    }),
  offseasonChecklist: () =>
    apiRequest<{
      stages: Array<{
        id: string;
        label: string;
        description: string;
        done: boolean;
        done_at: string | null;
      }>;
      current_stage: string | null;
      all_done: boolean;
    }>("/offseason/checklist"),
  offseasonOverview: () =>
    apiRequest<Record<string, unknown>>("/offseason/overview"),
  offseasonStage: (stageId: string) =>
    apiRequest<Record<string, unknown>>(
      `/offseason/stage/${encodeURIComponent(stageId)}`,
    ),
  offseasonRun: () =>
    apiRequest<Record<string, unknown>>("/offseason/run-pipeline", {
      method: "POST",
    }),
  offseasonMark: (stage_id: string) =>
    apiRequest<Record<string, unknown>>("/offseason/stage/mark", {
      method: "POST",
      body: { stage_id },
    }),
  autoAssignTeam: (teamId: string) =>
    apiRequest<{ team_id: string; status: string }>(
      `/teams/${encodeURIComponent(teamId)}/auto-assign`,
      { method: "POST" },
    ),
  autoAssignAll: () =>
    apiRequest<{ status: string }>("/reassign/all", { method: "POST" }),
  financeStabilityRun: (payload: {
    seasons?: number;
    seed?: number;
    preset?: string;
  }) =>
    apiRequest<Record<string, unknown>>("/finance-stability/run", {
      method: "POST",
      body: payload,
    }),
  financeStabilityCompare: (payload: {
    seasons?: number;
    seed?: number;
    presets?: string[];
  }) =>
    apiRequest<Record<string, unknown>>("/finance-stability/compare", {
      method: "POST",
      body: payload,
    }),
  financeStabilityEvaluate: (season_metrics: Array<Record<string, unknown>>) =>
    apiRequest<Record<string, unknown>>("/finance-stability/evaluate", {
      method: "POST",
      body: { season_metrics },
    }),
  teamChangeRequests: (teamId: string) =>
    apiRequest<{
      team_id: string;
      count: number;
      requests: Array<Record<string, unknown>>;
    }>(`/teams/${encodeURIComponent(teamId)}/change-requests`),
  exportTeamChangeRequest: (
    teamId: string,
    payload: {
      owner_name: string;
      note: string;
      sections: { roster: boolean; lineups: boolean; pitching: boolean; depth: boolean };
    },
  ) =>
    apiRequest<{
      request_id: string;
      export_path: string;
      filename: string;
      summary: string;
      file_count: number;
    }>(`/teams/${encodeURIComponent(teamId)}/change-requests/export`, {
      method: "POST",
      body: payload,
    }),
  cancelTeamChangeRequest: (
    teamId: string,
    requestId: string,
    ownerName: string,
  ) =>
    apiRequest<{ request_id: string; export_path: string; filename: string }>(
      `/teams/${encodeURIComponent(teamId)}/change-requests/${encodeURIComponent(requestId)}/cancel`,
      { method: "POST", body: { owner_name: ownerName } },
    ),
  changeRequestDownloadUrl: (teamId: string, filename: string) => {
    const { apiBaseUrl } = getBridge();
    return `${apiBaseUrl}/teams/${encodeURIComponent(teamId)}/change-requests/download/${encodeURIComponent(filename)}`;
  },
  teamStats: (teamId: string) =>
    apiRequest<{
      team_id: string;
      columns: { batters: string[]; pitchers: string[]; team: string[] };
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
      team_totals: Record<string, number | string | null>;
    }>(`/teams/${encodeURIComponent(teamId)}/stats`),
  adminLeagueScheduleTemplates: () =>
    apiRequest<{
      templates: Array<{
        id: string;
        name: string;
        description: string;
        games_per_team: number;
      }>;
    }>("/admin-league/schedule-templates"),
  adminRegenerateSchedule: (template_id: string) =>
    apiRequest<{
      games: number;
      template_id: string;
      start_year: number;
      schedule_path: string;
    }>("/admin-league/regenerate-schedule", {
      method: "POST",
      body: { template_id },
    }),
  adminResetStats: () =>
    apiRequest<{ reset: boolean; path: string }>("/admin-league/reset-stats", {
      method: "POST",
    }),
  adminResetResults: () =>
    apiRequest<{ reset: boolean; games: number }>(
      "/admin-league/reset-results",
      { method: "POST" },
    ),
  draftSettings: () =>
    apiRequest<{
      rounds: number;
      pool_size: number;
      limits: {
        rounds: { min: number; max: number; default: number };
        pool_size: { min: number; max: number; default: number };
      };
    }>("/draft/settings"),
  saveDraftSettings: (rounds: number, pool_size: number) =>
    apiRequest<{ rounds: number; pool_size: number }>("/draft/settings", {
      method: "PUT",
      body: { rounds, pool_size },
    }),
  adminDraftInitialize: (year?: number, seed?: number) =>
    apiRequest<{ year: number; order: string[]; seed: number | null }>(
      "/draft/admin/initialize",
      { method: "POST", body: { year, seed } },
    ),
  adminDraftReset: (year?: number) =>
    apiRequest<{ year: number; reset: boolean }>("/draft/admin/reset", {
      method: "POST",
      body: { year },
    }),
  adminDraftGeneratePool: (year?: number) =>
    apiRequest<{ year: number; pool_size: number }>(
      "/draft/admin/generate-pool",
      { method: "POST", body: { year } },
    ),
  adminDraftManualPick: (player_id: string, year?: number) =>
    apiRequest<{
      year: number;
      round: number;
      overall: number;
      team_id: string;
      player_id: string;
    }>("/draft/admin/manual-pick", {
      method: "POST",
      body: { player_id, year },
    }),
  adminRepairLineups: () =>
    apiRequest<{ fixed: string[]; failed: string[] }>(
      "/admin-league/repair-lineups",
      { method: "POST" },
    ),
  adminCloneLeague: (league_id: string, display_name: string) =>
    apiRequest<{ league_id: string; display_name: string; path: string }>(
      "/admin-league/clone",
      { method: "POST", body: { league_id, display_name } },
    ),
  simulateExhibition: (home_team: string, away_team: string) =>
    apiRequest<{
      home_team: string;
      away_team: string;
      home: {
        score: number;
        batting: Array<{
          player_id: string;
          name: string;
          ab: number;
          h: number;
          bb: number;
          so: number;
          sb: number;
        }>;
        pitching: Array<{
          player_id: string;
          name: string;
          pitches: number;
          bb: number;
          so: number;
        }>;
      };
      away: {
        score: number;
        batting: Array<{
          player_id: string;
          name: string;
          ab: number;
          h: number;
          bb: number;
          so: number;
          sb: number;
        }>;
        pitching: Array<{
          player_id: string;
          name: string;
          pitches: number;
          bb: number;
          so: number;
        }>;
      };
      boxscore_path: string | null;
      debug_log: string[];
      field_positions: Record<string, string>;
    }>("/exhibition/simulate", {
      method: "POST",
      body: { home_team, away_team },
    }),
  helpManual: () =>
    apiRequest<{ format: string; source: string; content: string }>(
      "/help/manual",
    ),
  helpTutorials: () =>
    apiRequest<{
      count: number;
      tutorials: Array<{
        tutorial_id: string;
        title: string;
        summary: string;
        steps: Array<{ title: string; body_html: string }>;
      }>;
    }>("/help/tutorials"),
  helpLegacyManuals: () =>
    apiRequest<{
      manuals: Array<{ doc_id: string; filename: string; available: boolean }>;
    }>("/help/legacy-manuals"),
  helpLegacyManualUrl: (doc_id: string) => {
    const { apiBaseUrl } = getBridge();
    return `${apiBaseUrl}/help/legacy-manuals/${encodeURIComponent(doc_id)}`;
  },
  listParks: () =>
    apiRequest<{
      count: number;
      parks: Array<{
        park_id: string;
        name: string;
        year: number;
        lf: number | null;
        cf: number | null;
        rf: number | null;
        foul_territory: string | null;
        has_preview: boolean;
      }>;
    }>("/parks"),
  parkPreviewUrl: (park_id: string, year: number) => {
    const { apiBaseUrl } = getBridge();
    const qp = new URLSearchParams({
      park_id,
      year: String(year),
    });
    return `${apiBaseUrl}/parks/preview?${qp.toString()}`;
  },
};
