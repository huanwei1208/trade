## Context

The repository already has language quality gates and a mandatory six-role review for medium or large changes. Those controls catch malformed code and review a particular proposal, but they do not provide a stable, executable contract for design completeness. A change can still enter implementation with no clear owner, a duplicated source of truth, an inverted dependency, an unbounded write path, or an unauditable forecast claim.

The design gate must work locally, without network access or real-data reads. It must preserve `./trade` as the public command surface, reuse OpenSpec as the source of change intent, and avoid pretending that static checks can prove an architecture is optimal. Historical OpenSpec changes are incomplete by the new standard, so rollout must be prospective rather than rewriting old records.

Stakeholders are maintainers, implementation agents, reviewers, and operators who need deterministic evidence before code is written.

## Goals / Non-Goals

**Goals:**

- Make design obligations explicit, reviewable, and machine-checkable before implementation.
- Keep policy immutable by version and domain-aware, with stable namespaced rule IDs and deterministic text/JSON output.
- Separate hard blockers from warning-first heuristics and require owned, expiring exceptions.
- Route the gate through `./trade dev` and through changed-scope quality planning for governed OpenSpec changes.
- Preserve evidence, calibration, point-in-time, unknown-state, and rollback requirements for financial/data designs.

**Non-Goals:**

- Prove that a design is globally optimal or replace human review.
- Infer architecture only from source-code metrics or ban every large file.
- Rewrite historical OpenSpec changes or change production trading/data behavior.
- Inspect real databases, parquet files, or external services.

## Design Quality Brief

### Requirements and acceptance

The user-visible requirement is a reusable guardrail against low-quality architecture across Python, TypeScript, Java, C++, Web/API, data, and quantitative work. Acceptance requires a documented workflow skill, a versioned policy, a deterministic read-only CLI, changed-scope routing, tests, and a passing six-role review with no unresolved P0 findings.

### Ownership and boundaries

- `trade_py/devtools/design_quality/` owns parsing, policy evaluation, findings, and report serialization.
- `trade_py/cli/dev.py` owns only argument handling and exit-code translation; it does not own design rules.
- `design-policy/v1.toml` is the immutable machine-readable source of rule IDs, severity, required sections, resource limits, profiles, and exception constraints.
- Each governed change owns `design-quality.toml`, which declares policy version, explicit impact applicability with reasons, and obligation mappings to owners, paths, specs, and tasks.
- Each approval owns `design-review.toml`, which records portable policy/artifact content digests, the reviewed commit, six judge results, findings, resolutions, and final status. It is excluded from the artifact digest it attests to. A reachable commit receives an additional full tree check; matching content digests remain authoritative after squash makes that commit unreachable.
- `.codex/skills/design-quality/` owns agent workflow and interpretation guidance; it references, but does not duplicate, the policy table.
- OpenSpec `proposal.md`, `design.md`, `specs/`, and `tasks.md` remain the source of change intent and evidence.
- The existing quality planner adds a supplemental aggregate contributor after ordinary file ownership routing. It delegates evaluation to the design-quality package and never steals Markdown/TOML ownership from the shared provider.

Dependency direction is `trade CLI -> dev CLI facade -> design_quality service -> filesystem/OpenSpec artifacts`. The design-quality package must not import CLI, Web, DB, market-data, or engine runtime modules.

### Data and state invariants

The checker is filesystem read-only. It may read one immutable policy version and an allowlisted snapshot of selected OpenSpec changes, but must never instantiate `TradeDB`, open production DB/parquet assets, call the network, mutate files, follow symlinks, or depend on ambient market state. Allowed change artifacts are `.openspec.yaml`, `design-quality.toml`, `design-review.toml`, `proposal.md`, `design.md`, `tasks.md`, and `specs/*/spec.md`. Policy-configured file-count, per-file byte, total-byte, and finding-count limits fail closed. Descriptor-based reads use no-follow semantics and pre/post stat signatures; a final inventory/content-digest verification rejects mixed generations before reporting.

`design-quality.toml` declares every supported impact as `applies = true|false` with a substantive reason. Applicability selects composable profiles such as `core.*`, `contract.*`, `storage.*`, `forecast.*`, and `external_event.*`. Every selected profile consumes explicit policy-named fields from `[evidence.<profile>]`; prose keywords cannot satisfy or disable required evidence. Policy-owned impact signals only warn when an `applies = false` declaration contradicts governed behavior text.

For point-in-time/predictive work, structured evidence covers decision time; event, publication, first-seen, available, and revision clocks; knowledge mode; revision and universe policy; coverage state; label maturity; leakage tests; evidence identity; calibration lifecycle; out-of-sample population/window/horizon/metrics/positive sample count/uncertainty/regime slices/baseline; and heuristic-versus-validated promotion gates. Each clock is a typed table bound to its own policy source, with explicit unavailable/estimated fallback, timezone, and confidence. Coverage, maturity, calibration, and unavailable behavior are enums, and `no_numeric_fallback` must be the boolean `true`; missing, pending, stale, or uncalibrated inputs may not silently become ordinary numeric values or success states.

For persistent writes, structured evidence covers authoritative writer, idempotency key, concurrency control, staging/validation, pointer-last or equivalent atomic visibility, crash windows, corrupt-predecessor preservation, partial-result aggregation, reader consistency, backup/hash verification, rollback, and audit trail. Schema migrations additionally select a compatibility profile whose typed fields require an additive/new version with the old version preserved, backward and forward compatibility modes, dual-read/write, non-destructive checkpointed backfill, gated cutover, restorable rollback, and a bounded legacy-retirement window.

For external event data such as news, social, macro, or on-chain, structured evidence covers a known stable source ID and source kind; typed event/publication/first-seen/available/revision clocks bound to their distinct sources; verified/contracted/public-record provenance whose source ID must match and whose reference is a non-placeholder identifier; approved licensing; the complete availability-state set; finite bounded quota/cost/concurrency/retry/circuit/queue values; enabled durable/transactional idempotency with source/event keys, bounded deduplication, and a controlled conflict policy; mandatory backpressure/DLQ/replay/tombstone behavior; correction/finality enums; and degraded/unavailable outcomes. Ingestion-now clocks, unknown identities, unlimited resources, retry forever, non-idempotent ingestion, success-only availability, numeric fallback, and unknown enum values are rejected structurally rather than by prose keywords.

### Contracts and compatibility

The public command is:

```text
./trade dev design-check <change> [--strict] [--format text|json] [--as-of YYYY-MM-DD]
```

Exit codes are `0` for pass, `1` for change-owned policy findings that fail the selected mode, and `2` for invocation or repository-policy/configuration errors. Invalid, expired, unknown, or blocker-targeting change exceptions are findings (`1`), not infrastructure errors. JSON output includes schema/checker/policy versions, policy/artifact digests, change names, strict flag, effective date, approval eligibility, governance status, applied profiles, ordered findings, applied/invalid/expiring exceptions, artifact inventory, and summary counts. Determinism means identical content, options, policy, and effective date produce identical output. The default effective date is the current UTC date. Historical `--as-of` is non-strict replay/diagnostic only; strict implementation approval rejects any non-current effective date with exit `2`, and automatic changed-scope approval never accepts an override.

The `trade` wrapper routes `design-check` through `uv run --frozen --no-sync`. Root/dev help exposes the single pre-code sequence: non-strict design pre-check, six-role consensus review, strict design approval, then implementation `dev check`. Existing `trade dev check|fix|quality|review` behavior remains. Changed-scope `check` invokes a single internal batch step with all sorted, unique applicable changes and always uses strict mode; direct strict checks also require governance. The quality executor maps nested exit `1` to quality failure and `2` to infrastructure failure, carries the bounded structured design report in a versioned `details` field rather than opaque diagnostic text, and validates the complete v1 audit field set, real ISO dates, digest/commit formats, finding/exception/artifact records, exact non-boolean summary counts, approval commit verification status, batch width, and state/count/exit consistency. Empty success, findings hidden under `NOT_GOVERNED`, missing/invalid approval provenance, contradictory status, or a suppressed blocker is an infrastructure failure rather than a pass.

Governance applies to changes with `design-quality.toml`. A change absent from the merge-base OpenSpec tree is required to add that marker; historical changes remain ungoverned until explicitly migrated. Changed-scope selection separates the all-mode inventory from actual added/deleted/modified delta: adding a new unmarked change, deleting a governance marker, deleting a required governed artifact, or modifying/deleting an existing immutable policy version fails closed. Reports distinguish `PASS`, `FAIL`, `ERROR`, and `NOT_GOVERNED`. Policy v1 intentionally accepts only `specs/*/spec.md`; unsupported layouts or unselected policy versions fail closed instead of implying configurability.

### Failure and recovery

Missing/invalid repository policy, ambiguous change selection, orphan governance requirements, malformed batch envelopes, unsafe slug/path/symlink, resource-limit breach, or unreadable/concurrently changed artifacts fail closed as exit `2`. Missing required design evidence and change-owned marker/review/exception errors yield deterministic findings and exit `1`. Change slugs match `[a-z0-9][a-z0-9-]*`; canonical change and artifact paths must remain below `openspec/changes` and may not be symlinks. Duplicate capability/requirement or task identifiers are ambiguity blockers. Human errors include remediation without stack traces. Because the checker is read-only, recovery is editing evidence and rerunning it.

### Performance and capacity

The direct checker reads one policy and one change; the internal batch checker performs linear work in selected changes and allowlisted artifact bytes. It targets sub-second direct execution for a normal change. Default v1 limits are 128 files, 256 KiB per file, 2 MiB total per change, 200 report findings, 100 changes per batch, and 16 MiB total artifact bytes per batch. Capability enumeration stops at the file cap before sorting. Reachable reviewed trees use bounded inventory output plus batch-checked/batch-read blobs, so historical blobs are size-checked before their bounded aggregate read and Git process count stays linear in changes rather than artifacts. The checker validates batch count and filesystem metadata/byte budgets before reading artifact bodies and fails excess as exit `2`. The parent bounds stdout/stderr, kills a structured producer on first stdout overflow, and preserves the original deadline even if a child closes output pipes before hanging. The aggregate design step is classified heavy to avoid competing with light checks at maximum width. It must not scan source trees, real data roots, or invoke network tools. Git scope discovery remains owned by the existing quality scope layer, not the checker. The aggregate contributor emits one subprocess step per changed scope, without a redundant version subprocess.

### Observability and operations

Text output names policy/artifact digests, governed changes, effective date, strict mode, applicability, every rule ID/severity/path/remediation, exception state, reviewed commit verification status, omitted-detail counts, and final counts. JSON provides the same fields and is embedded structurally in the parent quality report. Configuration errors remain distinguishable through exit `2`; `NOT_GOVERNED` is never rendered as `PASS`. No telemetry is emitted.

### Validation strategy

- Unit tests cover immutable policy loading, marker/obligation/Brief/review parsing, blockers, warnings, exceptions, deterministic ordering, resource/path/symlink safety, concurrent snapshots, JSON schema, and exit semantics.
- CLI tests cover lazy loading, frozen/no-sync routing, no DB construction, text/JSON output, invalid slugs/paths, explicit effective dates, and invalid changes.
- Scope/contributor tests prove added/deleted governance state and governed changed designs trigger one strict batch step while unrelated historical changes retain existing ownership checks.
- Executor tests prove nested `1`/`2` mapping, semantic envelope consistency, deadline preservation after early pipe closure, and bounded structured details preserve parent exit precedence.
- Live batch tests evaluate 2, 10, and 100 real governed snapshots; all-mode Git tests separate unchanged inventory from actual immutable-policy modifications.
- Forward/negative tests exercise point-in-time leakage, evidence/calibration promotion, unknown numeric fallback, write corruption/dual writer/partial success, data migration, external event timestamps/availability/cost/DLQ, Web/API contracts, mixed-language boundaries, and valid/invalid exceptions.
- `python -m compileall trade_py tests`, focused pytest, `./trade dev check`, strict OpenSpec validation, and the skill validator form the completion gate.

### Alternatives and trade-offs

1. **AGENTS.md prose only** was rejected because it is not deterministic, versioned at rule granularity, or directly testable.
2. **A universal architecture linter over source code** was rejected because ownership and trade-offs cannot be reliably inferred from syntax and it would reward superficial compliance.
3. **A checklist only in the skill** was rejected because different agents could interpret it differently and CI could not consume it.
4. **Retrofitting all historical changes** was rejected because it creates noise unrelated to current implementation and can fabricate design rationale after the fact.

The chosen hybrid deliberately checks evidence and obvious structural hazards while leaving architecture judgment to reviewers. This can reject incomplete good ideas, so warning exceptions are supported; hard safety blockers are not suppressible without changing reviewed policy.

### Rollout and rollback

Rollout is additive: land policy/parser/reporting first, then CLI, then changed-scope integration, then workflow documentation/skill. Existing runtime and data contracts do not change. Rollback removes the quality-provider hook and CLI routing while retaining design documents; because the gate is read-only, rollback requires no data restoration. Policy changes require version bumps and tests for compatibility.

## Decisions

### Decision 1: Structured evidence plus targeted heuristics

The gate validates a mandatory Design Quality Brief and a small set of cross-cutting hazards. This makes missing reasoning auditable without claiming semantic proof. Pure prose was too subjective; full source-code architecture inference was too brittle.

### Decision 2: Immutable TOML policy profiles and structured change evidence

TOML is already used by repository quality tooling, works on Python 3.10 through the existing compatibility path, and makes stable rule IDs reviewable. Policies live at immutable version paths and compose namespaced profiles. Change applicability, obligations, exceptions, and review evidence use explicit TOML schemas so enforcement does not depend on vague Markdown keywords.

### Decision 3: Prospective governance marker

Changes absent from the merge-base OpenSpec tree must declare governance; historical changes are routed only after explicit migration. Inventory and true Git delta remain separate so all-mode checks neither invent immutable-policy edits nor hide real policy modification/deletion.

### Decision 4: Strict mode promotes unresolved warnings

Hard blockers always fail. Strict mode also fails warnings unless a policy-valid exception names an owner, reason, and expiry. This keeps ordinary diagnostics useful while making implementation approval unambiguous.

### Decision 5: Existing quality planner uses an aggregate contributor

OpenSpec artifacts keep their ordinary shared-provider ownership. A supplemental contributor observes the whole scope after ownership routing, derives sorted change names, and emits one strict batch step that invokes the same service as the direct CLI. Per-exit classification and structured details preserve the parent quality contract.

### Decision 6: Two-phase design approval

Pre-review uses non-strict diagnostics and requires zero hard blockers. The six-role review then produces findings against portable policy/artifact content digests and a reviewed commit. After fixes, `design-review.toml` records all six roles, finding IDs, consensus priority, resolution, and final approval against the new digest. Strict mode is implementation approval: it requires fresh approved review evidence and no unresolved warning or P0. A reachable reviewed commit must contain the exact policy and governed inventory/content; after mandatory squash makes it unreachable, a fresh clone still verifies the portable digests. Changing attested artifacts makes approval stale.

## Risks / Trade-offs

- [Checklist compliance can replace thinking] -> Keep the brief concise, require alternatives and six-role review, and state explicitly that passing is necessary but insufficient.
- [False confidence from document checks] -> Enforce evidence completeness only, require explicit applicability/obligations, and leave semantic truth to digest-bound consensus review.
- [False positives] -> Use stable namespaced rules, warning-first heuristics, and owned expiring exceptions; hard blockers target missing safety evidence, not claims of architectural optimality.
- [Skill and policy drift] -> Make the skill reference policy IDs and add forward tests that compare documented commands and required sections to policy.
- [Historical changes unexpectedly fail] -> Use prospective marker/addition semantics and explicit migration.
- [Quality checks become slow] -> Limit reads to one change directory and prohibit source/data/history/network scans.
- [An extreme changed scope builds argv before the child enforces the 100-target policy limit] -> The current bounded repository scope is safe and the child fails closed; track manifest/preflight planning before expanding the repository or policy limit.

## Migration Plan

1. Add immutable policy profiles, structured schemas, checker, tests, and CLI without automatic routing.
2. Add the skill and repository workflow documentation.
3. Enable changed-scope routing only for marked changes.
4. Validate this change as the first governed example, record digest-bound consensus evidence, and rerun strict implementation approval.
5. Roll back by disabling/removing the provider hook; retain the artifacts as documentation.

## Open Questions

None blocking. Future policy expansion requires a version bump, examples, and review rather than adding broad regexes ad hoc.
