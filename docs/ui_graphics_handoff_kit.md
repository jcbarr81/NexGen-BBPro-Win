# UI Graphics Handoff Kit (ChatGPT + Screenshots + PyQt Code)

This guide gives you reusable templates for redesigning NexGen BBPro UI screens
with ChatGPT while keeping working PyQt code.

## Will this workflow work?

Yes, with guardrails.

- It works best when you provide both:
  - A current screenshot of the exact window/dialog.
  - The exact source code for that class (not a paraphrase).
- Ask for two outputs separately:
  - New graphic assets (PNG/SVG specs).
  - Updated code that integrates those assets.
- Keep stable IDs and names (`objectName`, signal hookups, data bindings) so UX
  changes do not break behavior.

## Current UI Surface Inventory

Top-level classes detected in `ui/`:

- 48 dialogs (`QDialog`)
- 3 main windows (`QMainWindow`)
- 23 widgets/pages (`QWidget`)

Primary classes to hand off (file -> class):

- `ui/admin_dashboard/pages/base.py` -> `DashboardPage`
- `ui/avatar_tutorial_dialog.py` -> `AvatarTutorialDialog`
- `ui/boxscore_window.py` -> `BoxScoreWindow`
- `ui/change_request_export_dialog.py` -> `ChangeRequestExportDialog`
- `ui/change_requests_window.py` -> `ChangeRequestsWindow`
- `ui/depth_chart_dialog.py` -> `DepthChartDialog`
- `ui/draft_console.py` -> `DraftConsole`
- `ui/draft_results_dialog.py` -> `DraftResultsDialog`
- `ui/exhibition_game_dialog.py` -> `ExhibitionGameDialog`
- `ui/finance_stability_dialog.py` -> `FinanceStabilityDialog`
- `ui/financial_settings_dialog.py` -> `FinancialSettingsDialog`
- `ui/free_agency_window.py` -> `FreeAgencyWindow`
- `ui/gm_finance_queue_dialog.py` -> `GmFinanceQueueDialog`
- `ui/hall_of_fame_settings_dialog.py` -> `HallOfFameSettingsDialog`
- `ui/injury_center_window.py` -> `InjuryCenterWindow`
- `ui/injury_settings_dialog.py` -> `InjurySettingsDialog`
- `ui/league_history_window.py` -> `LeagueHistoryWindow`
- `ui/league_leaders_window.py` -> `LeagueLeadersWindow`
- `ui/league_manager_dialog.py` -> `LeagueManagerDialog`
- `ui/league_preset_dialogs.py` -> `LeagueSetupChoiceDialog`
- `ui/league_preset_dialogs.py` -> `PresetListDialog`
- `ui/league_stats_window.py` -> `LeagueStatsWindow`
- `ui/lineup_editor.py` -> `LineupEditor`
- `ui/login_window.py` -> `LoginWindow`
- `ui/logo_tutorial_dialog.py` -> `LogoTutorialDialog`
- `ui/news_window.py` -> `NewsWindow`
- `ui/offseason_finance_dialog.py` -> `OffseasonFinanceDialog`
- `ui/owner_dashboard.py` -> `OwnerDashboard`
- `ui/owner_finance_page.py` -> `OwnerFinancePage`
- `ui/owner_home_page.py` -> `OwnerHomePage`
- `ui/owner_home_page.py` -> `BullpenReadinessWidget`
- `ui/owner_home_page.py` -> `MatchupScoutWidget`
- `ui/owner_home_page.py` -> `HotColdWidget`
- `ui/owner_home_page.py` -> `DivisionStandingsWidget`
- `ui/park_selector_dialog.py` -> `ParkSelectorDialog`
- `ui/pitchers_dialog.py` -> `RetroHeader`
- `ui/pitchers_dialog.py` -> `PitchersDialog`
- `ui/pitchers_window.py` -> `PitchersWindow`
- `ui/pitching_editor.py` -> `PitchingEditor`
- `ui/playbalance_editor.py` -> `PhysicsTuningEditor`
- `ui/player_browser_dialog.py` -> `PlayerBrowserDialog`
- `ui/player_profile_dialog.py` -> `PlayerProfileDialog`
- `ui/player_profile_dialog.py` -> `SprayChartWidget`
- `ui/player_profile_dialog.py` -> `RollingStatsWidget`
- `ui/player_profile_dialog.py` -> `ComparisonSelectorDialog`
- `ui/playoffs_window.py` -> `PlayoffsWindow`
- `ui/position_players_dialog.py` -> `RetroHeader`
- `ui/position_players_dialog.py` -> `PositionPlayersDialog`
- `ui/reassign_players_dialog.py` -> `ReassignPlayersDialog`
- `ui/roster_page.py` -> `RosterPage`
- `ui/schedule_page.py` -> `SchedulePage`
- `ui/schedule_window.py` -> `ScheduleWindow`
- `ui/season_progress_window.py` -> `SeasonProgressWindow`
- `ui/splash_screen.py` -> `SplashScreen`
- `ui/standings_window.py` -> `StandingsWindow`
- `ui/team_entry_dialog.py` -> `TeamEntryDialog`
- `ui/team_page.py` -> `TeamPage`
- `ui/team_records_page.py` -> `TeamRecordsPage`
- `ui/team_schedule_window.py` -> `TeamScheduleWindow`
- `ui/team_settings_dialog.py` -> `TeamSettingsDialog`
- `ui/team_stats_window.py` -> `TeamStatsWindow`
- `ui/trade_dialog.py` -> `TradeDialog`
- `ui/trade_settings_dialog.py` -> `TradeSettingsDialog`
- `ui/training_focus_dialog.py` -> `TrainingFocusDialog`
- `ui/transactions_page.py` -> `TransactionsPage`
- `ui/transactions_window.py` -> `TransactionsWindow`
- `ui/tutorial_dialog.py` -> `TutorialDialog`
- `ui/ui_template.py` -> `DashboardPage`
- `ui/ui_template.py` -> `LeaguePage`
- `ui/ui_template.py` -> `TeamsPage`
- `ui/ui_template.py` -> `UsersPage`
- `ui/ui_template.py` -> `UtilitiesPage`
- `ui/ui_template.py` -> `MainWindow`
- `ui/_admin_dashboard_legacy.py` -> `MainWindow`

## Source Bundle Checklist Per Screen

For each redesign request, include:

- Screenshot of current screen.
- Entire file that contains the class.
- Class name to edit.
- Constraints:
  - Keep method names/signals.
  - Keep data flow.
  - Keep existing IDs/object names unless explicitly changed.
  - Do not remove validation/guard logic.

## Prompt Template: Screenshot + Code -> New Visual Assets

```text
You are redesigning a PyQt6 screen for a desktop baseball sim app.

I will provide:
1) Screenshot of the current screen
2) Source code for class: <CLASS_NAME>

Task:
- Propose a visual redesign that keeps the same information architecture and
  interaction flow.
- Keep the brand direction: baseball retro-modern, high readability.
- Return:
  1) Asset list (backgrounds, panel textures, icons, badges) with exact pixel
     sizes and transparent/non-transparent requirements.
  2) Prompt text I can use to generate each asset image.
  3) Color tokens and typography tokens.

Constraints:
- Do not change business logic.
- Do not remove controls that exist in the screenshot.
- Ensure it works in both light and dark theme variants.
```

## Prompt Template: Screenshot + Code -> Updated PyQt Code

```text
Using this screenshot and this PyQt6 class source, rewrite ONLY the UI build/
style portions to implement a cleaner visual layout.

Output requirements:
- Return a full updated class definition for <CLASS_NAME>.
- Keep all existing non-UI logic and method signatures.
- Preserve object names and signals used elsewhere.
- If adding assets, load them from `assets/ui/<name>.png` with safe fallback.
- Keep window/dialog sizing practical for 1366x768 and 1920x1080.
- No placeholder TODO comments.

Quality checks before output:
- No runtime errors from missing widgets referenced later.
- Tab order remains reasonable.
- Existing buttons/actions still trigger same handlers.
```

## Reusable PyQt6 UI Templates

Use these as starter blocks when asking ChatGPT for code changes.

### 1. Dialog Shell

```python
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton


class ExampleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Example")
        self.resize(920, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Dialog Title")
        title.setObjectName("Title")
        root.addWidget(title)

        body = QLabel("Content goes here.")
        body.setWordWrap(True)
        root.addWidget(body, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        ok_btn = QPushButton("Save")
        ok_btn.setObjectName("Primary")
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        root.addLayout(buttons)
```

### 2. Data Table Dialog

```python
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem


class ExampleTableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Table")
        self.resize(1100, 700)

        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["A", "B", "C", "D"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        root.addWidget(self.table)

    def add_row(self, values: list[str]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate(values):
            self.table.setItem(row, col, QTableWidgetItem(value))
```

### 3. Form Section

```python
from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QLineEdit, QComboBox, QSpinBox


def build_form_section() -> QWidget:
    host = QWidget()
    grid = QGridLayout(host)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(10)

    grid.addWidget(QLabel("Team"), 0, 0)
    team_box = QComboBox()
    grid.addWidget(team_box, 0, 1)

    grid.addWidget(QLabel("Owner"), 1, 0)
    owner_edit = QLineEdit()
    grid.addWidget(owner_edit, 1, 1)

    grid.addWidget(QLabel("Budget"), 2, 0)
    budget_spin = QSpinBox()
    budget_spin.setRange(0, 999)
    grid.addWidget(budget_spin, 2, 1)

    return host
```

### 4. Tabbed Layout

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QLabel


def build_tabs() -> QWidget:
    wrapper = QWidget()
    root = QVBoxLayout(wrapper)
    tabs = QTabWidget()
    root.addWidget(tabs)

    for name in ["Overview", "Details", "History"]:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(f"{name} content"))
        tabs.addTab(tab, name)

    return wrapper
```

### 5. Card + Metrics Strip (aligned with `ui/components.py`)

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from ui.components import Card, section_title, build_metric_row


def build_metrics_card() -> QWidget:
    card = Card()
    layout = card.layout()
    layout.addWidget(section_title("Quick Metrics"))
    layout.addWidget(
        build_metric_row(
            [
                ("Record", "81-54"),
                ("Run Diff", "+92"),
                ("Streak", "W3"),
                ("Playoff Odds", "74%"),
            ],
            columns=4,
            variant="stat",
        )
    )
    return card
```

### 6. Theme Hook (aligned with `ui/theme.py`)

```python
from PyQt6.QtWidgets import QApplication
from ui.theme import LIGHT_QSS


def apply_theme(app: QApplication) -> None:
    app.setStyleSheet(LIGHT_QSS)
```

## Recommended Workflow (Per Window/Dialog)

1. Take screenshot.
2. Paste screenshot + full class source into ChatGPT using the prompt template.
3. Ask for asset spec first (no code).
4. Generate assets.
5. Ask for code update that references those assets.
6. Paste code into local class and run the target UI manually.
7. Refine in one more pass with a fresh screenshot.

## Risks to Watch

- Large class rewrites can drop signal connections or helper methods.
- Styling-only edits can still break runtime if widget names are changed.
- Asset paths can break packaging if files are not under project assets.

## Optional Command Snippets

Find all top-level UI classes:

```powershell
rg -n "^class\s+(\w+)\((?:QtWidgets\.)?(QDialog|QMainWindow|QWidget)\)" ui -S
```

Find widget types used across UI:

```powershell
rg -o "\bQ[A-Z][A-Za-z0-9_]*\b" ui -S | % { ($_ -split ':')[-1] } | sort -Unique
```
