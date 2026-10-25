# Development Process

Small-scale personal apps. Pragmatic, no over-engineering.

## Agent Roles

| Role | Agent | Tier | Purpose |
|------|-------|------|---------|
| Orchestrator | main | Planner | User dialogue, scope, PRD, task decomposition, synthesis |
| Scout | `scout` | Builder | Code mapping, pattern location — Phase 1 research |
| Test Writer | `test-writer` | Builder | Writes behavioral tests, confirms RED — Phase 2 |
| Dev | `coder` | Builder | Bounded implementation tasks — Phase 2/3 |
| QA | `qa` | Builder | Full suite runs, behavior verification — Phase 2/3 gate |
| Architect | (escalate to user) | Human | Design blockers — see triggers below |
| Reviewer | `reviewer` | Builder | Pre-gate diff review (Phase 2 + Phase 3 gates) |

**Architect (Human) escalation — invoke when ANY trigger fires:**
- Same task returns `ISSUES:` twice with same root cause
- Task spec spans 3+ subsystems (e.g. schema + API + UI + auth)
- Orchestrator's Checkpoint B self-review fails on 2nd pass (decomposition keeps producing >5-file tasks)
- Sub-agent escalation request: any sub-agent returns `NEEDS_ARCHITECT — <reason>`

**Handler:** user (human). The Architect role is never delegated to an LLM. Orchestrator pauses, presents the decision point in ≤5 bullets, waits for user direction. When user resolves: orchestrator appends a one-line ADR to [docs/adr.md](docs/adr.md), then resumes Planner dispatch with Builder sub-agents.

## Orchestrator Behavior

The main agent (Orchestrator) is the project lead. It owns dialogue with the user and delegates all research, implementation, and verification to sub-agents.

**Reporting:** After each sub-agent completes, report one-sentence TL;DR. Do not narrate internals or paste raw output. Full details only if user asks.

```
Scout: found existing auth module at src/auth — reusing.
Dev [task 2/4]: user store created. Tests pass.
QA: 3/4 PRD behaviors pass. should_redirectOnLogout fails — redirect missing.
```

**Economy rules:**
- Never read a file a sub-agent already touched in the same session — trust the diff receipt.
- Read PRD once at Phase 2 kickoff; cache scope/behaviors/out-of-scope mentally. Do not re-read mid-phase.
- Read cached Scout report (`docs/<n>-<feature>-scout.md`) first. Only re-spawn Scout if report missing or stale.
- If summarizing sub-agent output to user, use the 1-sentence TL;DR format. Never paste raw diffs.

**Blocker vs. pragmatic default:**
- **Raise to user:** ambiguous PRD requirement, conflicting constraints, security decision, data loss risk
- **Take default silently:** file/folder naming (follow existing), library version (latest stable), minor style choices, implementation approach when PRD is unambiguous
- Document every default taken as an assumption in the Phase 2 kickoff list

**Self-review checkpoints (max 2 passes each):**

Checkpoint A — PRD draft (end of Phase 1, before presenting to user):
1. Every behavior maps to a user story — no orphaned behaviors
2. Behaviors are observable outcomes, not implementation steps
3. Out of scope explicitly cuts anything not needed for personal use
4. No architecture decisions smuggled into behavior descriptions

Checkpoint B — Decomposition (Phase 2 kickoff, before first sub-agent call):
1. Every behavior from PRD has a corresponding test-writer spec
2. Every task is bounded (≤5 files, single goal, verifiable)
3. No duplicated work across tasks or behaviors
4. No task covers more than one behavior's worth of work
5. Every task has a Verify command (unit test or behavioral test reference) — no exceptions

Fix and re-check on failure. After 2nd pass: proceed with best result, note remaining concerns in kickoff assumptions.

**Handling sub-agent `ISSUES:` output:**

When a sub-agent returns with `ISSUES: <list>` after its 3 self-review iterations:
1. **Re-spawn with refined spec** — if ISSUES suggest the spec was unclear (ambiguous goal, missing context file). Tighten the spec, retry once.
2. **Escalate to user** — if ISSUES indicate a real requirement gap or design tradeoff (e.g., "two valid approaches, no PRD guidance"). Raise as blocker.
3. **Accept and log** — if ISSUES are cosmetic (style preferences, naming nits). Note in kickoff assumptions log, move on.

Never spawn the same agent twice with the same spec. If re-spawn would be identical, escalate instead.

**Phase transition discipline:**

The PRD status field (header of `docs/<n>-<feature-name>.md`) is the source of truth for current phase. Orchestrator reads it at every kickoff, trusts file over session memory.

Hard rules:
- Orchestrator updates PRD status field ONLY on **explicit** user instruction (e.g. "move to implementation", "transition to refactoring", "advance phase"). Never implicitly — gate completion alone does NOT trigger transition.
- Before any transition, orchestrator runs the current phase's gate checklist and reports pass/fail per item. User decides whether to advance despite any failures.
- Orchestrator NEVER signals "phase complete" until every gate checklist item passes (or user explicitly accepts the gap).
- Phase work matches PRD status. If user requests work belonging to a different phase, refuse and surface the mismatch (unless the request itself is the transition instruction).

Mismatch handlers:

| User request | Current PRD status | Orchestrator response |
|--------------|--------------------|-----------------------|
| "implement X" | none (no PRD) | "No PRD exists. Start Phase 1 first to define behaviors." |
| "implement X" | `exploration` | "PRD in Phase 1. Run gate checklist? If you then say 'move to implementation', I'll update status and start Phase 2." |
| "move to implementation" (explicit) | `exploration` | Run Phase 1 gate checklist. Report pass/fail. If user confirms, update status to `implementation`, start Phase 2. |
| "refactor X" | `implementation` | "Current PRD in Phase 2. Options: (a) finish implementation, (b) pause and write separate refactor PRD." |
| "ship/deploy" | `refactoring` or earlier | "Phase 3 not done. Remaining gate items: [list]." |
| "add feature Y to this work" | `implementation` | "Y not in PRD §6 behaviors. Options: (a) add to current PRD (re-run Phase 1 gate), (b) defer to follow-up PRD." |
| `status.md` shows active feature X | user asks "let's start feature Y" | "Feature X active in Phase Y. Options: (a) finish X, (b) abort X (see Abort section), then start Y." |

Trivial features (fast-path) still transition through phases — the gates compress, but the discipline remains. Orchestrator runs gate checklist verbally at fast-path end.

## Phases

### Phase 1: Exploration

**Goal:** Lock down requirements in a detailed, actionable PRD before any production code is written.

**How it works:**
- Discuss the feature/app idea collaboratively
- Align on scope — cut anything that isn't essential for personal use
- Define concrete behaviors (these become acceptance criteria for Phase 2)
- Optionally build a clickable prototype to explore UX ideas (see Conventions)
- **Research delegation (before writing PRD):**
  - Existing codebase → delegate to Scout (`scout`). Save the report to `docs/<n>-<feature>-scout.md`. Phase 2 sub-agents read this file; do not re-spawn Scout.
  - Greenfield or external tech → use own knowledge; optionally spawn general agent for web research.
  - Scout report contents: file:line table, key patterns, reuse candidates. ≤100 lines.
- Write the PRD to `docs/<NNN>-<feature-name>.md` (3-digit padded sequential)

**New app?** The first PRD should broadly explore the domain and identify the main features, then slice them vertically so each subsequent PRD targets one deliverable slice.

**PRD structure:**

Each PRD starts with a status line at the top:

```
Status: exploration
```

Status meanings:
- `exploration` — requirements being defined, no production code yet
- `implementation` — PRD signed off, code being written
- `refactoring` — implementation complete, tests passing, now cleaning up
- `done` — refactoring finished, merged to main

Followed by:
1. Overview — what and why, in 2-3 sentences
2. User stories — short, concrete
3. UI/UX — screens, flows, key interactions
4. Technical approach — stack, architecture decisions, constraints
   - **Decisions:** 3-6 one-liners capturing key choices
     - "Chose X over Y because Z"
     - "Assume A; if false, revisit"
     - "Risk: B; mitigation: C"
5. Data model / state shape — entities and key invariants (even a rough sketch)
6. Behaviors — observable outcomes the feature must produce. Each becomes a behavioral test.

   Format per behavior:
   ```
   - should_[verb][Object]: [what the user/caller observes when this works]
     Type: api | playwright
   ```
   Naming rule: `should_` prefix, camelCase, verb-first. Example: `should_redirectToLoginWhenUnauthenticated`.
7. Out of scope — what we're explicitly not doing
8. Retrospective (filled at Phase 3 done) — what surprised us, what we'd decide differently. ≤5 bullets.

**Gate checklist:**
- [ ] PRD has: overview, user stories, UI/UX, technical approach with decisions, data model, behaviors, out of scope
- [ ] Each behavior uses `should_` naming and specifies type (api | playwright)
- [ ] Out of scope is explicit
- [ ] `docs/status.md` shows no other active feature (or update to reflect new PRD)
- [ ] Status set to `exploration`
- [ ] Feature branch created: `feature/<name>`
- [ ] PRD committed with message: `PRD: <feature>`

**After gate:** Update PRD status to `implementation`.

**Model:** Planner orchestrator + Builder sub-agents (`scout`)

### Phase 2: Implementation

**Goal:** Build exactly what the PRD specifies. All behaviors from the PRD implemented and passing.

**Kickoff (mandatory):**
Before writing any code, Orchestrator must:
- Read PRD status header. If status != `implementation`, halt and surface mismatch to user.
- Read `docs/status.md` first to recover prior session state. Confirm active feature matches this PRD.
- Check for `docs/<n>-<feature>-scout.md`. If exists, use as cached code map — do not re-spawn Scout.
- Reference the PRD
- Restate scope and out-of-scope
- Reference behaviors by name (PRD §6) — do not re-quote unless user asks
- List assumptions explicitly
- If blocked, ask — don't invent

**Fast-path (trivial features):**

If feature meets ALL: 1 behavior, ≤2 tasks, no DB/auth/routing changes, no new dependencies — skip sub-agent ceremony.
Orchestrator writes behavioral test + implements inline, then runs the verify command. Use sub-agents only when feature is non-trivial.

Document the fast-path decision in kickoff assumptions.

**Decomposition (mandatory before any code):**

Step 1 — list behaviors from PRD (`should_` names).
Step 2 — for each behavior, run the TDD cycle:

```
RED:    test-writer writes behavioral test, confirms it fails
GREEN:  coder implements tasks until behavioral test passes
        (tasks may include optional unit tests for internal logic)
VERIFY: qa confirms behavioral test + any unit tests pass
```

Behavior spec format (handed to `test-writer`):
```
### Behavior: <should_name>
Description: <observable outcome>
Type: api | playwright
Read: [existing test files]
Suite command: <command to run this single test>
```

Task spec format (handed to `coder`). Each task must be "bounded" — single goal, ≤5 files:
```
### Task: <name>
Behavior: <should_name this task contributes to>
Goal: <one sentence>
Modify: [file1, file2]
Read: [file3, file4]
Verify: <unit test command, or "run behavioral test: <cmd>">
Out of scope: [list]
```

After all behaviors complete, hand the full suite + behavior names to `qa`. Pass → proceed to gate. Fail → back to RED/GREEN cycle for failing behavior.

**Fall back to Orchestrator inline (skip sub-agent) when:**
- Task touches cross-cutting concerns AND the change is mechanically clear (e.g., rename env var across 4 files, add CORS header in middleware + tests + docs)
- `coder` returns `SCOPE_TOO_BROAD` after re-decomposition failed

**Escalate to Architect (user) when:**
- Task requires a DESIGN choice (where new state lives, how subsystems communicate, which abstraction wins)
- See Architect triggers at top of file

Decision rule: "Can I describe the change in one unambiguous sentence?" → Orchestrator inline. Otherwise → Architect (user).

**How it works:**
- Implement features per the PRD
- Write tests following the test strategy (see Defaults)
- Tests must be runnable via a single command documented in `docs/index.md`, and passing before handoff
- If a change affects behavior or acceptance criteria, stop and update the PRD (or write a follow-up PRD). No "quick improvements."
- User performs manual testing after: execute every PRD behavior once end-to-end

**When manual testing finds issues:**

Escalate based on symptoms:
- **Small fix** — discuss in chat, correct, re-run tests
- **Bigger problem** — soft reset, write a focused follow-up PRD. Triggers:
  - Same fix needed twice (regression loop)
  - Can't explain the failure in 1-2 sentences
  - Fix requires touching multiple areas (e.g. schema + UI + tests) AND post-test discovery (if known up-front, NEEDS_ARCHITECT should fire during decomposition instead)
  - New behavior needed that isn't in the PRD
- **Full fail** — drop the branch, restart with better instructions. Triggers:
  - Tests become flaky / nondeterministic
  - Repeated regressions after follow-up PRD
  - Requirements still unclear after revision

**Abort (rare):** user decides feature shouldn't ship. Orchestrator: confirm intent, then guide user to (1) delete feature branch, (2) delete `docs/<n>-<feature>-scout.md` if present and reset `docs/status.md` to `No active feature.`, (3) leave PRD in place with status reverted to `exploration` OR delete PRD if scrapped entirely. No commit — branch deletion handles it.

**Gate checklist:**
- [ ] All automated tests passing locally
- [ ] All tasks handed to `coder` completed and verified
- [ ] `qa` full suite run: all PRD behaviors pass
- [ ] `/simplify` skill pass over changed files: address surfaced issues before reviewer
- [ ] `reviewer` pass over diff: any severity-🔴 finding loops back to Dev cycle (coder fix → qa re-verify)
- [ ] Confirm token spend within budget (see Caching discipline). Tools: harness telemetry, or `/caveman-stats` if caveman plugin installed.
- [ ] User has executed every PRD behavior once end-to-end
- [ ] User has instructed transition; PRD status updated to `refactoring`
- [ ] `docs/status.md` reflects current feature + Phase 2 state
- [ ] `docs/index.md` created or updated (bootstrap template if missing)
- [ ] Committed with message: `Impl: <feature>`

**Model:** Planner orchestrator + Builder sub-agents (`test-writer`, `coder`, `qa`)

### Phase 3: Refactoring

**Goal:** Consolidate and improve, keeping tests green throughout.

**Kickoff (mandatory):**
Orchestrator must:
- Read PRD status header. If status != `refactoring`, halt and surface mismatch to user.
- Read `docs/status.md` for prior session state.
- Verify Phase 2 gate items all passed (in particular: tests green, behaviors verified).
- List refactor opportunities by category before proposing tasks.

**How it works:**
- Orchestrator identifies refactor opportunities from one of these named categories:
  - `rename` — symbol or file name change, no behavior change
  - `extract` — pull duplicated code into a function/module
  - `inline` — collapse a single-caller abstraction back
  - `dedupe` — remove copy-paste, consolidate to one source
  - `dead-code-removal` — delete unused exports, vars, files
- Each refactor opportunity becomes a task using the Phase 2 task spec format, with `Goal:` prefixed by the category (e.g. `Goal: rename UserService → AccountService`)
- Hand each task to `coder`; run `qa` after each task — never break green
- No new features. No behavioral test changes. If a test must change to accommodate refactor, it's a PRD change.
- Observable behavior unchanged: UI, routes, persisted data shape, public component props

Note: /simplify skill not run in Phase 3 — would be self-referential. Phase 3 IS the simplification work.

**Gate checklist:**
- [ ] All tests passing
- [ ] All tasks handed to `coder` completed and verified
- [ ] `qa` final suite run: all PRD behaviors pass
- [ ] `reviewer` pass over diff: any severity-🔴 finding loops back to refactor cycle
- [ ] Confirm token spend within budget (see Caching discipline). Tools: harness telemetry, or `/caveman-stats` if caveman plugin installed.
- [ ] No change in externally observable behavior (UI, routes, persisted data, public props)
- [ ] PRD Retrospective section (section 8) filled with ≤5 bullets
- [ ] User has instructed transition; PRD status updated to `done`
- [ ] `docs/index.md` updated
- [ ] Committed with message: `Refactor: <feature>`
- [ ] Scout report (`docs/<n>-<feature>-scout.md`) deleted
- [ ] `docs/status.md` reset to `No active feature.`
- [ ] PRD moved to `docs/done/<NNN>-<feature-name>.md`
- [ ] Feature branch merged to `main`

**Model:** Planner orchestrator + Builder sub-agents (`coder`, `qa`)

## Git

- `main` stays clean and deployable
- Feature branch created at Phase 1 sign-off: `feature/<name>`
- Each quality gate = a user commit on the feature branch
- AI never commits — user controls all commits
- Merge to `main` after Phase 3

## Repo Index

`docs/index.md` — lightweight map of the repo.

- Folder tree + one-liner per key file
- How to run the app
- How to run tests
- Links to current/active PRDs
- Updated at the end of Phase 2 and Phase 3
- Not exhaustive — just enough for fast orientation on a cold start
- AI consults this first when picking up an existing project

## Status

Single central file `docs/status.md` tracks the currently active feature. One feature at a time — process explicitly forbids parallel features.

Contents:
- Active feature ID + phase (e.g., `003-user-auth (Phase 2: implementation)`)
- Behaviors done / in-progress / not-started
- Last assumption decisions
- Open ISSUES from sub-agent returns
- Next action

When no feature is active: `status.md` contains `No active feature.`

**Size cap:** ≤50 lines. Older entries collapse into single "Earlier sessions: ..." line.

**Write cadence:** Orchestrator updates at end of each session (before user ends turn or topic shifts). Single write per session.

**Reset:** at Phase 3 done, orchestrator resets file to `No active feature.` (no deletion — git history holds the archive).

**Concurrency rule:** if `status.md` shows an active feature and user starts a new one, orchestrator refuses with "Feature X currently active in Phase Y. Finish or abort it first."

## Caching discipline

Provider-agnostic. Most LLM harnesses cache stable prompt prefixes (Anthropic prompt cache, similar in others). Maximize cache hits during sub-agent spawn bursts:

- Do not edit CLAUDE.md, process.md, or `.claude/agents/*.md` mid-feature. Treat as frozen between Phase 1 sign-off and Phase 3 done.
- Orchestrator: keep a stable "feature state" preamble at start of each turn (PRD §6 behavior list + current step). User-injected mid-stream messages go after this block, not before.
- Sub-agent specs (Behavior spec, Task spec) follow the documented format exactly. Reordering fields breaks cache.
- Tools/permissions list stable across spawns in same feature.

Cache hits reduce input token cost 50-80% during TDD bursts.

**Token budgets:**
- Fast-path feature: ≤30k input + output total
- Normal feature: ≤150k input + output total
- Architect escalation triggers above 200k (something off — re-decompose)

## Defaults

Apply to all projects unless a PRD explicitly overrides.

- **Formatter + linter:** Prettier + ESLint (or equivalent for the stack, e.g. Python: ruff/black; Go: golangci-lint)
- **Secrets:** Never paste secrets/keys/tokens into prompts or code. Use `.env` + `.gitignore`. Sanitize logs before sharing.
- **Error handling:** Fail fast with clear messages. No silent swallows.
- **Test strategy:**
  - Behavioral test (required per behavior): `should_` naming, API-level or Playwright. Written before implementation (RED first).
  - Unit test (optional per task): only for non-trivial internal logic. Written by `coder` as part of the task.
  - No standalone integration layer — behavioral tests cover API boundaries by definition.
- **Test environment:**
  - DB: in-memory by default, reset per test run. Stack mapping:
    - Node/SQL → better-sqlite3 `:memory:` or sql.js
    - Node/Mongo → mongodb-memory-server
    - Python/SQL → SQLite `:memory:` or pytest tmp fixtures
    - Go → embedded SQLite in temp dir
  - Server: `npm test` (or equivalent single command) handles bringing up any required service. No manual setup.
  - Playwright: spawned with a known port via the test runner; teardown automatic.
  - No shared test state between runs — every run is isolated.
- **External services:**
  - Default: mock at the HTTP boundary (e.g. MSW for browser/node, vcr-style cassettes for Python, httptest in Go).
  - Real calls only when `E2E_LIVE=1` env var is set, AND test is tagged `@live`.
  - Never call paid APIs in unit/behavioral tests unattended. PRD must explicitly opt-in.
- **Storage:** Define where state lives in the PRD (local, IndexedDB, server, etc.)

## Conventions

- **Tech stack:** Discuss per project. Expect React / Vite / PWA frequently.
- **PRD files:** `docs/<NNN>-<feature-name>.md` (3-digit zero-padded sequential: `001`, `002`, ...). When PRD reaches `done` status, move to `docs/done/<NNN>-<feature-name>.md` to keep active PRD list visible.
- **Prototypes:** Optional Phase 1 output. HTML/JS/CSS only, stored in `docs/prototypes/<feature-name>/`. Kept for reference but never used as a base for production code.
- **Scope discipline:** If it's not in the PRD, it doesn't get built. If we discover something new mid-implementation, stop and update the PRD first. No "quick improvements."