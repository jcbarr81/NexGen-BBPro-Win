## 5.2.38
- Promoted Player Profile V2 to the default profile dialog while keeping the legacy profile available as an explicit fallback.
- Removed the hidden legacy-dialog proxy from Player Profile V2 and replaced it with native compare, stats summary, and career ledger flows.
- Added regression coverage for V2-native comparison behavior and the new launcher default/fallback routing.

## 5.2.37
- Added established-league contract backfill when finance is enabled so existing rosters receive inferred contracts instead of remaining contract-empty.
- Added commissioner-facing save-time messaging summarizing generated contracts for mid-league finance enablement.
- Added regression coverage for established-league backfill heuristics and finance-settings-triggered contract migration.

## 5.2.36
- Added finance module tooltips in league creation and league finance settings so commissioners can compare Off/Basic/Advanced/MLB-Like/Warn/Block behaviors directly in the UI.
- Added shared finance-level help text builders to keep module and enforcement explanations consistent across finance setup surfaces.

## 5.2.35
- Seed inaugural roster contracts automatically when finance is enabled so first-year preseason teams no longer open the Finance hub with empty payroll/contract state.
- Added startup repair coverage for inaugural finance-enabled saves that were created before contracts were seeded.
- Added regression coverage for inaugural contract seeding and established-league skip behavior.

## 5.2.34
- Hardened player profile routing with explicit launcher fallback behavior.
- Added regression coverage for default, override, and invalid-variant profile launches.
- Added V2 compare-selection safety coverage without expanding UI dependencies.
- Added compact Player Profile V2 contract snapshot details and overall rating transparency rows for raw, displayed, scouted, and star values.
