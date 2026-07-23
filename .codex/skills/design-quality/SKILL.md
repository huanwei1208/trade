---
name: design-quality
description: Govern medium or large trade changes before implementation with evidence-backed architecture boundaries, explicit risk profiles, an OpenSpec Design Quality Brief, six-role consensus review, digest-bound approval, and strict design checking. Use for DB/schema or storage changes, trading or forecast semantics, public CLI/API/data contracts, external-event ingestion, runtime concurrency, workflow orchestration, C++ engine behavior, or cross-module refactors; also use before merging those changes.
---

# Design Quality

Keep architecture judgment human-reviewable and make its evidence mechanically
complete. This skill governs design before `$code-quality` governs implementation.

## Route the change

1. Read `AGENTS.md`, run `git status -sb`, and inspect the real caller, owner,
   contracts, tests, and data paths.
2. Treat a typo, one-line local fix, or documentation-only correction with no public
   contract or state change as small. Record the reason and continue with
   `$code-quality`.
3. Treat DB/schema/storage changes, trading or forecast semantics, public contracts,
   external-event data, runtime concurrency, workflow orchestration, C++ engine
   behavior, and cross-module refactors as governed medium/large changes.
4. For governed work, read [references/workflow.md](references/workflow.md) and
   [references/brief.md](references/brief.md). Read
   [references/profiles.md](references/profiles.md) when any non-core impact applies.

## Govern before code

Use a dedicated implementation worktree and create an OpenSpec change before editing
production code. The change must include:

- `design-quality.toml` with every v1 impact declared `true` or `false` and a
  substantive reason;
- obligations mapping owners, paths, contracts, failure states, spec requirements,
  and validation tasks;
- a substantive Design Quality Brief in `design.md`;
- specs and tasks that make acceptance and validation traceable.

Run the diagnostic pre-check:

```bash
./trade dev design-check <change>
```

Resolve its findings, then use `.agents/skills/review-this/SKILL.md` for the required
six-role review in a separate review worktree. Keep semantic architecture judgment in
the review; never treat keyword presence or a green checker as design approval.

Record the resolved, digest-bound panel evidence in `design-review.toml`, then run:

```bash
./trade dev design-check <change> --strict
```

Do not begin implementation until strict approval passes. Historical `--as-of` output
is diagnostic only and cannot approve implementation.

## Hand off to implementation

After strict approval, invoke `$code-quality`, load its shared and relevant language
references, implement the smallest coherent slices, test each behavior change, and
commit each validated unit. If implementation changes the approved design artifacts,
the digest becomes stale: stop, re-run the panel as needed, refresh review evidence,
and regain strict approval.

Before merging medium/large work, run the six-role review again against the actual
implementation, resolve every P0, and complete both design and code-quality gates.

## Refuse paper compliance

- Do not invent owners, risks, capacities, rollback steps, or review approvals.
- Do not mark an impact false merely to avoid its profile.
- Do not replace unavailable financial evidence with a neutral number or success.
- Do not use blanket exceptions. Exceptions require a known suppressible warning,
  owner, reason, expiry, and visible residual risk.
- Do not approve catch-all modules or speculative abstractions without ownership and
  consumer evidence.
- Do not modify real data while collecting design evidence.

## Report the gate

State the change name, selected profiles, diagnostic and strict results, panel status,
resolved and residual risks, approved digest, and the exact handoff to `$code-quality`.
