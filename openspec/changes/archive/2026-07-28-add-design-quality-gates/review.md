# Design Quality Gates Consensus Review

Review baseline: `2afc627`

Panel: reliability, performance, architecture, data quality, observability, news/future integration

Scores: `5, 7, 5, 4, 6, 4` (mean `5.2/10`)

Critical findings: none

Initial status: blocked before implementation

## Consensus strengths

- The direct command is cohesive under `trade dev`, with a thin CLI and isolated read-only service boundary.
- Stable rule IDs, deterministic text/JSON, explicit exit classes, and owned expiring exceptions are a sound governance base.
- Point-in-time, provenance, calibration, unknown state, write recovery, and six-role human review are the correct risk areas.
- The existing quality executor already provides offline environment, timeout, bounded output, and aggregate precedence primitives.

## P0 findings and design resolutions

| ID | Consensus | Finding | Resolution in amended design |
|---|---:|---|---|
| REVIEW-001 | 4 judges | No machine-readable, fresh six-role evidence for unresolved P0 | Add digest-bound `design-review.toml`, six role states, stable findings/resolutions, and strict approval freshness. |
| REVIEW-002 | 3 judges | Automatic changed-scope strictness and governance lifecycle were undefined | New changes require `design-quality.toml`; automatic contributor is always strict; status distinguishes not-governed from pass. |
| REVIEW-003 | 3 judges | Existing exclusive file-owner provider cannot aggregate OpenSpec artifacts | Add a supplemental aggregate plan-contributor seam; shared provider retains Markdown/TOML ownership. |
| REVIEW-004 | 3 judges | Nested child exits cannot preserve quality `1` versus infrastructure `2` | Add per-exit classification and bounded structured `details` in the parent result. |
| REVIEW-005 | 2 judges | `design-check` would use syncing `uv run` | Route it with `--frozen --no-sync` and add wrapper tests. |
| REVIEW-006 | 2 judges | Multiple changes, unbounded artifacts, paths, symlinks, and concurrent edits were undefined | Add one sorted batch step, allowlist, fixed resource caps, slug/canonical-path/symlink checks, immutable snapshot, and 2/10/100 fixtures. |
| REVIEW-007 | 2 judges | Deleting governance or required artifacts could bypass scope selection | Preserve added/deleted scope metadata and fail closed on marker/required-artifact removal. |
| REVIEW-008 | 3 judges | The checker claimed it could prove architecture from documents | Limit automation to evidence completeness/contradictions; semantic truth remains with digest-bound consensus review. |
| REVIEW-009 | 2 judges | Domain applicability and external event data could be hidden by wording | Require explicit impact declarations with reasons and compose namespaced policy profiles. |
| REVIEW-010 | 2 judges | PIT, calibration, unknown state, write safety, and external-event constraints were too shallow | Define structured predictive, storage, and external-event evidence contracts plus negative fixtures. |
| REVIEW-011 | reliability re-review | Aggregate limits allowed unbounded total batch bytes | Cap v1 batches at 100 changes and 16 MiB, checked before artifact bodies are read. |
| REVIEW-012 | reliability re-review | Historical `--as-of` could revive an expired exception for strict approval | Restrict historical dates to non-strict replay; strict approval requires the current UTC date. |
| REVIEW-013 | observability re-review | Root/dev help update was accepted but absent from tasks | Add root/dev help and its CLI contract test to tasks 2.1 and 2.5. |

## P1/P2 follow-ups accepted into implementation

- Carry policy/artifact digests, effective date, applicability, exceptions, and artifact inventory in reports.
- Treat invalid change-owned exceptions as exit `1`; reserve exit `2` for invocation/repository-policy failures.
- Add cross-artifact obligation IDs linking owners/paths/contracts/failures to spec requirements and validation tasks.
- Avoid redundant version subprocesses and quadratic duplicate-ID detection in the touched planner path.
- Update root/dev help and make design-quality the canonical pre-code phase that hands off to code-quality.

## Implementation order

1. Immutable policy, structured schemas, snapshot safety, evidence profiles.
2. Direct CLI and deterministic reports.
3. Scope metadata, aggregate contributor, nested exits/details.
4. Skill/workflow governance and forward negative corpus.
5. Full validation, fresh six-role evidence, strict approval, then implementation merge.

## Re-review

Status: approved for implementation against artifact digest `sha256:e3206f865f2a0a78d7b85d9c6896bf1aae3aa3c6de8b81f03fc0106c08f882fd`.

All six roles confirmed the final `ba4f756` design without remaining P0 findings. The machine-readable result is recorded in `design-review.toml`. Because this change bootstraps the checker itself, self-hosted strict approval remains a completion requirement before merge.

## Final implementation review

Reviewed implementation: `a1cc996bd74254f97dad153d6403bcc1e4f90fd9`

Policy digest: `sha256:660a9aa5c48c3279081976600db135faa09987635b112529a55fc6d00abe1b2a`

Artifact digest: `sha256:a07d1c8cc15a409bcb1406880312923d7f207deb9d66f4927a329a9d5a587152`

Final scores: reliability `10`, performance `9`, architecture `9`, data quality `9`, observability `9`, news/future `9`.

Final status: approved with no unresolved P0 findings.

Implementation review closed fail-open paths for immutable-policy binding, planned target coverage, current governance and artifact snapshots, exact impact-selected profiles, exception ownership and expiry, strict dates, report status/count/exit consistency, bounded output and snapshot reads, and real `QUALITY/1` versus `INFRASTRUCTURE/2` semantics. The parent now independently binds every live target, including governed, required-missing, and historical not-governed states.

Accepted residual risks:

- v1 binds the current `design-review.toml` artifact and approval metadata, but the child evaluator remains trusted to interpret the complete six-role attestation. Branch protection, reviewed code, and the human panel are the current control; v2 should expose a pure parent-side attestation verifier or signed proof.
- Timezone, fallback, per-clock confidence, and aggregate timestamp-confidence relationships are individually typed but not yet cross-field constrained. Human news/future review remains authoritative; v2 should add IANA/UTC and conditional consistency rules.
- Before report schema v2, extract the versioned parent validator from the generic executor and remove the bounded duplicate applicability scan.

Final measured capacity remained bounded: 100 ordinary changes bound in about 159 ms; 100 changes by 128 artifacts bound in about 1.64 seconds; a near-16-MiB evaluator plus parent-binding stress completed in about 7.4 seconds, below the 30-second design-step budget. No extra Git processes were introduced.

## Final validation

- `pytest -q tests/test_design_quality_*.py tests/test_quality_*.py tests/test_dev_quality_cli.py`: `295 passed`.
- Ruff format check: `45 files already formatted`; Ruff lint: all checks passed.
- BasedPyright across design-quality, quality, and their test surfaces: `0 errors, 0 warnings, 0 notes`.
- `python -m compileall trade_py tests`: passed.
- Real changed-scope `dev check`: `PASS`, 46 files, 10 results; design strict, Python type/lint/format/syntax, config, hygiene, and shell checks all passed.
- Strict text and JSON design-check smoke: `PASS`, zero findings, current UTC review, verified reviewed commit.
- Official skill validator: both repository `code-quality` and `design-quality` skills are valid.
- `openspec validate add-design-quality-gates --strict`: change is valid; only the non-fatal blocked PostHog telemetry flush reported a network warning.
- `git diff --check`: passed. No runtime or generated market data was read, migrated, or committed.
