import { Suspense, lazy, useEffect, useRef } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { SplashGate } from "@/pages/SplashGate";
import { Toaster } from "@/components/Toaster";
import { CommandPalette } from "@/components/CommandPalette";
// Eagerly loaded — these are on the critical path before / immediately
// after login, so deferring them only adds flicker without saving real
// bytes up-front.
import { LoginPage } from "@/pages/LoginPage";
import { LeagueSelectPage } from "@/pages/LeagueSelectPage";
import { OwnerDashboardPage } from "@/pages/OwnerDashboardPage";

// Everything else is code-split with ``React.lazy``. Vite emits one chunk
// per lazy import, so the initial bundle trims ~500 KB and each page is
// downloaded on demand. Named-export pages need a tiny adapter to
// produce the ``{ default }`` shape ``lazy()`` expects.
const named = <K extends string, T>(
  key: K,
  loader: () => Promise<Record<K, T>>,
) => loader().then((m) => ({ default: m[key] })) as Promise<{ default: T }>;

const RosterPage = lazy(() =>
  named("RosterPage", () => import("@/pages/RosterPage")),
);
const PitchersPage = lazy(() =>
  named("PitchersPage", () => import("@/pages/PitchersPage")),
);
const PositionPlayersPage = lazy(() =>
  named("PositionPlayersPage", () => import("@/pages/PositionPlayersPage")),
);
const ComparePage = lazy(() =>
  named("ComparePage", () => import("@/pages/ComparePage")),
);
const StandingsPage = lazy(() =>
  named("StandingsPage", () => import("@/pages/StandingsPage")),
);
const SchedulePage = lazy(() =>
  named("SchedulePage", () => import("@/pages/SchedulePage")),
);
const LiveGamePage = lazy(() =>
  named("LiveGamePage", () => import("@/pages/LiveGamePage")),
);
const TradesPage = lazy(() =>
  named("TradesPage", () => import("@/pages/TradesPage")),
);
const DraftPage = lazy(() =>
  named("DraftPage", () => import("@/pages/DraftPage")),
);
const PlayoffsPage = lazy(() =>
  named("PlayoffsPage", () => import("@/pages/PlayoffsPage")),
);
const FinancePage = lazy(() =>
  named("FinancePage", () => import("@/pages/FinancePage")),
);
const ContractsPage = lazy(() =>
  named("ContractsPage", () => import("@/pages/ContractsPage")),
);
const AwardsPage = lazy(() =>
  named("AwardsPage", () => import("@/pages/AwardsPage")),
);
const AllStarPage = lazy(() =>
  named("AllStarPage", () => import("@/pages/AllStarPage")),
);
const AdminUsersPage = lazy(() =>
  named("AdminUsersPage", () => import("@/pages/AdminUsersPage")),
);
const TeamsPage = lazy(() =>
  named("TeamsPage", () => import("@/pages/TeamsPage")),
);
const UtilitiesPage = lazy(() =>
  named("UtilitiesPage", () => import("@/pages/UtilitiesPage")),
);
const SeasonPage = lazy(() =>
  named("SeasonPage", () => import("@/pages/SeasonPage")),
);
const LineupPage = lazy(() =>
  named("LineupPage", () => import("@/pages/LineupPage")),
);
const TrainingPage = lazy(() =>
  named("TrainingPage", () => import("@/pages/TrainingPage")),
);
const TeamSettingsPage = lazy(() =>
  named("TeamSettingsPage", () => import("@/pages/TeamSettingsPage")),
);
const PlayerProfilePage = lazy(() =>
  named("PlayerProfilePage", () => import("@/pages/PlayerProfilePage")),
);
const BoxscorePage = lazy(() =>
  named("BoxscorePage", () => import("@/pages/BoxscorePage")),
);
const TeamDetailPage = lazy(() =>
  named("TeamDetailPage", () => import("@/pages/TeamDetailPage")),
);
const ActivityPage = lazy(() =>
  named("ActivityPage", () => import("@/pages/ActivityPage")),
);
const NewsPage = lazy(() =>
  named("NewsPage", () => import("@/pages/NewsPage")),
);
const NotificationsPage = lazy(() =>
  named("NotificationsPage", () => import("@/pages/NotificationsPage")),
);
const HubPage = lazy(() =>
  named("HubPage", () => import("@/pages/HubPage")),
);
const MyTeamRedirect = lazy(() =>
  named("MyTeamRedirect", () => import("@/pages/MyTeamRedirect")),
);
const InjuryPage = lazy(() =>
  named("InjuryPage", () => import("@/pages/InjuryPage")),
);
const FreeAgencyPage = lazy(() =>
  named("FreeAgencyPage", () => import("@/pages/FreeAgencyPage")),
);
const LeadersPage = lazy(() =>
  named("LeadersPage", () => import("@/pages/LeadersPage")),
);
const StatsPage = lazy(() =>
  named("StatsPage", () => import("@/pages/StatsPage")),
);
const PlayersBrowserPage = lazy(() =>
  named("PlayersBrowserPage", () => import("@/pages/PlayersBrowserPage")),
);
const LeagueHistoryPage = lazy(() =>
  named("LeagueHistoryPage", () => import("@/pages/LeagueHistoryPage")),
);
const CommissionerPage = lazy(() =>
  named("CommissionerPage", () => import("@/pages/CommissionerPage")),
);
const CommandCenterPage = lazy(() =>
  named("CommandCenterPage", () => import("@/pages/CommandCenterPage")),
);
const FinanceQueuePage = lazy(() =>
  named("FinanceQueuePage", () => import("@/pages/FinanceQueuePage")),
);
const ChangeRequestsPage = lazy(() =>
  named("ChangeRequestsPage", () => import("@/pages/ChangeRequestsPage")),
);
const HallOfFamePage = lazy(() =>
  named("HallOfFamePage", () => import("@/pages/HallOfFamePage")),
);
const RecordsPage = lazy(() =>
  named("RecordsPage", () => import("@/pages/RecordsPage")),
);
const TuningPage = lazy(() =>
  named("TuningPage", () => import("@/pages/TuningPage")),
);
const LeagueCreatePage = lazy(() =>
  named("LeagueCreatePage", () => import("@/pages/LeagueCreatePage")),
);
const ComingSoonPage = lazy(() =>
  named("ComingSoonPage", () => import("@/pages/ComingSoonPage")),
);
const DepthChartPage = lazy(() =>
  named("DepthChartPage", () => import("@/pages/DepthChartPage")),
);
const OffseasonPage = lazy(() =>
  named("OffseasonPage", () => import("@/pages/OffseasonPage")),
);
const ReassignPage = lazy(() =>
  named("ReassignPage", () => import("@/pages/ReassignPage")),
);
const FinanceStabilityPage = lazy(() =>
  named("FinanceStabilityPage", () => import("@/pages/FinanceStabilityPage")),
);
const ChangeRequestExportPage = lazy(() =>
  named(
    "ChangeRequestExportPage",
    () => import("@/pages/ChangeRequestExportPage"),
  ),
);
const HelpPage = lazy(() =>
  named("HelpPage", () => import("@/pages/HelpPage")),
);
const ExhibitionPage = lazy(() =>
  named("ExhibitionPage", () => import("@/pages/ExhibitionPage")),
);
const AdminLeaguePage = lazy(() =>
  named("AdminLeaguePage", () => import("@/pages/AdminLeaguePage")),
);
const ParksPage = lazy(() =>
  named("ParksPage", () => import("@/pages/ParksPage")),
);
import { useAuthStore } from "@/lib/auth-store";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/**
 * Dashboard + descendant routes also require a selected league. If none is
 * set yet, bounce to the picker (entry point of the app). LeagueSelectPage
 * itself sits outside this guard so the user can reach it without auth.
 */
function RequireLeague({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const league = useAuthStore((s) => s.activeLeagueId);
  if (!league) return <Navigate to="/select-league" replace />;
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

const STUB_ROUTES: Array<{ path: string; label: string }> = [];

/**
 * Clear every React Query cache entry when the active league changes. Each
 * league has its own teams, roster, lineups, players, standings, stats,
 * etc. — without a wipe we serve stale data from the previous league until
 * the user manually refreshes. This runs once at mount with the initial
 * league id, then fires only on actual change. Safe to call ``clear()``
 * since auth/token lives in Zustand, not React Query.
 */
function LeagueCacheInvalidator() {
  const queryClient = useQueryClient();
  const activeLeagueId = useAuthStore((s) => s.activeLeagueId);
  const prevRef = useRef<string | null>(activeLeagueId);
  useEffect(() => {
    if (prevRef.current !== activeLeagueId) {
      queryClient.clear();
      prevRef.current = activeLeagueId;
    }
  }, [activeLeagueId, queryClient]);
  return null;
}

/** Fallback while a lazy-loaded route chunk downloads. Matches the
 *  SplashGate aesthetic so switching pages feels consistent. */
function RouteFallback() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-canvas">
      <Loader2 className="h-6 w-6 animate-spin text-amber" />
    </div>
  );
}

export default function App() {
  return (
    <SplashGate>
      <LeagueCacheInvalidator />
      <Toaster />
      <CommandPalette />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* Accessible without auth for first-run bootstrap; the page
            component itself enforces admin when first-run=1 is absent. */}
        <Route path="/leagues/new" element={<LeagueCreatePage />} />
        {/* League picker is the first screen shown — public so users can
            choose (or create) a league before signing in. The picker sets
            the active league, then routes to /login. */}
        <Route path="/select-league" element={<LeagueSelectPage />} />
        <Route
          path="/home"
          element={
            <RequireLeague>
              <OwnerDashboardPage />
            </RequireLeague>
          }
        />
        <Route
          path="/season"
          element={
            <RequireLeague>
              <SeasonPage />
            </RequireLeague>
          }
        />
        <Route
          path="/roster"
          element={
            <RequireLeague>
              <RosterPage />
            </RequireLeague>
          }
        />
        <Route
          path="/pitchers"
          element={
            <RequireLeague>
              <PitchersPage />
            </RequireLeague>
          }
        />
        <Route
          path="/position-players"
          element={
            <RequireLeague>
              <PositionPlayersPage />
            </RequireLeague>
          }
        />
        <Route
          path="/lineup"
          element={
            <RequireLeague>
              <LineupPage />
            </RequireLeague>
          }
        />
        <Route
          path="/training"
          element={
            <RequireLeague>
              <TrainingPage />
            </RequireLeague>
          }
        />
        <Route
          path="/injuries"
          element={
            <RequireLeague>
              <InjuryPage />
            </RequireLeague>
          }
        />
        <Route
          path="/notifications"
          element={
            <RequireLeague>
              <NotificationsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/hub/:hubKey"
          element={
            <RequireLeague>
              <HubPage />
            </RequireLeague>
          }
        />
        <Route
          path="/free-agency"
          element={
            <RequireLeague>
              <FreeAgencyPage />
            </RequireLeague>
          }
        />
        <Route
          path="/leaders"
          element={
            <RequireLeague>
              <LeadersPage />
            </RequireLeague>
          }
        />
        <Route
          path="/stats"
          element={
            <RequireLeague>
              <StatsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/players"
          element={
            <RequireLeague>
              <PlayersBrowserPage />
            </RequireLeague>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireLeague>
              <TeamSettingsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/player/:playerId"
          element={
            <RequireLeague>
              <PlayerProfilePage />
            </RequireLeague>
          }
        />
        <Route
          path="/compare/:playerA/:playerB"
          element={
            <RequireLeague>
              <ComparePage />
            </RequireLeague>
          }
        />
        <Route
          path="/boxscore"
          element={
            <RequireLeague>
              <BoxscorePage />
            </RequireLeague>
          }
        />
        <Route
          path="/team/:teamId"
          element={
            <RequireLeague>
              <TeamDetailPage />
            </RequireLeague>
          }
        />
        <Route
          path="/my-team-stats"
          element={
            <RequireLeague>
              <MyTeamRedirect />
            </RequireLeague>
          }
        />
        <Route
          path="/league"
          element={
            <RequireLeague>
              <StandingsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/schedule"
          element={
            <RequireLeague>
              <SchedulePage />
            </RequireLeague>
          }
        />
        <Route
          path="/live"
          element={
            <RequireLeague>
              <LiveGamePage />
            </RequireLeague>
          }
        />
        <Route
          path="/news"
          element={
            <RequireLeague>
              <NewsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/transactions"
          element={
            <RequireLeague>
              <ActivityPage />
            </RequireLeague>
          }
        />
        <Route
          path="/trades"
          element={
            <RequireLeague>
              <TradesPage />
            </RequireLeague>
          }
        />
        <Route
          path="/draft"
          element={
            <RequireLeague>
              <DraftPage />
            </RequireLeague>
          }
        />
        <Route
          path="/playoffs"
          element={
            <RequireLeague>
              <PlayoffsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/history"
          element={
            <RequireLeague>
              <LeagueHistoryPage />
            </RequireLeague>
          }
        />
        <Route
          path="/finance"
          element={
            <RequireLeague>
              <FinancePage />
            </RequireLeague>
          }
        />
        <Route
          path="/contracts"
          element={
            <RequireLeague>
              <ContractsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/awards"
          element={
            <RequireLeague>
              <AwardsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/all-star"
          element={
            <RequireLeague>
              <AllStarPage />
            </RequireLeague>
          }
        />
        <Route
          path="/users"
          element={
            <RequireLeague>
              <AdminUsersPage />
            </RequireLeague>
          }
        />
        <Route
          path="/commissioner"
          element={
            <RequireLeague>
              <CommissionerPage />
            </RequireLeague>
          }
        />
        <Route
          path="/command-center"
          element={
            <RequireLeague>
              <CommandCenterPage />
            </RequireLeague>
          }
        />
        <Route
          path="/finance-queue"
          element={
            <RequireLeague>
              <FinanceQueuePage />
            </RequireLeague>
          }
        />
        <Route
          path="/change-requests"
          element={
            <RequireLeague>
              <ChangeRequestsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/hall-of-fame"
          element={
            <RequireLeague>
              <HallOfFamePage />
            </RequireLeague>
          }
        />
        <Route
          path="/records"
          element={
            <RequireLeague>
              <RecordsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/tuning"
          element={
            <RequireLeague>
              <TuningPage />
            </RequireLeague>
          }
        />
        <Route
          path="/teams"
          element={
            <RequireLeague>
              <TeamsPage />
            </RequireLeague>
          }
        />
        <Route
          path="/utilities"
          element={
            <RequireLeague>
              <UtilitiesPage />
            </RequireLeague>
          }
        />
        <Route
          path="/depth-chart"
          element={
            <RequireLeague>
              <DepthChartPage />
            </RequireLeague>
          }
        />
        <Route
          path="/offseason"
          element={
            <RequireLeague>
              <OffseasonPage />
            </RequireLeague>
          }
        />
        <Route
          path="/reassign"
          element={
            <RequireLeague>
              <ReassignPage />
            </RequireLeague>
          }
        />
        <Route
          path="/finance-stability"
          element={
            <RequireLeague>
              <FinanceStabilityPage />
            </RequireLeague>
          }
        />
        <Route
          path="/submit-change-request"
          element={
            <RequireLeague>
              <ChangeRequestExportPage />
            </RequireLeague>
          }
        />
        <Route
          path="/help"
          element={
            <RequireAuth>
              <HelpPage />
            </RequireAuth>
          }
        />
        <Route
          path="/exhibition"
          element={
            <RequireLeague>
              <ExhibitionPage />
            </RequireLeague>
          }
        />
        <Route
          path="/league-admin"
          element={
            <RequireLeague>
              <AdminLeaguePage />
            </RequireLeague>
          }
        />
        <Route
          path="/parks"
          element={
            <RequireLeague>
              <ParksPage />
            </RequireLeague>
          }
        />
        {STUB_ROUTES.map(({ path, label }) => (
          <Route
            key={path}
            path={path}
            element={
              <RequireLeague>
                <ComingSoonPage label={label} />
              </RequireLeague>
            }
          />
        ))}
        <Route path="/" element={<Navigate to="/select-league" replace />} />
        <Route path="*" element={<Navigate to="/select-league" replace />} />
        </Routes>
      </Suspense>
    </SplashGate>
  );
}
