# NexGen-BBPro → Google Cloud: Multi-Owner Cloud Migration & AI Plan

> Status: Proposal / architecture plan. Nothing here is built yet.
> Goal: Run multi-owner leagues in the cloud (no local install required) while
> reusing the existing FastAPI backend, React UI, and Python sim engine, and
> layering Gemini / Vertex AI into trades, drafting, lineups, and narrative.

---

## 1. Where we are today (and why it's a good starting point)

The codebase is already split the way a cloud app wants to be:

| Layer | Today | Reuse outlook |
|---|---|---|
| **UI** | React + Vite + Tailwind SPA (`desktop/src`) wrapped in Electron | ~95% reused. Electron becomes optional. |
| **API** | FastAPI app, 50+ routers (`api/`), spawned as a 127.0.0.1 sidecar | ~90% reused. Swap storage + auth deps. |
| **Sim engine** | `physics_sim/` (pitch physics) + `playbalance/` (game logic), pure synchronous compute, sub-second/game | 100% reused, unchanged. |
| **CPU "AI"** | Rule-based services: `cpu_trade_evaluator`, `cpu_trade_proposals`, `draft_ai`, `contract_negotiator`, `depth_chart_manager`, `roster_auto_assign`, `team_strategy_profiles` | Reused as **guardrails** around Gemini. |
| **Data** | Per-league files: `data/leagues/<id>/data/*.{csv,json,txt}` (~44 MB) | Migrated to Cloud SQL + GCS via a storage seam. |
| **Auth** | `users.txt` per league + per-process HMAC token (localhost-only) | Replaced by Firebase Auth + DB memberships. |
| **LLM** | `utils/openai_client.py` → OpenAI `gpt-image-1` for logos/avatars only | Generalized to a Vertex AI client. |

**Three structural facts that make this tractable:**

1. **Storage is funneled through one seam.** ~220 call sites resolve data through
   `utils/path_utils.get_data_dir()` / `get_active_league_*()`. We do not touch 220
   call sites — we change what that seam returns. It already accepts a `league_id`
   param and a `NEXGEN_ACTIVE_LEAGUE` override; today it just resolves to a process
   global. Making it **request-context aware** is the central backend refactor.
2. **The UI already speaks HTTP + WebSocket to a remote-ish base URL** (the sidecar
   handshake gives it `baseUrl`/`wsUrl` + a bearer token). Pointing it at a cloud
   URL with a real token is a config change, not a rewrite.
3. **The sim engine is pure compute** — no global UI state, no DB coupling. It runs
   identically in a Cloud Run container.

**The one assumption that must die:** a single process-global "active league"
(`active_league.txt` pointer + module-level cache in `path_utils`, plus the
per-process HMAC secret in `api/security.py`). A multi-tenant server has many leagues
live at once; "active league" must become per-request, not per-process.

---

## 2. Target architecture on GCP

```
                          ┌──────────────────────────────────────────────┐
   Browser / Electron ──► │  Firebase Hosting + Cloud CDN (React SPA)     │
   (owner's Google login) └──────────────────────────────────────────────┘
            │  HTTPS / WSS  (Firebase ID token)
            ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │  Cloud Run: FastAPI service (the existing `api/` app, containerized)  │
   │   • verifies Firebase ID token → uid                                  │
   │   • resolves league_id per-request → DataStore (no global state)      │
   │   • read/light-write endpoints respond inline                         │
   │   • heavy work (sim a day, draft round) → enqueue Cloud Task          │
   └──────────────────────────────────────────────────────────────────────┘
        │                 │                  │                    │
        ▼                 ▼                  ▼                    ▼
  ┌───────────┐   ┌───────────────┐   ┌──────────────┐   ┌─────────────────┐
  │ Cloud SQL │   │ Cloud Storage │   │ Vertex AI    │   │ Cloud Tasks +   │
  │ (Postgres)│   │ (GCS blobs)   │   │ Gemini/Imagen│   │ Cloud Run Jobs  │
  │ system of │   │ boxscores,    │   │ trades,draft │   │ (async sim,     │
  │ record    │   │ logos, snaps  │   │ lineups,news │   │ day-advance)    │
  └───────────┘   └───────────────┘   └──────────────┘   └─────────────────┘
        ▲                                                          │
        └──────────────── Pub/Sub (sim-complete fan-out) ◄─────────┘
                                   │
                                   ▼  push standings/news/notifications
                        connected owners (WSS or Firestore listeners)
```

### GCP service mapping

| Concern | GCP service | Why |
|---|---|---|
| Frontend hosting | **Firebase Hosting** (+ Cloud CDN) | Static SPA, global CDN, free tier, custom domains, easy preview channels. |
| API + live WebSocket | **Cloud Run** (container) | Runs the existing `python -m api` unchanged; HTTP + WS; scales to zero; per-request billing. |
| System of record | **Cloud SQL for PostgreSQL** | Relational queries (standings, leaders, stats, contracts) and ACID for concurrent owners. |
| Realtime presence / notifications | **Firestore** (optional, additive) | Native client listeners for "trade offer arrived", "day was simmed", chat. |
| Large blobs | **Cloud Storage (GCS)** | Boxscores, career archives, logos/avatars, league snapshots/backups. |
| Identity | **Firebase Authentication / Identity Platform** | Real per-owner Google / email login; ID tokens verified in FastAPI. |
| AI | **Vertex AI** (Gemini, Imagen, grounding, fine-tuning) | Trades, draft, lineups, narrative, images; enterprise data controls. |
| Async sim / cadence | **Cloud Tasks + Cloud Run Jobs + Cloud Scheduler** | Day-advance jobs, nightly auto-sim, season batch runs. |
| Event fan-out | **Pub/Sub** | "Day N simmed" → notify all owners, update feeds. |
| Secrets | **Secret Manager** | Replaces `config.ini` API keys. |
| Observability | **Cloud Logging / Monitoring / Trace** | Replaces the `sidecar.log` FileHandler in `api/app.py`. |
| CI/CD | **Cloud Build + Artifact Registry** | Build container, run tests, deploy Cloud Run + Hosting. |

### What happens to Electron?

Electron is **not thrown away** — it changes role:

- **Cloud mode (new default for multiplayer):** the Electron shell (or any browser)
  loads the Firebase-hosted SPA and talks to Cloud Run. The `sidecar.ts` spawn +
  handshake is replaced by a small `RemoteBackend` config (base URL + Firebase
  token). Most of `desktop/electron/*` stays; `sidecar.ts` is retired for cloud
  builds.
- **Offline / solo mode (kept):** the existing sidecar path still works for
  single-player local play. The **DataStore abstraction** (below) is what lets the
  same backend run against local files *or* the cloud, so we don't fork the code.

---

## 3. The backend refactors (in dependency order)

### 3.1 Storage seam: introduce a `DataStore` interface

`utils/path_utils` is already the chokepoint. Wrap it:

- Define a `DataStore` protocol: `read_json/write_json`, `read_csv/write_csv`,
  `read_text/write_text`, `list`, `lock(scope)`.
- **`LocalFileDataStore`** — current behavior, for Electron/offline/dev. Keeps the
  `data/leagues/<id>/data` layout. Zero behavior change.
- **`CloudDataStore`** — Cloud SQL for the structured "hot" entities + GCS for blobs.
- The selector is an env flag (`NEXGEN_BACKEND=local|cloud`). Most code keeps calling
  helpers like `load_players_from_csv` / `load_roster`; we re-point those helpers at
  the active `DataStore` rather than editing every caller.

What goes where:

| Data | Destination | Notes |
|---|---|---|
| users / memberships / roles | Cloud SQL | Replaces `users.txt`; now keyed by Firebase uid. |
| rosters, lineups, depth charts | Cloud SQL | Concurrent owner edits need transactions. |
| standings, season_state, schedule | Cloud SQL | Queryable; serialized day-advance writes. |
| season_stats, leaders, records | Cloud SQL | Aggregations/leaderboards are SQL's strength. |
| contracts, finances, transactions | Cloud SQL | Ledger semantics, audit trail. |
| trades (state machine) | Cloud SQL | proposed→countered→accepted→executed. |
| boxscores, career archives, snapshots | GCS | Large, write-once, read-rarely. |
| logos / avatars | GCS (public-read) | Served via CDN. |

A **one-time migrator** reads each existing `data/leagues/<id>/data/*` tree and loads
it into Cloud SQL + GCS. The current 6 leagues + legacy leagues become the first test
fixtures.

### 3.2 Kill the process-global "active league"

Today `get_active_league_id()` reads a module cache / env / `active_league.txt`.
In the server, replace the module-global with a **`contextvars.ContextVar`** set by
FastAPI middleware from the request (subdomain `cbl.app...`, path `/leagues/{id}/...`,
or a JWT claim). Then `get_data_dir()` resolves against that ContextVar.

- Pro: localized change at the seam; the 220 call sites keep working.
- The per-process HMAC secret in `api/security.py` is also a global — replaced
  wholesale by Firebase token verification (next section).

### 3.3 Auth & multi-tenancy

- **Identity:** Firebase Auth. The SPA signs in (Google / email-link), gets an ID
  token, sends `Authorization: Bearer <id_token>`. A FastAPI dependency
  (`require_firebase_user`, replacing `require_bearer`) verifies it → `uid`.
- **Membership / authz:** a `league_members(league_id, uid, role, team_id)` table.
  Role ∈ {commissioner, owner, viewer}. Every request resolves
  `(uid, league_id) → role/team` and authorizes. The existing role check pattern
  (e.g. `_require_admin` in `ai_settings.py`) generalizes to
  `require_role(commissioner)` / `require_team_owner(team_id)`.
- **Invites:** commissioner generates an invite link → invitee signs in → membership
  row created with their chosen/assigned team. CPU teams have no membership.

#### Many-to-many: users ↔ leagues (an explicit requirement)

Identity is **global and singular** (one Firebase `uid` per person); membership is
**per-league and plural**. `league_members` is a many-to-many join, so:

- **Multiple commissioners running multiple leagues** = many rows with
  `role=commissioner` across different `league_id`s. Leagues are fully independent —
  separate data trees today, separate `league_id`-scoped rows in Cloud SQL. No shared
  state, no cross-league interference.
- **One person in many leagues, with a different role/team in each** = many rows,
  same `uid`, different `league_id` — e.g. commissioner of `cbl`, owner of the Dragons
  in `usabl`, viewer in a third — all under one login.

| uid | league_id | role | team_id |
|---|---|---|---|
| `alice` | `cbl` | commissioner | — |
| `alice` | `usabl` | owner | `dragons` |
| `bob` | `cbl` | owner | `sox` |
| `bob` | `usabl` | commissioner | — |

Two rules keep this correct:

1. **Authorization is always `(uid, league_id)` — never a global role.** There is no
   "what role is Alice?", only "what is Alice *in this league?*". Switching leagues
   re-resolves permissions automatically from the membership row.
2. **The login token must carry only identity, not role/team.** This is the single
   place the current code blocks multi-league membership: `api/security.py`'s
   `issue_token` bakes one `role` + `team_id` into the token at login — a hardwired
   single-league assumption. The Firebase model drops that; role/team come from
   `league_members` per request. Replacing it is what unlocks the requirement.

### 3.4 Concurrency (the multi-owner crux)

Single-player never had concurrent writers; multi-owner does.

- **Lineup / roster edits:** optimistic concurrency (version column; reject stale
  writes) instead of `api/file_lock.py`.
- **Trades:** model as a state machine row; transitions are transactional.
- **Day-advance:** must be serialized per league. A `league_sim_lock` (SQL advisory
  lock or a Firestore transaction) ensures exactly one day-advance job runs at a time;
  duplicate triggers are no-ops. This is what prevents two owners double-simming.

---

## 4. Simulation in the cloud

Per how leagues are actually played (a **day at a time**, not pitch-by-pitch), the
default path is asynchronous day-advance:

1. Commissioner (or scheduler) hits `POST /leagues/{id}/advance-day`.
2. API acquires the per-league sim lock, enqueues a **Cloud Task** → **Cloud Run Job**.
3. The job loads the league via `CloudDataStore`, runs every scheduled game through
   the **unchanged** `physics_sim` engine, writes results/standings/stats/finances,
   advances `season_state`, and generates news (§5).
4. On completion it publishes to **Pub/Sub**; subscribers push notifications and
   refreshed standings to connected owners (WSS broadcast or Firestore listeners).

Supporting modes:

- **Live spectating** keeps the existing `api/ws/sim.py` pitch-by-pitch streamer for
  "watch this game" — Cloud Run supports WebSockets (mind the 60-min request cap; a
  game is far shorter).
- **Auto-cadence leagues:** **Cloud Scheduler** cron → advance-day for leagues that
  opt into "sim every night at 8pm," so absent owners don't stall the league. CPU AI
  (§5) fills in lineups/roster moves for teams that didn't set them.
- **Batch / tuning runs** (the existing `tmp/long_term_runs`, multi-season sims) →
  **Cloud Run Jobs** with parallelism, writing artifacts to GCS. The CI KPI workflow
  (`.github/workflows/physics_sim_kpi.yml`) can target this too.

Sim compute is cheap (sub-second/game); the engine itself needs no changes — only its
**inputs/outputs** move from files to the DataStore.

---

## 5. AI layer with Vertex AI / Gemini

**Core principle: the LLM decides and narrates; the existing deterministic services
constrain and validate.** Physics and economy stay rule-based; Gemini never sets a
player's value or breaks a roster rule. Every AI action is filtered through the
existing services (`cpu_trade_evaluator`, `roster_validation`, payroll/cap checks)
before it commits. Use **controlled generation (JSON schema / structured output)** so
responses parse straight into existing models (`models/trade.py`, lineup dicts).

Rollout is ordered by value-to-risk (narrative first — text-only, no game-state risk).

### 5.1 Narrative & news — *start here* (low risk, high delight)
Wrap `news_feed`, `notification_engine`, `decision_explanations`. After each day-sim,
Gemini Flash writes game recaps, standings storylines, trade-deadline buzz, award
narratives, injury reports. Pure text; nothing to corrupt. Immediate "the league feels
alive" payoff and a safe way to wire up Vertex AI end-to-end.

### 5.2 Trades (`cpu_trade_evaluator`, `cpu_trade_proposals`)
- Quant engine still computes player value + fairness band (the guardrail).
- **Gemini Pro** proposes packages *within* the acceptable-value band, targets real
  roster needs (from depth charts), and writes the negotiation message.
- For **human-proposed** trades, Gemini responds accept / counter / reject **with
  reasoning**, where accept/counter are bounded by the fairness score — so AI GMs
  never get fleeced and never make insulting offers.
- Structured output → validated `Trade` → existing execution path. The existing
  cadence controls in `cpu_trade_proposals.py` stay as the scheduler.

### 5.3 Draft for CPU teams (`draft_ai.py`)
- Inputs: draft board + team needs + `team_strategy_profiles` + scouting ratings.
- Start with **few-shot prompted Gemini** picking within the BPA/need shortlist the
  existing heuristic produces (heuristic = fallback + constraint set).
- Later: **Vertex AI fine-tuning / batch eval** on historical draft+outcome data to
  learn a house draft style. Keep the rule-based `draft_ai` as the safety net and for
  offline/local play.

### 5.4 Lineups & depth charts (`depth_chart_manager`, `roster_auto_assign`)
Gemini sets lineups vs. the specific opposing starter and park, honoring platoon
splits and rest, output as a structured lineup → validated by `roster_validation`
before commit. Powers both CPU teams and an optional "auto-set my lineup" for owners.

### 5.5 Commissioner / owner assistant (new)
A grounded chat ("how's my farm system?", "who should I start tonight?", "summarize
the trade deadline") using Vertex AI grounding / function-calling tools that read the
existing API endpoints. RAG over the league's own standings, news, and rules.

### 5.6 Images
Migrate logo/avatar generation from OpenAI `gpt-image-1` to **Imagen on Vertex AI** to
consolidate on GCP and one billing/credentials path (or keep OpenAI — the
`openai_client.py` pattern generalizes either way). Keys move to **Secret Manager**.

### Model & cost discipline
- **Gemini Flash** for high-volume/cheap (news, lineups, trade messages); **Gemini
  Pro** for heavy reasoning (draft, multi-team trades).
- Cache prompts/context; batch per-day AI work into the day-sim job; cap per-league
  AI spend. AI is opt-in per league with a budget knob (extends the existing
  `/ai` settings router and `team_strategy_profiles`).

---

## 6. Phased delivery

Each phase ships something runnable. AI (Phase 4) can start in parallel right after
Phase 0, since narrative work doesn't depend on the data migration.

| Phase | Outcome | Key work | De-risks |
|---|---|---|---|
| **0. Lift & shift** | Existing app runs on Cloud Run behind Firebase Auth, one league, single-tenant, data on a mounted volume/GCS | Containerize `api/`; deploy Cloud Run; host SPA on Firebase; swap sidecar handshake → remote config; Firebase token verify | "Does it even run in the cloud unchanged?" |
| **1. Storage seam** | `DataStore` interface; Cloud SQL + GCS; one-time migrator for existing leagues | Define interface; `CloudDataStore`; re-point loaders; migrate `data/leagues/*` | Data model + migration correctness |
| **2. Multi-tenancy** | Many leagues + many owners concurrently; per-request league context; memberships/authz; concurrency control | ContextVar league resolution; `league_members`; `require_role`; optimistic locking; trade state machine | The "active league" global; concurrent writers |
| **3. Async sim** | Day-advance as Cloud Run Job; nightly auto-cadence; Pub/Sub notifications; live spectating retained | Cloud Tasks/Jobs/Scheduler; per-league sim lock; Pub/Sub fan-out | Serialized sim; absent-owner handling |
| **4. AI layer** | Gemini narrative → trades → lineups → draft, each guarded by existing services | Vertex AI client (Secret Manager); structured output; wrap CPU services; per-league AI budget | Determinism/fairness guardrails; cost |
| **5. Hardening** | Observability, cost controls, scale/load test, fine-tuned draft model, backups/DR | Cloud Logging/Monitoring/Trace; GCS snapshot backups; load tests; Vertex fine-tuning | Production readiness |

---

## 7. Code reuse summary

- **Reused unchanged:** `physics_sim/`, `playbalance/`, `models/`, the entire `api/`
  router surface, the React UI under `desktop/src`.
- **Reused as guardrails for AI:** `cpu_trade_evaluator`, `cpu_trade_proposals`,
  `draft_ai`, `contract_negotiator`, `depth_chart_manager`, `roster_auto_assign`,
  `roster_validation`, `team_strategy_profiles`, `decision_explanations`.
- **Refactored at the seam (not rewritten):** `utils/path_utils` → `DataStore` +
  ContextVar; `api/security.py` → Firebase token verify; loaders
  (`player_loader`, `roster_loader`, `team_loader`, `user_manager`) re-pointed.
- **Generalized:** `utils/openai_client.py` → Vertex AI client + Secret Manager.
- **Retired for cloud builds (kept for offline):** `desktop/electron/sidecar.ts`
  spawn/handshake.

---

## 8. Decisions

**Locked in:**

1. **System of record: Cloud SQL (PostgreSQL).** Relational store for
   standings/stats/leaderboards/contracts/finances + ACID for concurrent owners.
   Firestore is additive-only, brought in later for realtime notifications if needed.
2. **Offline + cloud, both first-class.** The Electron + local-sidecar single-player
   path stays a supported product. This makes `LocalFileDataStore` **permanent**, and
   is the reason the `DataStore` abstraction (§3.1) is non-negotiable: one backend,
   two storage implementations selected by `NEXGEN_BACKEND=local|cloud`. No code fork.

**Still open (decide before the relevant phase):**

3. **Cadence model:** commissioner-triggered day-advance, fixed nightly auto-sim, or
   both per-league? (Needed for Phase 3.)
4. **Image AI:** migrate to Imagen, or keep OpenAI? (Needed in Phase 4; low stakes.)
5. **AI spend posture:** default-on with a budget cap, or opt-in per league? (Phase 4.)
6. **Domain / tenancy URL scheme:** subdomain-per-league vs. path-per-league.
   (Needed for Phase 2.)
</content>
</invoke>
