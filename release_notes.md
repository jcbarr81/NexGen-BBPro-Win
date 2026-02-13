<!-- last_build_ref: 782e316f30b09798d4f49151db81f77ffd8f53d3 -->
# 4.5 Release Notes (Since 4.3.41)

## League Setup & Presets
- Added rule presets, schedule templates, and quick-start league presets.
- Quick-start leagues now let admins choose schedule length instead of a locked schedule.
- Enforced league size guardrails (40-team maximum).

## Player Development & Training
- Individual Training Focus (player-level overrides) with clear source hierarchy (Player → Team → League).
- Training focus defaults apply when no per-player focus is set.
- Training focus UI refreshes player profile after save.
- Added Training Focus tutorials.

## Hall of Fame
- New Hall of Fame system with eligibility/scoring rules.
- Admin UI for tuning thresholds and rules, including “Reset to Defaults.”
- Manual add/remove override support.

## Records & Timeline
- Record notifications with pop-ups when season/career records are broken.
- Season Timeline Feed for milestones, awards, records, and special events.
- Timeline feed surfaced in Season Progress view.

## Online League Workflow
- Owner Change Requests export flow (roster/lineup/pitching/depth chart).
- Admin Change Request queue with import, approve/apply, reject, and cancel.
- File validation and team-scoped enforcement for requests.
- Audit log for approvals and applications with file hashes.

## League Syncing
- League Snapshot export (admin) for distributing updated league files.
- League Snapshot import (owners) with automatic backup.
- League ID enforcement to prevent importing the wrong league.

## Commissioner-Only Access (Multi-Owner Mode)
- New league_settings.json with owner_league mode.
- Commissioner password required for admin access in multi-owner leagues.
- Commissioner password set during league creation.
- Enforced in both login and owner dashboard admin access flow.

## Admin Utilities
- Added “Export League Snapshot” action to Admin Utilities.
- Improved admin workflows and wiring for new tools.

## Tutorial Coverage
- Added tutorials for Individual Training Focus and related admin guidance.

# ﻿4.5.9 Release Notes (Since last build 782e316)
Date: 2026-02-12

- No changes since last build and no draft notes were found.

# 4.5.19 Release Notes (Since last build 782e316)
Date: 2026-02-13

- Added an owner tutorial for submitting roster change requests from the Roster page.
- Updated owner_admin_guide with Submit Change Request usage and the new Owner Change Requests tutorial.
- Added league Trade Settings for commissioners: enable/disable all trading, allow/disallow draft-pick trades, and set maximum tradable pick years out.
- Added draft-pick trade support in the Trade Center and admin trade review flows, including persisted pick assets on trade proposals.
- Added draft-pick ownership tracking so traded picks are honored on draft day.
- Added transaction log entries for draft-pick movement on accepted trades (both owner acceptance and commissioner review).
- Added a Trade Settings option to require commissioner approval before owner-accepted trades execute.
- Updated the Trades & Transactions tutorial content to reflect draft-pick trades, commissioner approval mode, and current trade execution behavior.
- Added trade policy prompts to league creation (trading on/off, draft-pick trades, commissioner approval requirement, and tradable pick years window).
- Added Trade Settings as a quick action on the Admin home dashboard.
- Reorganized the Admin dashboard into focused areas: new Transactions and League Settings pages, a Season-focused League page, and an Assets & Exports utilities layout with streamlined Home quick actions.
- Refined Admin dashboard IA and UX: internal page key renamed to Season (with compatibility alias), clearer page labels/tooltips, and improved hub-style navigation for Transactions/Season/Draft/Settings/Assets.
- Updated admin-facing tutorials/docs to match current navigation labels (Season, Transactions, League Settings, Assets & Exports) and renamed Admin Season page code from LeaguePage/league.py to SeasonPage/season.py for clarity.
