/**
 * Minimal fetch wrapper for the FastAPI sidecar.
 *
 * Every call automatically attaches the current bearer token -- either the
 * user session issued by `/auth/login` (preferred) or the per-launch Electron
 * token as a fallback for pre-login health checks.
 */

import { getBridge } from "./bridge";
import { useAuthStore } from "./auth-store";
import { firebaseEnabled, getIdToken } from "./firebase";

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
  /** Override the X-League-Id header for this one call (e.g. requesting to join
   *  a public league the user isn't active in yet). Defaults to activeLeagueId. */
  leagueId?: string;
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { apiBaseUrl, launchToken } = getBridge();
  const { token: sessionToken, activeLeagueId } = useAuthStore.getState();

  // Bearer precedence: explicit opts.token (incl. "" = no token) → Firebase ID
  // token (cloud) → legacy session/launch token (Electron / local sidecar).
  let bearer: string | undefined;
  if (opts.token !== undefined) {
    bearer = opts.token || undefined;
  } else {
    const fb = firebaseEnabled() ? await getIdToken() : null;
    bearer = fb ?? sessionToken ?? launchToken ?? undefined;
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (bearer) headers.Authorization = `Bearer ${bearer}`;
  // Tell the multi-tenant backend which league this request targets.
  const leagueHeader = opts.leagueId ?? activeLeagueId;
  if (leagueHeader) headers["X-League-Id"] = leagueHeader;

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

// --- Contracts ---

export interface ContractRecord {
  team_id: string;
  annual_salary: number;
  years_left: number;
  fa_year: number;
  guaranteed: boolean;
  buyout_guarantee: number;
  arb_eligible: boolean;
  service_time_days: number;
  options: Array<Record<string, unknown>>;
  incentives: Array<Record<string, unknown>>;
}

export interface ContractListRow {
  player_id: string;
  first_name: string;
  last_name: string;
  primary_position: string;
  is_pitcher: boolean;
  team_id: string;
  annual_salary: number;
  years_left: number;
  fa_year: number;
  guaranteed: boolean;
  buyout_guarantee: number;
  arb_eligible: boolean;
  service_time_days: number;
  pending_options: number;
  expiring_this_year: boolean;
}

export interface ContractListResponse {
  current_year: number;
  count: number;
  contracts: ContractListRow[];
}

// --- All-Star Game ---

export interface AllStarPlayer {
  player_id: string;
  team_id: string;
  first_name: string;
  last_name: string;
  position: string;
  stats: Record<string, number | string | null>;
}

export interface AllStarSquad {
  team_ids: string[];
  hitters: AllStarPlayer[];
  pitchers: AllStarPlayer[];
}

export interface AllStarMvp {
  player_id: string;
  team_id: string;
  name: string;
  position: string;
  line: string;
}

export interface AllStarGame {
  year: number;
  played_at?: string;
  home_squad: string;
  away_squad: string;
  home_runs: number;
  away_runs: number;
  winner: string;
  mvp: AllStarMvp | null;
  squads: Record<string, AllStarSquad>;
  skipped?: boolean;
  reason?: string;
}

export interface AllStarHistory {
  count: number;
  games: AllStarGame[];
}

// --- Awards ---

export interface AwardWinner {
  award: string;
  player_id: string;
  player_name: string;
  metric: string;
}

export interface AwardSeason {
  season_id: string;
  league_year: number | null;
  awards: AwardWinner[];
}

export interface AwardListResponse {
  seasons: AwardSeason[];
}

export interface ExtensionEvaluation {
  decision: "accepted" | "countered" | "rejected";
  fair_market_salary: number;
  fair_market_years: number;
  counter_salary: number | null;
  counter_years: number | null;
  reason: string;
  service_tier: "pre_arb" | "arbitration" | "free_agent";
  current_annual_salary?: number;
  current_years_left?: number;
  service_time_days?: number;
  player_id?: string;
  eligibility?: ExtensionEligibility;
  /** Payroll impact of this extension (the raise over the current salary). */
  payroll_impact?: PayrollOutlook | null;
}

export interface ExtensionEligibility {
  eligible: boolean;
  reason: string;
  code:
    | ""
    | "phase_blocked"
    | "fa_year_lockout"
    | "too_many_years_left"
    | "cooldown";
  cooldown_days_remaining: number | null;
}

export interface ExtensionRejection {
  code: "countered" | "rejected" | ExtensionEligibility["code"];
  message: string;
  player_id: string;
  negotiation?: ExtensionEvaluation;
  eligibility?: ExtensionEligibility;
  current_annual_salary: number;
  current_years_left: number;
}

export interface PayrollWarning {
  violations: Record<string, Record<string, unknown>>;
  mode: string;
  level: string;
  acknowledged: boolean;
}

export interface SignFreeAgentResponse {
  team_id: string;
  player_id: string;
  level: string;
  signed: boolean;
  annual_salary: number;
  years: number;
  contract: ContractRecord | null;
  payroll_warning: PayrollWarning | null;
  negotiation: ExtensionEvaluation | null;
  forced: boolean;
}

export interface CompetingBid {
  team_id: string;
  salary: number;
}

export interface FreeAgentOfferEvaluation {
  player_id: string;
  fair_market_salary: number;
  fair_market_years: number;
  decision: "accepted" | "countered" | "rejected";
  counter_salary: number | null;
  counter_years: number | null;
  reason: string;
  service_tier: "pre_arb" | "arbitration" | "free_agent";
  competing_bids: CompetingBid[];
  /** Payroll/tax/solvency consequences of this offer for the caller's team.
   *  Null when the caller has no team or finance data is unavailable. */
  payroll_impact: PayrollOutlook | null;
  phase_gate: { code: string; message: string; phase: string } | null;
}

export interface FreeAgentSignRejection {
  code: "countered" | "rejected" | "fa_window_closed" | "payroll_violation";
  message: string;
  player_id?: string;
  negotiation?: ExtensionEvaluation;
  competing_bids?: CompetingBid[];
  phase?: string;
  violations?: Record<string, Record<string, unknown>>;
  mode?: string;
  level?: string;
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
    finance_ai_tuning: Record<string, number>;
  };
  scouting: {
    league_id: string;
    enabled: boolean;
    base_monthly_credits: number;
    finance_off_multiplier: number;
    monthly_decay: number;
    passive_gain: number;
    max_banked_credits: number;
    auto_spend_cap: number;
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
    finance_modules: Array<{
      id: string;
      label: string;
      help: string;
      levels: string[];
      /** Per-level plain-language descriptions, keyed by level token. */
      level_help?: Record<string, string>;
    }>;
    finance_ai_tuning_defaults: Record<string, number>;
    finance_preset_profiles?: Record<
      string,
      {
        enabled: boolean;
        enforcement_mode: string;
        modules: Record<string, string>;
      }
    >;
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
  games_remaining?: number;
  status?: "clinched_division" | "leader" | "in_race" | "eliminated";
  magic_number?: number;
  // Playoff picture (#2): "division" = holds a division-leader playoff spot;
  // "wildcard" = currently in a wildcard spot. gb_wildcard = games back of the
  // last wildcard spot for chasers.
  playoff_spot?: "division" | "wildcard";
  gb_wildcard?: string;
}

export interface LeagueStandingsDivision {
  division: string;
  teams: LeagueStandingsRow[];
  league?: string | null;
}

export interface LeagueStandings {
  divisions: LeagueStandingsDivision[];
  // Ordered, distinct leagues (AL/NL split). Empty/absent for a single pool.
  leagues?: string[];
  playoff_teams_per_league?: number;
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

export interface ScheduleMarkers {
  today: string;
  season_start: string | null;
  season_end: string | null;
  all_star_break: string[];
  trade_deadline: string;
  draft_date: string | null;
}

export interface ScheduleList {
  games: ScheduleGame[];
  count: number;
  markers?: ScheduleMarkers;
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

export interface TradeCpuEvaluation {
  team_id: string;
  action: "accept" | "reject" | "counter";
  total_score: number;
  threshold: number;
  value_delta: number;
  fit_delta: number;
  timeline_delta: number;
  strategy_profile: string;
  competitive_window: string;
  reasons: string[];
}

export interface TradeReversal {
  note: string;
  from_team: string;
  to_team: string;
  by: string;
}

export interface TradeRecord {
  trade_id: string;
  from_team: string;
  to_team: string;
  status: string;
  initiated_by: "human" | "cpu";
  cpu_eval: TradeCpuEvaluation | null;
  reversal?: TradeReversal | null;
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

export interface TradeDeadline {
  deadline_date: string;
  current_sim_date: string;
  days_remaining: number;
  is_past: boolean;
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
  /** Round count configured for this draft (from draft settings). Used by
   *  the UI to detect "draft complete" once ``round`` advances past it. */
  configured_rounds?: number;
  configured_pool_size?: number;
  /** Backend-authoritative fields. With qualifying-offer compensation picks
   *  the draft order is non-uniform per round, so a client-side modulo over
   *  ``order`` is wrong — prefer these when present. */
  team_on_clock?: string | null;
  draft_complete?: boolean;
  total_picks?: number;
  has_compensation?: boolean;
}

export interface DraftResults {
  year: number;
  count: number;
  picks: DraftSelection[];
}

export interface DraftPickResult {
  year: number;
  round: number;
  overall: number;
  team_id: string;
  player_id: string;
  commit?: {
    added?: boolean;
    assigned?: boolean;
    note?: string | null;
    player_name?: string;
    error?: string;
  };
}

export interface DraftProspect {
  player_id: string;
  first_name: string;
  last_name: string;
  primary_position: string;
  is_pitcher: boolean;
  bats: string;
  throws: string;
  birthdate?: string | null;
  age?: number | null;
  overall: number;
  available: boolean;
  ratings: Record<string, number | string | null>;
}

export interface DraftPool {
  year: number;
  count: number;
  prospects: DraftProspect[];
}

export interface DraftAutoAdvanceResult {
  year: number;
  stop: "my_pick" | "end_of_round" | "end_of_draft";
  target_team: string | null;
  picks: DraftPickResult[];
  picks_made: number;
  draft_complete: boolean;
  team_on_clock: string | null;
  round: number;
  overall_pick: number;
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

export interface PlayoffSimResult {
  bracket: Playoffs;
  champion: string | null;
  complete: boolean;
  /** False when the bracket was already finished (the call was a no-op). */
  changed: boolean;
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
  /** Per-module levels (off/basic/...) for the league, so the UI can reveal the
   * owner actions the selected finance model enables. May be absent on older
   * servers. e.g. { owner_budgets: "basic", gm_arbitration: "off", ... } */
  modules?: Record<string, string>;
}

export interface ArbitrationPlayer {
  player_id: string;
  player_name: string;
  years_left: number;
  service_time_days: number;
  current_salary: number;
  projected_salary: number;
  recommended_raise_pct: number;
  recommended_action: string;
  decision_code?: string;
  queued_action?: string | null;
  queued_status?: string | null;
}

/**
 * Payroll-vs-threshold outlook (GET .../finance/payroll-context) and the
 * `payroll_impact` block on FA offer previews. Numeric fields are only
 * present when `active` is true (finance on + payroll rules basic/mlb_like).
 */
export interface PayrollOutlook {
  team_id: string;
  active: boolean;
  /** Payroll numbers are present (finance enabled) even if enforcement is off. */
  info?: boolean;
  finance_enabled: boolean;
  enforcement: string; // "on" | "off"
  preset: string;
  level: string; // "basic" | "mlb_like" | ...
  extra_annual_salary: number;
  signing_bonus: number;
  payroll?: number;
  projected_payroll?: number;
  threshold?: number;
  floor?: number;
  over_threshold?: number;
  under_floor?: number;
  headroom?: number;
  estimated_tax?: number;
  estimated_floor_fee?: number;
  zone?: "safe" | "over_threshold" | "under_floor";
  cash_on_hand?: number;
  debt?: number;
  cash_after_bonus?: number;
  debt_cap?: number;
  projected_debt?: number;
  opening_day_solvent?: boolean;
}

export interface FaOffer {
  team_id: string;
  years: number;
  annual_salary: number;
  signing_bonus: number;
  level: string;
  date: string;
  is_cpu: boolean;
}

export interface FaNegotiationResolution {
  outcome: "signed" | "no_deal" | "withdrawn";
  signed_team?: string;
  years?: number;
  annual_salary?: number;
  signing_bonus?: number;
  is_cpu?: boolean;
  date?: string;
  early?: boolean;
}

export interface FaNegotiationSummary {
  player_id: string;
  player_name?: string;
  status: "open" | "resolved";
  deadline_date: string;
  your_offer: FaOffer | null;
  leading_offer: FaOffer | null;
  offer_count: number;
  resolution: FaNegotiationResolution | null;
}

export interface FaWindowSigned {
  player_id: string;
  player_name: string;
  team_id: string;
  annual_salary: number;
  years: number;
}

export interface FaWindowLeader {
  player_id: string;
  player_name: string;
  leader_team: string;
  leader_is_cpu: boolean;
  leader_salary: number;
  leader_years: number;
  teams_offering: string[];
}

export interface FaWindowLog {
  day: number;
  date: string;
  signed: FaWindowSigned[];
  leaders?: FaWindowLeader[];
  cpu_seeded?: number;
  message?: string;
}

export interface FaWindowStatus {
  finance_enabled: boolean;
  exists: boolean;
  status?: string | null;
  day?: number | null;
  total_days: number;
  start_date?: string | null;
  deadline_date?: string | null;
  latest?: FaWindowLog | null;
  sweep_locked: boolean;
  // Multi-owner participation this window.
  human_teams?: string[];
  participants?: string[];
  waiting?: string[];
}

export interface SeasonReadinessTeam {
  team_id: string;
  ready: boolean;
  issues: string[];
}

export interface SeasonReadiness {
  teams: SeasonReadinessTeam[];
  all_ready: boolean;
  human_team_count: number;
  unready: string[];
}

export interface SeasonActionItem {
  kind: string;
  severity: "action" | "info";
  title: string;
  detail: string;
  count: number;
  href: string;
}

export interface SeasonActionItems {
  team_id: string | null;
  items: SeasonActionItem[];
  count: number;
  deadline: string | null;
}

export interface SubmitFaOfferResponse {
  player_id: string;
  negotiation: {
    player_id: string;
    opened_date: string;
    deadline_date: string;
    status: string;
    offers: FaOffer[];
    resolution: FaNegotiationResolution | null;
  };
  payroll_impact: PayrollOutlook | null;
}

export type FinanceTodoSeverity = "info" | "warning" | "critical";

export interface FinanceTodoItem {
  id: string;
  severity: FinanceTodoSeverity;
  label: string;
  to: string;
}

export interface FinanceTodo {
  team_id: string;
  phase: string;
  finance_enabled: boolean;
  items: FinanceTodoItem[];
}

export interface QualifyingOfferRecord {
  player_id: string;
  team_id: string;
  qo_value: number;
  salary?: number;
  decision: string; // pending | accepted | declined | not_tendered
  signed_with: string | null;
  comp_awarded: boolean;
}

export interface TeamQualifyingOffers {
  team_id: string;
  year: number;
  offers: QualifyingOfferRecord[];
}

/** One pending owner decision awaiting commissioner review. */
export interface FinanceQueueRow {
  team_id: string;
  queue_type: string;
  item_id: string;
  action: string;
  notes: string;
  updated_at: string;
  review_status: string;
  applied: boolean;
  applied_at: string;
  payload: Record<string, unknown>;
  /** Enriched by the API: display name for item_id (a player id). */
  player_name?: string;
  current_salary?: number | null;
  projected_salary?: number | null;
  /** Plain-language version of `action`. */
  action_label?: string;
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
  /** Readable display name (Firestore handle) when available; else = username. */
  display_name?: string;
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
  /** Raw contract fields for owner option/renew actions (may be absent). */
  contract_meta?: {
    team_id: string;
    annual_salary: number;
    service_time_days: number;
    arb_eligible: boolean;
    options: Array<{
      type?: string;
      label?: string;
      salary?: number;
      decision?: string;
      buyout?: number;
    }>;
  };
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
  /** Per-rating deltas from the most recent spring training camp. */
  spring_training_gains?: {
    year?: number | string | null;
    focus?: string | null;
    changes?: Record<string, number>;
  };
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
  /** Per-step "this preseason workflow has been completed" flags read
   *  from season_progress.json. The UI uses these to lock out repeat
   *  runs of the corresponding preseason buttons. */
  preseason_done?: {
    free_agency?: boolean;
    training_camp?: boolean;
    schedule?: boolean;
  };
  played_dates?: string[];
  errors?: string[];
  new_phase?: SeasonPhase;
  /** True when the simulator hit the draft date — owner must run the
   *  draft in /draft before any more days will advance. */
  draft_blocked?: boolean;
  /** Authoritative state flags from the backend (don't infer these from
   *  current_date/draft_date). `season_complete` = the whole regular-season
   *  schedule is played; `draft_completed` = the amateur draft is committed. */
  season_complete?: boolean;
  draft_completed?: boolean;
  /** True only in PLAYOFFS once a champion is crowned. Used to gate the
   *  Advance Phase button so it can't be clicked on an unfinished bracket. */
  playoffs_complete?: boolean;
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
  /** Notification events emitted while this batch ran. */
  notifications?: NotificationEvent[];
  /** Set when the multi-day sim was stopped early because a notification
   *  rule with stop_sim=true fired. The string is the rule's title. */
  sim_stopped_reason?: string | null;
}

// --- Notifications ---

export interface NotificationRuleSpec {
  id: string;
  label: string;
  default_notify: boolean;
  default_stop: boolean;
  threshold?: number | null;
  threshold_label?: string | null;
  threshold_min?: number | null;
  threshold_max?: number | null;
}

export interface NotificationCategory {
  id: string;
  label: string;
  rules: NotificationRuleSpec[];
}

export interface NotificationRulePayload {
  enabled: boolean;
  notify: boolean;
  stop_sim: boolean;
  threshold?: number | null;
}

export interface NotificationSettings {
  team_id: string;
  rules: Record<string, NotificationRulePayload>;
}

export interface NotificationEvent {
  rule_id: string;
  severity: "info" | "warning" | "critical";
  title: string;
  message: string;
  sim_date?: string | null;
  timestamp: string;
  payload?: Record<string, unknown>;
  stop_sim: boolean;
  notify: boolean;
}

export interface SimProgress {
  active: boolean;
  target: number;
  played: number;
  elapsed_seconds: number;
  status: "idle" | "running" | "done" | "error";
  run_id: number;
  result: SeasonState | null;
  error: string | null;
  cancel_requested?: boolean;
}

/**
 * Drives a background sim to completion. The start endpoint returns
 * immediately ({status:"running"}); we then poll /season/sim-progress until
 * the job reports done (→ return its final state) or error (→ throw). This
 * keeps every sim request short, so a long multi-day jump never trips the
 * ~60s Firebase Hosting proxy cap that produced false "Action failed" errors.
 *
 * Transient poll failures (a 429 from the CPU-pegged instance, a momentary
 * network blip) are swallowed and retried — only a real job error or an
 * overall timeout rejects.
 */
async function runBackgroundSim(
  start: () => Promise<{ status: string; run_id: number }>,
): Promise<SeasonState> {
  const started = await start();
  // A synchronous/fast path (or an older backend) may already return the
  // finished state instead of a "running" handle — pass it straight through.
  if ((started as unknown as SeasonState)?.phase && started.status !== "running") {
    return started as unknown as SeasonState;
  }

  const POLL_MS = 1200;
  const MAX_WAIT_MS = 20 * 60 * 1000; // 20 min hard ceiling
  const deadline = Date.now() + MAX_WAIT_MS;
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  // Tolerate a few consecutive poll failures before giving up — the instance
  // can briefly 429 while the sim pegs its single CPU.
  let consecutiveErrors = 0;
  for (;;) {
    if (Date.now() > deadline) {
      throw new Error(
        "The simulation is taking longer than expected. It may still be " +
          "running — refresh the Season page in a moment to see the result.",
      );
    }
    await sleep(POLL_MS);
    let prog: SimProgress;
    try {
      prog = await api.seasonSimProgress();
      consecutiveErrors = 0;
    } catch {
      if (++consecutiveErrors > 25) {
        throw new Error(
          "Lost contact with the simulation service. Refresh the Season " +
            "page to check whether the sim completed.",
        );
      }
      continue;
    }
    if (prog.run_id !== started.run_id) {
      // A different run took over the slot (another tab/owner) — stop tracking
      // ours rather than report a foreign run's result as if it were this one.
      throw new Error("This simulation was superseded by another run.");
    }
    if (prog.status === "done" && prog.result) return prog.result;
    if (prog.status === "error") {
      throw new Error(prog.error || "Simulation failed.");
    }
  }
}

export const api = {
  // App-specific health path (not /healthz, which network intermediaries
  // often intercept — see api/app.py). /healthz stays for platform checks.
  //
  // ``token: ""`` skips the Firebase ID-token fetch: /meta/app-status is a
  // public readiness probe, and awaiting getIdToken() here means a stalled
  // token refresh would hang the startup splash forever (no fetch, no error).
  // ``signal`` lets the caller bound the request with a timeout.
  health: (signal?: AbortSignal) =>
    apiRequest<HealthPayload>("/meta/app-status", { token: "", signal }),
  login: (username: string, password: string) =>
    apiRequest<LoginPayload>("/auth/login", {
      method: "POST",
      body: { username, password },
    }),

  // --- Multi-tenant (Firebase-authenticated) ---
  accountSignup: (handle: string, pkg: "commissioner" | "owner") =>
    apiRequest<{ uid: string; handle: string; package: string; email: string }>(
      "/account/signup",
      { method: "POST", body: { handle, package: pkg } },
    ),
  accountMe: () =>
    apiRequest<{
      account: { handle?: string; package?: string; email?: string } | null;
      leagues: Array<{
        league_id: string;
        role: string;
        team_id: string;
        status: string;
        display_name: string | null;
        visibility: string | null;
      }>;
      super_admin?: boolean;
      all_leagues?: Array<{
        league_id: string;
        display_name: string | null;
        visibility: string | null;
        commissioner_uid: string | null;
      }>;
    }>("/account/me"),
  listPublicLeagues: () =>
    apiRequest<{ leagues: Array<{ league_id: string; display_name: string }> }>(
      "/leagues/public",
    ),
  createLeagueAsCommissioner: (payload: Record<string, unknown>) =>
    apiRequest<{
      league_id: string;
      display_name: string;
      visibility: string;
      commissioner_uid: string;
      team_id: string;
      teams_total: number;
    }>("/leagues/create-as-commissioner", { method: "POST", body: payload }),
  generateInvite: (team_id?: string) =>
    apiRequest<{ code: string; league_id: string; team_id: string; status: string }>(
      "/invites",
      { method: "POST", body: { team_id: team_id ?? "" } },
    ),
  listInvites: () =>
    apiRequest<{
      invites: Array<{
        code: string;
        team_id: string;
        status: string;
        uses: number;
        max_uses: number;
      }>;
    }>("/invites"),
  revokeInvite: (code: string) =>
    apiRequest<{ code: string; status: string }>(
      `/invites/${encodeURIComponent(code)}/revoke`,
      { method: "POST" },
    ),
  redeemInvite: (code: string) =>
    apiRequest<{ league_id: string; team_id: string; status: string }>(
      "/invites/redeem",
      { method: "POST", body: { code } },
    ),
  requestToJoin: (leagueId: string, note?: string) =>
    apiRequest<{ request_id: string; status: string }>("/join-requests", {
      method: "POST",
      body: { note: note ?? "" },
      leagueId,
    }),
  listJoinRequests: () =>
    apiRequest<{
      requests: Array<{ request_id: string; uid: string; handle: string; note: string }>;
    }>("/join-requests"),
  approveJoinRequest: (request_id: string, team_id: string) =>
    apiRequest<{ request_id: string; status: string; team_id: string }>(
      `/join-requests/${encodeURIComponent(request_id)}/approve`,
      { method: "POST", body: { team_id } },
    ),
  denyJoinRequest: (request_id: string) =>
    apiRequest<{ request_id: string; status: string }>(
      `/join-requests/${encodeURIComponent(request_id)}/deny`,
      { method: "POST" },
    ),
  assignMemberTeam: (uid: string, team_id: string) =>
    apiRequest<{ uid: string; team_id: string; status: string }>(
      `/members/${encodeURIComponent(uid)}/assign-team`,
      { method: "POST", body: { team_id } },
    ),
  /** Super-admin: regenerate one player's AI avatar (spot-check before a full run). */
  regeneratePlayerAvatar: (playerId: string) =>
    apiRequest<{ player_id: string; ok: boolean }>(
      `/players/${encodeURIComponent(playerId)}/avatar/regenerate`,
      { method: "POST" },
    ),
  /** Super-admin: permanently delete ANY league (control plane + game data + GCS). */
  platformDeleteLeague: (leagueId: string) =>
    apiRequest<{ deleted: boolean; league_id: string; errors: string[] }>(
      `/platform/leagues/${encodeURIComponent(leagueId)}`,
      { method: "DELETE" },
    ),
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
  archiveLeague: (leagueId: string) =>
    apiRequest<{ archived: boolean; league_id: string; status: string }>(
      `/leagues/${encodeURIComponent(leagueId)}/archive`,
      { method: "POST" },
    ),
  unarchiveLeague: (leagueId: string) =>
    apiRequest<{ archived: boolean; league_id: string; status: string }>(
      `/leagues/${encodeURIComponent(leagueId)}/unarchive`,
      { method: "POST" },
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
  teamRosterCompliance: (teamId: string) =>
    apiRequest<{
      ok: boolean;
      errors: string[];
      warnings: string[];
      counts: { act: number; aaa: number; low: number; dl: number; ir: number };
      caps: { act: number; aaa: number; low: number };
    }>(`/teams/${encodeURIComponent(teamId)}/roster/compliance`),
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
  autofillLineup: (teamId: string, vs?: "lhp" | "rhp") =>
    apiRequest<{ team_id: string; lhp: Lineup; rhp: Lineup }>(
      `/teams/${encodeURIComponent(teamId)}/lineup/autofill${vs ? `?vs=${vs}` : ""}`,
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
  /** Re-frame existing logos in place (trim margins) — no AI, instant. */
  normalizeLogos: () =>
    apiRequest<ExportJobStart>("/exports/logos/normalize", { method: "POST" }),
  aiStatus: () =>
    apiRequest<{
      status: string;
      ok: boolean;
      message: string | null;
      renderer_ok?: boolean;
      openai?: { status: string; ok: boolean; message: string | null };
      vertex?: { status: string; ok: boolean; message: string | null };
    }>("/ai/status"),
  setOpenAiKey: (api_key: string) =>
    apiRequest<{
      status: string;
      ok: boolean;
      message: string | null;
    }>("/ai/api-key", { method: "POST", body: { api_key } }),
  generateAvatars: (
    initial_creation: boolean = false,
    engine?: "ai" | "template",
  ) =>
    apiRequest<ExportJobStart>("/exports/avatars", {
      method: "POST",
      body: { initial_creation, engine },
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
    apiRequest<{ count: number; rows: FinanceQueueRow[] }>(
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
  saveCommishScouting: (payload: Partial<CommissionerSettings["scouting"]>) =>
    apiRequest<CommissionerSettings>("/commissioner/settings/scouting", {
      method: "PUT",
      body: payload,
    }),
  notificationSchema: () =>
    apiRequest<{ categories: NotificationCategory[] }>("/notifications/schema"),
  notificationSettings: (teamId: string) =>
    apiRequest<NotificationSettings>(
      `/notifications/settings/${encodeURIComponent(teamId)}`,
    ),
  saveNotificationSettings: (
    teamId: string,
    payload: { rules: Record<string, NotificationRulePayload> },
  ) =>
    apiRequest<NotificationSettings>(
      `/notifications/settings/${encodeURIComponent(teamId)}`,
      { method: "PUT", body: payload },
    ),
  notificationHistory: (teamId: string, limit = 100) =>
    apiRequest<{
      team_id: string;
      count: number;
      events: NotificationEvent[];
    }>(
      `/notifications/history/${encodeURIComponent(teamId)}?limit=${limit}`,
    ),
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
        overall_raw?: number | null;
        overall_display?: number | null;
        overall_stars_text?: string | null;
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
    payload: {
      player_id: string;
      level: "ACT" | "AAA" | "LOW";
      annual_salary?: number;
      years?: number;
      signing_bonus?: number;
      acknowledge_warning?: boolean;
      force?: boolean;
    },
  ) =>
    apiRequest<SignFreeAgentResponse>(
      `/teams/${encodeURIComponent(teamId)}/sign`,
      { method: "POST", body: payload },
    ),
  evaluateFreeAgentOffer: (
    playerId: string,
    payload: {
      years?: number;
      annual_salary?: number;
      signing_bonus?: number;
      team_id?: string;
    },
  ) =>
    apiRequest<FreeAgentOfferEvaluation>(
      `/free-agents/${encodeURIComponent(playerId)}/evaluate-offer`,
      { method: "POST", body: payload },
    ),
  submitFaOffer: (
    playerId: string,
    payload: {
      team_id: string;
      years?: number;
      annual_salary?: number;
      signing_bonus?: number;
      level?: "ACT" | "AAA" | "LOW";
    },
  ) =>
    apiRequest<SubmitFaOfferResponse>(
      `/free-agents/${encodeURIComponent(playerId)}/offer`,
      { method: "POST", body: payload },
    ),
  listFaNegotiations: (teamId?: string) =>
    apiRequest<{ team_id: string; negotiations: FaNegotiationSummary[] }>(
      `/free-agents/negotiations${teamId ? `?team_id=${encodeURIComponent(teamId)}` : ""}`,
    ),
  withdrawFaOffer: (playerId: string, teamId?: string) =>
    apiRequest<{ withdrawn: boolean }>(
      `/free-agents/${encodeURIComponent(playerId)}/offer${teamId ? `?team_id=${encodeURIComponent(teamId)}` : ""}`,
      { method: "DELETE" },
    ),
  extendContract: (
    playerId: string,
    payload: {
      additional_years?: number;
      annual_salary?: number;
      guaranteed?: boolean;
      buyout_guarantee?: number;
      force?: boolean;
    },
  ) =>
    apiRequest<{
      player_id: string;
      extended_by: string;
      contract: ContractRecord;
      negotiation: ExtensionEvaluation | null;
      forced: boolean;
    }>(
      `/contracts/${encodeURIComponent(playerId)}/extend`,
      { method: "POST", body: payload },
    ),
  /** Owner: exercise/decline a contract option (advanced contracts model). */
  decideContractOption: (
    playerId: string,
    decision: "exercised" | "declined",
    optionIndex = 0,
  ) =>
    apiRequest<{ player_id: string; decision: string; option_index: number; contract: ContractRecord }>(
      `/contracts/${encodeURIComponent(playerId)}/option`,
      { method: "POST", body: { decision, option_index: optionIndex } },
    ),
  /** Owner: renew a pre-arb player's salary (advanced contracts model). */
  renewContract: (playerId: string, annualSalary: number) =>
    apiRequest<{ renewed: boolean; player_id: string; annual_salary: number; team_id: string; message?: string }>(
      `/contracts/${encodeURIComponent(playerId)}/renew`,
      { method: "POST", body: { annual_salary: annualSalary } },
    ),
  evaluateExtension: (
    playerId: string,
    payload: { years?: number; annual_salary?: number; team_id?: string },
  ) =>
    apiRequest<ExtensionEvaluation>(
      `/contracts/${encodeURIComponent(playerId)}/evaluate-extension`,
      { method: "POST", body: payload },
    ),
  listAwards: (year?: number) => {
    const qs = year ? `?year=${year}` : "";
    return apiRequest<AwardListResponse>(`/awards${qs}`);
  },
  listAllStarGames: () => apiRequest<AllStarHistory>("/all-star"),
  getAllStarGame: (year: number) => apiRequest<AllStarGame>(`/all-star/${year}`),
  triggerAllStarGame: (year: number, opts?: { force?: boolean; seed?: number }) =>
    apiRequest<AllStarGame>(`/all-star/${year}/play`, {
      method: "POST",
      body: { force: opts?.force, seed: opts?.seed },
    }),
  listContracts: (opts?: { team_id?: string; expiring_only?: boolean }) => {
    const params = new URLSearchParams();
    if (opts?.team_id) params.set("team_id", opts.team_id);
    if (opts?.expiring_only) params.set("expiring_only", "true");
    const qs = params.toString();
    return apiRequest<ContractListResponse>(`/contracts${qs ? `?${qs}` : ""}`);
  },
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
      categories: Array<{ id: string; count: number }>;
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
  getLeagueTraining: () =>
    apiRequest<{
      league_id: string;
      tracks: { hitters: string[]; pitchers: string[] };
      hitters: Record<string, number>;
      pitchers: Record<string, number>;
    }>("/training/league"),
  saveLeagueTraining: (payload: {
    hitters: Record<string, number>;
    pitchers: Record<string, number>;
  }) =>
    apiRequest<{
      league_id: string;
      tracks: { hitters: string[]; pitchers: string[] };
      hitters: Record<string, number>;
      pitchers: Record<string, number>;
    }>("/training/league", { method: "PUT", body: payload }),
  preseasonListUnsigned: (run_cpu = true) =>
    apiRequest<{
      unsigned_count: number;
      unsigned_names: string[];
      cpu_signed: number;
      cpu_rounds: number;
      cpu_applied: boolean;
      cpu_running?: boolean;
    }>("/season/preseason/list-unsigned", {
      method: "POST",
      body: { run_cpu },
    }),
  faWindowState: () => apiRequest<FaWindowStatus>("/season/fa-window"),
  faWindowAdvanceDay: () =>
    apiRequest<{ result: { ok: boolean; signed?: FaWindowSigned[] }; window: FaWindowStatus }>(
      "/season/fa-window/advance-day",
      { method: "POST" },
    ),
  seasonReadiness: () => apiRequest<SeasonReadiness>("/season/readiness"),
  seasonActionItems: () =>
    apiRequest<SeasonActionItems>("/season/action-items"),
  seasonReadinessCpuFill: (teamId: string) =>
    apiRequest<{
      team_id: string;
      ready: boolean;
      issues: string[];
      readiness: SeasonReadiness;
    }>(
      `/season/readiness/cpu-fill?team_id=${encodeURIComponent(teamId)}`,
      { method: "POST" },
    ),
  getSeasonDeadline: () =>
    apiRequest<{ deadline: string | null }>("/season/deadline"),
  setSeasonDeadline: (deadline: string | null) =>
    apiRequest<{ deadline: string | null }>("/season/deadline", {
      method: "POST",
      body: { deadline },
    }),
  preseasonTrainingCamp: () =>
    apiRequest<{
      players_processed: number;
      top_gainers: Array<{
        player_id: string;
        name: string;
        focus: string;
        total_gain: number;
      }>;
    }>("/season/preseason/training-camp", { method: "POST" }),
  seasonState: () => apiRequest<SeasonState>("/season/state"),
  seasonSimProgress: () =>
    apiRequest<SimProgress>("/season/sim-progress"),
  seasonSimCancel: () =>
    apiRequest<{ cancel_requested: boolean; run_id: number }>(
      "/season/sim-cancel",
      { method: "POST" },
    ),
  // Each sim starts a background job and then resolves with the final state
  // once polling sees it finish — so the caller (useSimMutation) is unchanged.
  seasonSimulateDay: () =>
    runBackgroundSim(() =>
      apiRequest<{ status: string; run_id: number }>("/season/simulate/day", {
        method: "POST",
      }),
    ),
  seasonSimulateWeek: () =>
    runBackgroundSim(() =>
      apiRequest<{ status: string; run_id: number }>("/season/simulate/week", {
        method: "POST",
      }),
    ),
  seasonSimulateMonth: () =>
    runBackgroundSim(() =>
      apiRequest<{ status: string; run_id: number }>("/season/simulate/month", {
        method: "POST",
      }),
    ),
  seasonSimulateDays: (n: number) =>
    runBackgroundSim(() =>
      apiRequest<{ status: string; run_id: number }>("/season/simulate/days", {
        method: "POST",
        body: { n },
      }),
    ),
  seasonSimulateToDraft: () =>
    runBackgroundSim(() =>
      apiRequest<{ status: string; run_id: number }>(
        "/season/simulate/to-draft",
        { method: "POST" },
      ),
    ),
  seasonSimulateToPlayoffs: () =>
    runBackgroundSim(() =>
      apiRequest<{ status: string; run_id: number }>(
        "/season/simulate/to-playoffs",
        { method: "POST" },
      ),
    ),
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
  /** Owner action: set this team's budget targets (training/scouting/
   * development/facilities). Rejected (409) if finance/owner_budgets is off. */
  updateTeamBudgets: (teamId: string, budgets: Record<string, number>) =>
    apiRequest<{ saved: boolean; team_id: string; budgets: Record<string, number>; message?: string }>(
      `/teams/${encodeURIComponent(teamId)}/finance/budgets`,
      { method: "PUT", body: { budgets } },
    ),
  /** Arbitration-eligible players for a team (empty when gm_arbitration is off). */
  teamArbitration: (teamId: string) =>
    apiRequest<{ team_id: string; players: ArbitrationPlayer[] }>(
      `/teams/${encodeURIComponent(teamId)}/finance/arbitration`,
    ),
  /** Owner arbitration decision: offer_raise / hold / non_tender. */
  submitArbitrationDecision: (
    teamId: string,
    playerId: string,
    action: "offer_raise" | "hold" | "non_tender",
    projectedSalary?: number,
  ) =>
    apiRequest<Record<string, unknown>>(
      `/teams/${encodeURIComponent(teamId)}/finance/arbitration/${encodeURIComponent(playerId)}`,
      {
        method: "POST",
        body: {
          action,
          ...(projectedSalary != null ? { payload: { projected_salary: projectedSalary } } : {}),
        },
      },
    ),
  financeTransactions: (teamId: string, limit = 50) =>
    apiRequest<FinanceTransactions>(
      `/teams/${encodeURIComponent(teamId)}/finance/transactions?limit=${limit}`,
    ),
  financeTodo: (teamId: string) =>
    apiRequest<FinanceTodo>(`/teams/${encodeURIComponent(teamId)}/finance/todo`),
  payrollContext: (teamId: string) =>
    apiRequest<PayrollOutlook>(
      `/teams/${encodeURIComponent(teamId)}/finance/payroll-context`,
    ),
  teamQualifyingOffers: (teamId: string) =>
    apiRequest<TeamQualifyingOffers>(
      `/teams/${encodeURIComponent(teamId)}/finance/qualifying-offers`,
    ),
  resolveQualifyingOffer: (teamId: string, playerId: string, tender: boolean) =>
    apiRequest<{ applied: boolean; decision: string }>(
      `/teams/${encodeURIComponent(teamId)}/finance/qualifying-offers/${encodeURIComponent(playerId)}`,
      { method: "POST", body: { tender } },
    ),
  playoffYears: () => apiRequest<PlayoffYears>("/playoffs/years"),
  playoffs: (year?: number) => {
    const qs = year ? `?year=${year}` : "";
    return apiRequest<Playoffs>(`/playoffs${qs}`);
  },
  simulatePlayoffGame: () =>
    apiRequest<PlayoffSimResult>("/playoffs/simulate/game", { method: "POST" }),
  simulatePlayoffRound: () =>
    apiRequest<PlayoffSimResult>("/playoffs/simulate/round", { method: "POST" }),
  simulatePlayoffAll: () =>
    apiRequest<PlayoffSimResult>("/playoffs/simulate/all", { method: "POST" }),
  rebuildPlayoffs: (numPlayoffTeams = 4) =>
    apiRequest<{ bracket: Playoffs; rebuilt: boolean; num_playoff_teams: number }>(
      "/playoffs/rebuild",
      { method: "POST", body: { num_playoff_teams: numPlayoffTeams } },
    ),
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
  reverseTrade: (tradeId: string, note = "") =>
    apiRequest<{ trade_id: string; status: string; note: string }>(
      `/trades/${encodeURIComponent(tradeId)}/reverse`,
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
  tradeDeadline: () => apiRequest<TradeDeadline>("/trades/deadline"),
  counterTrade: (
    tradeId: string,
    payload: {
      give_player_ids: string[];
      receive_player_ids: string[];
      give_pick_ids?: string[];
      receive_pick_ids?: string[];
    },
  ) =>
    apiRequest<{
      original_trade_id: string;
      original_status: string;
      counter_trade_id: string;
      counter_status: string;
      cpu_response: TradeCpuEvaluation | null;
      counter_back_id: string | null;
    }>(
      `/trades/${encodeURIComponent(tradeId)}/counter`,
      { method: "POST", body: payload },
    ),
  schedule: (params: {
    teamId?: string;
    start?: string;
    end?: string;
    played?: boolean;
    limit?: number;
    includeMarkers?: boolean;
  } = {}) => {
    const q = new URLSearchParams();
    if (params.teamId) q.set("team_id", params.teamId);
    if (params.start) q.set("start", params.start);
    if (params.end) q.set("end", params.end);
    if (params.played !== undefined) q.set("played", String(params.played));
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    if (params.includeMarkers) q.set("include_markers", "true");
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
  autofillDepthChart: (teamId: string) =>
    apiRequest<{
      team_id: string;
      positions: string[];
      max_depth: number;
      chart: Record<string, string[]>;
    }>(`/teams/${encodeURIComponent(teamId)}/depth-chart/auto-fill`, {
      method: "POST",
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
  offseasonDetails: () =>
    apiRequest<{
      ended_season_year: number;
      next_season_year: number;
      contract_expirations: Array<Record<string, unknown>>;
      arbitration_details: Array<Record<string, unknown>>;
      payroll_accounting_details: Array<Record<string, unknown>>;
      budget_deltas: Array<Record<string, unknown>>;
      gm_finance_queue: Array<Record<string, unknown>>;
    }>("/offseason/details"),
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
    apiRequest<{
      team_id: string;
      status: string;
      released: string[];
      released_count: number;
      overflow: string[];
      overflow_count: number;
    }>(`/teams/${encodeURIComponent(teamId)}/auto-assign`, { method: "POST" }),
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
  draftPool: (year?: number, opts?: { available_only?: boolean; limit?: number }) => {
    const params = new URLSearchParams();
    if (year) params.set("year", String(year));
    if (opts?.available_only !== undefined)
      params.set("available_only", opts.available_only ? "true" : "false");
    if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return apiRequest<DraftPool>(`/draft/pool${qs ? `?${qs}` : ""}`);
  },
  draftMakePick: (player_id: string, year?: number) =>
    apiRequest<DraftPickResult>("/draft/pick", {
      method: "POST",
      body: { player_id, year },
    }),
  draftAutoPick: (year?: number) =>
    apiRequest<DraftPickResult>("/draft/auto-pick", {
      method: "POST",
      body: { year },
    }),
  draftAutoAdvance: (
    stop: "my_pick" | "end_of_round" | "end_of_draft",
    opts?: { year?: number; team_id?: string },
  ) =>
    apiRequest<DraftAutoAdvanceResult>("/draft/auto-advance", {
      method: "POST",
      body: { stop, year: opts?.year, team_id: opts?.team_id },
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
  adminResetToOpeningDay: (options: {
    purge_boxscores?: boolean;
    clear_news?: boolean;
    clear_transactions?: boolean;
  }) =>
    apiRequest<{
      reset: boolean;
      opening_day_year: number | null;
      boxscores_cleared: boolean;
      news_cleared: boolean;
      transactions_cleared: boolean;
      notes: string[];
    }>("/admin-league/reset-to-opening-day", {
      method: "POST",
      body: options,
    }),
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
