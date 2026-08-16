# Codex — First Prompt

Paste the block below as the **very first message** to Codex (or any new coding
agent) when picking up this project. It forces proper onboarding + a green-gate
check before any code changes, and keeps you in the loop on the first real
decision. Background on everything it references lives in
[`CODEX_HANDOFF.md`](CODEX_HANDOFF.md).

---

## Initial onboarding prompt (copy/paste verbatim)

```text
You're taking over development of NexGen-BBPro, a baseball-league simulation
game (Electron + FastAPI + a physics sim engine, deployed to Google Cloud Run +
Firebase).

Before writing any code, onboard:
1. Read docs/CODEX_HANDOFF.md in full, then AGENTS.md and README.md. Follow the
   pointers they give.
2. Install the backend deps: pip install -r requirements-server.txt into the
   project venv.
3. Verify the suite is green using the project's gate:
   python scripts/run_tests_isolated.py
   (per-file isolation — a plain `pytest` run is EXPECTED to show cross-file
   pollution failures that are NOT real bugs; handoff doc section 5 explains why).

Then, before doing any feature work, report back with:
- A 5-8 bullet summary of the architecture and current state, so I can confirm
  you understand it.
- The result of the green gate (X/201 files green).
- The "pick-up-here" list from the handoff doc section 7, and which item you'd
  recommend starting with and why.

Do not change code or bump versions yet — just onboard, verify, and propose a
plan. Wait for my go-ahead on which task to start.
```

---

## Why this shape

- Codex auto-reads `AGENTS.md`, which routes it to `CODEX_HANDOFF.md` — but
  telling it to read the handoff doc **in full first** stops it skimming past the
  testing/pollution traps.
- Running the **green gate and reporting the number** surfaces env problems
  (missing deps, wrong venv) up front and proves it can reproduce a known-good
  baseline before touching anything.
- Asking it to **summarize its understanding + propose a plan, and wait** keeps
  you in the loop on the first real decision (which task to start).

## Follow-up prompt (once you pick a task)

Be specific and re-state the verification gate. Example for the biggest ready
item:

```text
Start on S1-10 (parallel day simulation). Follow docs/specs/S1-10_parallel_day.md
exactly. Its release gate is byte-parity of the three benchmark_sim_days.py
digests (serial vs parallel) — treat that as mandatory, and note it changes
serial seed values so re-baseline the pre-change code first. Record the outcome +
commit hash in docs/deep_review_plan.md.
```

For any engine/calibration change, the equivalent gate is
`scripts/physics_sim_season_kpis.py --strict` green on seeds 1 and 2 (162 games).

## One cleanup to settle early

`AGENTS.md` currently contradicts itself on the Python venv (one line says
`.venv`, another `.venv2`). Decide which is canonical and have Codex fix that
line so it isn't guessing every session.
