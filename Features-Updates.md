> **⚠️ Stale — last updated 2026-02; app is at 7.0.11 (note added 2026-07-13).**
> This checklist predates the Electron/React + cloud rebuild and the 7.0 finance
> overhaul. Many P2 items (salary/free agency, team budgets, scouting, strategy
> profiles, analytics/career-arc) have since shipped. Treat `release_notes.md`
> and `docs/future_work.md` (see its reconciliation banner) as the current source
> of truth; verify any item here against code before actioning.

==========
P0 - FIX NOW
==========
- [x] Show MLB park that they have chosen, that feature crashes UI as of now
- [x] If user has made changes to lineup or pitching rotation and has not saved, warn them if they try to close the window
- [x] Users display is not working properly, backend seems fine, but display is off
- [x] Team totals display under team stats is a little off, probably wanted to fix that
- [x] Only pitchers in LOW after creating league and no pitchers in AAA after using the auto-assign feature
- [x] Team stats pages were still lingering in the background for some reason
- [x] Closing the main screen should close all other windows as well

==========
P1 - CORE UX + LEAGUE FLOW
==========
- [x] When starting a league, remind admin to set draft settings
- [x] When opening team dashboard from admin panel, lets close the admin panel
- [x] When opening admin panel from team dashboard, close team dashboard
- [x] provide a link to the admin panel at the very bottom of the left menu
- [x] Playoff viewer link should probably be under League page
- [x] Open player dialog when double clicking from lineup or pitching staff editor
- [x] When the draft is ready, lets post some sort of messaged on the owner dashboard
- [x] Output draft results so that they are viewable for the current year and for historical years
- [x] If a human owned team makes the playoffs they should get a pop up congratulating them and letting them know that they made the post season
- [x] Revamp the player dialog to make sure that all relevant info is displayed
- [x] Player dialog opens maximized with a bottom-right close button
- [x] Make league leaders look more like the team stats pages
- [x] Dashboard console doesn't have any sorting enabled
- [x] Draft pool ratings display now uses draft-pool percentiles so prospects no longer show identical ratings
- [x] Draft pool ages now span 17-21 (HS + college mix) and birthdates match generated ages
- [x] Autosave + crash recovery for key league/roster changes
- [x] Clear dirty-state indicators across editors and dashboards
- [x] Background task progress indicators for long-running sims/exports

==========
P2 - ADMIN + LONGER-TERM
==========
- [x] Turn injuries on/off and set frequency
- [x] Tutorial on creating player avatars
- [x] Tutorial on team logo generation
- [x] Revisit the ability to edit "playbalance". Make it easy to use and make sure that it has descriptions on fields and is able to be saved and changed from year to year
- [x] Season progress, lets work on the timeline display
- [x] When creating players for the draft too many elite players are being created. Young players should have lower ratings and progress over time according to their potential ratings
- [x] Value young players more and don't cut or release them
- [x] Records and special events need to be tracked and displayed
- [x] Eventually add individual training focus per player
- [x] Develop workflow for online leagues so that owners can make changes and then either send updates or upload them automtically
- [x] Add support for multiple leagues
- [ ] Further refine the UI with a better scheme and/or graphics
- [ ] Develop salary and free agency system
- [x] Test and futher develop trading workflow, ensure trading of draft picks is enabled and tracked
- [x] Add Hall of Fame feature
- [x] Records, special event notifcations
- [ ] AI team strategy profiles (rebuild/contend) with role-based roster targets
- [ ] Smarter prospect protection logic and promotion/option handling
- [ ] Scouting system with fog-of-war ratings and scouting budgets
- [ ] Draft enhancements: late bloomers, varied class strength, draft-day storylines
- [ ] Team budgets, market sizes, and financial rules tied to roster decisions
- [x] Season timeline feed for milestones, awards, records, and special events
- [ ] Expanded analytics dashboards (advanced metrics, filters, comparisons)
- [ ] Career arc views and year-over-year comparisons for players/teams
- [x] Export reports to CSV/PDF for league history and analytics
- [x] Rule presets, schedule templates, and quick-start league setups
- [x] Online league tooling: live shared-data editing, approval queues, sync/audit log
- [x] Multi-league management: league switcher + per-league settings isolation
- [ ] Optional shared player pools across leagues

==========
P3 - DIFFERENTIATORS + LONG-TERM
==========
- [ ] Modding/community content pipeline (rulesets, assets, data packs)
- [ ] Presentation layer: in-game visual sim (2D/3D) and highlight reels
- [ ] Commentary/announcer track with milestone callouts
