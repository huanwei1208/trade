# Multi-Agent Consensus Review (review-this)

Use this skill before implementing or merging medium/large changes. Launch N
specialized judge agents in parallel, let each audit from their role, then
synthesize consensus. The goal is to catch bugs, design flaws, and usability
problems early — before they become entrenched.

## When to invoke

- Medium or large changes as defined in AGENTS.md (DB/schema changes, data
  storage changes, trading semantics, Web API contracts, C++ engine behavior,
  workflow orchestration, cross-module refactors).
- Any change that touches data ingestion correctness.
- Before merging a feature branch back to master.
- When explicitly asked for a "review", "judge", "audit", or "consensus".

Small local fixes (typo, one-line bug, doc update) do NOT need full review.

## Judge roles

The six standard roles cover the main failure modes of a quant trading system.
All roles MUST read real code (not guess), cite file:line references, and
rate every finding by severity:

| Severity | Meaning |
|----------|---------|
| CRIT     | Data loss, silent wrong data, crash, security issue, money-at-risk |
| HIGH     | Wrong behavior, major scalability break, broken contract |
| MED      | Operational pain, performance issue, confusing UX, drift risk |
| LOW      | Cosmetic, dead code, style, micro-opt |

### Standard judge panel (6 roles)

1. **Reliability & Resilience** — error handling, retries, idempotency, data loss
   prevention, recovery, crash safety, concurrent execution, locking.
2. **Performance & Scalability** — throughput, QPS control, memory, parquet I/O,
   bus congestion, pool sizing, what breaks at 10× scale, N+1 queries.
3. **Architecture & Design** — module boundaries, abstraction quality, meta-driven
   extensibility, separation of concerns, plugin patterns, CLI cohesion, leaky
   abstractions, hardcoded vs config-driven.
4. **Data Quality & Validation** — OHLCV validation, outlier detection, timestamp
   handling, timezones, look-ahead bias, cross-source reconciliation, gap
   detection, schema evolution, silent corruption vectors.
5. **Observability & Operability** — CLI usability, logging, health/doctor
   commands, web dashboard, alerting, audit trail, error messages, backup/DR,
   SLO/SLI foundations, command sprawl.
6. **News/Sentiment & Future Integration** — bus channel isolation for NLP,
   unstructured data schema, rate limiting for heterogeneous sources,
   backpressure/DLQ, embedding storage, plugin pattern generalization.

For targeted reviews (e.g. web-only, engine-only), prune the panel to the
relevant roles. For broad reviews, launch all six in parallel.

## How to run a review

### Step 1: Create review worktree

```bash
# From repo root
git worktree add ../trade-wt-review-<slug> -b wt/review-<slug>-<yyyymmdd>
```

All judge agents MUST work in the review worktree, never in the main working
tree or feature worktree. This prevents review agents from colliding with
in-flight implementation.

### Step 2: Launch 6 judge agents in parallel

Use the Agent tool with `run_in_background: true`, `subagent_type: "general-purpose"`,
and the prompt template below for each role. All agents must receive the SAME
worktree path and scope description so they review the same code.

**Prompt template per judge (replace {ROLE_NAME}, {ROLE_FOCUS}, {SCOPE}):**

```
You are **Judge N: {ROLE_NAME}** for the codebase at `/data00/home/guohuanwei.cztj/git_files/<review-worktree>`.

Focus: {ROLE_FOCUS}

Scope of this review: {SCOPE}

Read actual code (don't guess). Cite file:line for every finding.
Rate each finding CRIT/HIGH/MED/LOW.

Your report MUST contain:
1. Strengths in your focus area (3-5 concrete things done well with file:line)
2. Concrete issues, each with: severity, file:line, what the bug is, why it matters,
   and a specific fix suggestion.
3. Score (1-10) for your focus area with justification.
4. Priority-ordered action list (P0 this week / P1 next sprint / P2+ backlog).

Do NOT modify any code. This is an audit-only review.
Be constructively critical — do not just praise; find real problems.
```

Assign concrete role descriptions from the "Standard judge panel" section above
for {ROLE_NAME} and {ROLE_FOCUS}.

### Step 3: Wait for all 6 judges to complete

Collect all six reports. Do NOT start synthesis until all have returned.

### Step 4: Synthesize consensus

Identify:
- **Unanimous findings**: mentioned by 3+ judges → must fix before merge.
- **Two-judge agreement**: mentioned by 2 judges → high priority fix.
- **Single-judge findings**: evaluate on merit, include if well-evidenced.
- **Disagreements**: if judges contradict each other, launch one reconciliation
  round (send the disagreement to a new agent or back to one of the disagreeing
  judges for rebuttal, max 1 round of debate).

Produce a consensus report with:
- Top 3-5 strengths (all judges agree)
- P0/P1/P2 action items with file:line (sorted by consensus count × severity)
- Consensus score (average across judges, with explanation of spread)
- Recommended implementation order

### Step 5: Create implementation worktree and act

```bash
git worktree add ../trade-wt-fixes-<slug> -b wt/fixes-<slug>-<yyyymmdd>
```

Fix P0s first, commit each logical unit per AGENTS.md commit rules, push every
3-5 commits, then merge back to master.

### Step 6: Update this skill if judges found a blind spot

If a new failure mode is discovered that none of the 6 roles catch, add a new
judge role or extend an existing role's prompt.

## CLI entry point (trade dev review)

The `trade dev review` command scaffolds a review:

```bash
trade dev review [--scope <path>] [--slug <name>] [--roles r1,r2,...]
```

It prints the worktree path and the prompts to use (or, when running inside
an agent session, can be used as documentation for how to orchestrate the
review). The command itself does NOT launch agents; that requires an agent
runner (this skill / the AI orchestrator).

## Customization

Per-module extra roles can be added for specialized audits (e.g. C++ engine
memory-safety, web security, backtest overfitting). Define them under
`review-this/roles/` as additional markdown files and they become available
to the panel.
