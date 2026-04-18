import { Navigate, Route, Routes } from "react-router-dom";

import { SplashGate } from "@/pages/SplashGate";
import { LoginPage } from "@/pages/LoginPage";
import { LeagueSelectPage } from "@/pages/LeagueSelectPage";
import { OwnerDashboardPage } from "@/pages/OwnerDashboardPage";
import { RosterPage } from "@/pages/RosterPage";
import { StandingsPage } from "@/pages/StandingsPage";
import { SchedulePage } from "@/pages/SchedulePage";
import { LiveGamePage } from "@/pages/LiveGamePage";
import { TradesPage } from "@/pages/TradesPage";
import { DraftPage } from "@/pages/DraftPage";
import { PlayoffsPage } from "@/pages/PlayoffsPage";
import { FinancePage } from "@/pages/FinancePage";
import { AdminUsersPage } from "@/pages/AdminUsersPage";
import { TeamsPage } from "@/pages/TeamsPage";
import { UtilitiesPage } from "@/pages/UtilitiesPage";
import { SeasonPage } from "@/pages/SeasonPage";
import { LineupPage } from "@/pages/LineupPage";
import { TrainingPage } from "@/pages/TrainingPage";
import { TeamSettingsPage } from "@/pages/TeamSettingsPage";
import { PlayerProfilePage } from "@/pages/PlayerProfilePage";
import { BoxscorePage } from "@/pages/BoxscorePage";
import { TeamDetailPage } from "@/pages/TeamDetailPage";
import { ActivityPage } from "@/pages/ActivityPage";
import { NewsPage } from "@/pages/NewsPage";
import { InjuryPage } from "@/pages/InjuryPage";
import { FreeAgencyPage } from "@/pages/FreeAgencyPage";
import { LeadersPage } from "@/pages/LeadersPage";
import { StatsPage } from "@/pages/StatsPage";
import { PlayersBrowserPage } from "@/pages/PlayersBrowserPage";
import { LeagueHistoryPage } from "@/pages/LeagueHistoryPage";
import { CommissionerPage } from "@/pages/CommissionerPage";
import { CommandCenterPage } from "@/pages/CommandCenterPage";
import { FinanceQueuePage } from "@/pages/FinanceQueuePage";
import { ChangeRequestsPage } from "@/pages/ChangeRequestsPage";
import { HallOfFamePage } from "@/pages/HallOfFamePage";
import { RecordsPage } from "@/pages/RecordsPage";
import { TuningPage } from "@/pages/TuningPage";
import { LeagueCreatePage } from "@/pages/LeagueCreatePage";
import { ComingSoonPage } from "@/pages/ComingSoonPage";
import { DepthChartPage } from "@/pages/DepthChartPage";
import { OffseasonPage } from "@/pages/OffseasonPage";
import { ReassignPage } from "@/pages/ReassignPage";
import { FinanceStabilityPage } from "@/pages/FinanceStabilityPage";
import { ChangeRequestExportPage } from "@/pages/ChangeRequestExportPage";
import { HelpPage } from "@/pages/HelpPage";
import { ExhibitionPage } from "@/pages/ExhibitionPage";
import { AdminLeaguePage } from "@/pages/AdminLeaguePage";
import { useAuthStore } from "@/lib/auth-store";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/**
 * Dashboard + descendant routes also require a selected league. If none is
 * set yet, bounce to the picker. LeagueSelectPage itself sits outside this
 * guard so the user can reach it without a selection.
 */
function RequireLeague({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const league = useAuthStore((s) => s.activeLeagueId);
  if (!token) return <Navigate to="/login" replace />;
  if (!league) return <Navigate to="/select-league" replace />;
  return <>{children}</>;
}

const STUB_ROUTES: Array<{ path: string; label: string }> = [];

export default function App() {
  return (
    <SplashGate>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* Accessible without auth for first-run bootstrap; the page
            component itself enforces admin when first-run=1 is absent. */}
        <Route path="/leagues/new" element={<LeagueCreatePage />} />
        <Route
          path="/select-league"
          element={
            <RequireAuth>
              <LeagueSelectPage />
            </RequireAuth>
          }
        />
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
        <Route path="/" element={<Navigate to="/home" replace />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </SplashGate>
  );
}
