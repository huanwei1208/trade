# Design Quality Brief

Put these headings in the governed `design.md`. Each needs substantive repository
evidence, not placeholders or generic best practices.

## Requirements and acceptance

State observable behavior, users/callers, success criteria, non-goals, and how each
criterion will be verified.

## Ownership and boundaries

Name the owner modules, callers, dependencies, authoritative writers/readers, and why
the boundary is cohesive. Identify facades versus business logic and adapters.

## Data and state invariants

Define units, identifiers, ordering, time semantics, allowed transitions, unavailable
states, and invariants across retries or partial results.

## Contracts and compatibility

List CLI/API/schema/parquet/engine contracts, additive or breaking effects, defaults,
migration/fallback behavior, and consumer compatibility.

## Failure and recovery

Cover invalid input, unavailable dependencies, partial failure, timeout/retry,
concurrent execution, crash windows, corrupt predecessor state, operator recovery,
and explicit failure outputs.

## Performance and capacity

Give workload assumptions, hard bounds, batching/backpressure, resource ownership,
10x behavior, timeouts, and measurement strategy. Avoid unsupported throughput claims.

## Observability and operations

Define status/error semantics, evidence identity, logs/metrics/audit records,
diagnostic commands, alerts, and how an operator distinguishes empty from failed.

## Validation strategy

Map behavior and failure states to unit, integration, contract, replay, smoke, build,
and performance checks. Tests use temporary state unless live probing is explicit and
read-only.

## Alternatives and trade-offs

Compare credible alternatives against ownership, complexity, failure safety,
compatibility, and operational cost. Explain why the chosen option wins now.

## Rollout and rollback

Describe sequencing, migration or no-migration, feature/default changes, backup and
sample verification when applicable, rollback triggers, and state restoration.
