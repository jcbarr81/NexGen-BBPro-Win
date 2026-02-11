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
