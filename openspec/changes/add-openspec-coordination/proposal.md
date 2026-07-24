## Why

Multiple interactive windows can start independent coordinators against the same
repository. Git worktrees isolate source edits but do not identify which coordinator
may mutate one active OpenSpec change, and a paused old window can resume after a
human takeover with no fencing signal. Concurrent OpenSpec writes can therefore
silently overwrite design evidence or mix epochs.

## What Changes

- Add a standard-library `scripts/ops-coord` command that stores shared ownership,
  monotonic epochs, audit history, and short-lived operation locks under the absolute
  Git common directory.
- Require an atomic per-change claim before OpenSpec mutation and verify change ID,
  owner ID, epoch, worktree, and branch before controlled writes.
- Add explicit, confirmed human takeover that increments the epoch and fences every
  previous owner without PID-, age-, heartbeat-, or TTL-based automation.
- Add an argument-safe `run` wrapper for owned-change mutation and a `run-global`
  wrapper for serialized create, sync, archive, and other named shared operations.
- Add a Git boundary checker for worker, coordinator, and shared OpenSpec diffs, plus
  a repository-managed pre-commit hook installer and an independent CI workflow.
- Merge coordinator and worker behavior constraints into `AGENTS.md` and
  `openspec/config.yaml`.
- Add temporary-repository concurrency, fencing, locking, branch/worktree, diff
  boundary, and no-expiry tests plus concise operator documentation.

Design-quality governance applies with the `core`, `contract`, `storage`, and
`concurrency` profiles. The change adds public developer commands, atomically writes
durable coordination metadata, and protects concurrent local processes. It does not
change trading behavior, market data, DB/parquet schemas, OpenSpec internals, or the
OpenSpec executable.

## Capabilities

### New Capabilities

- `openspec-coordinator-fencing`: Local multi-worktree ownership, epoch fencing,
  controlled execution, shared-operation locking, Git boundaries, and agent policy.

### Modified Capabilities

None.

## Impact

- **Public CLI:** Adds `scripts/ops-coord claim|status|assert-owner|release|takeover|run|run-global`
  and `scripts/check-openspec-coordination.py`.
- **Persistent state:** Writes only to
  `$(git rev-parse --path-format=absolute --git-common-dir)/openspec-coordination/`;
  no runtime state appears below `openspec/` or in Git diffs.
- **Concurrency:** Per-change advisory file locks serialize ownership transitions
  while allowing unrelated changes in parallel. Per-operation global locks serialize
  only the wrapped command lifetime.
- **Compatibility:** Existing OpenSpec commands remain unchanged. Direct OpenSpec
  writes are constrained by policy and hooks, while callers opt into wrappers.
- **Data safety:** Coordination tests use temporary Git repositories and worktrees.
  No trading data, databases, parquet, models, or generated runtime assets are read
  or written.
- **Dependencies:** Python 3 standard library and POSIX `fcntl.flock`; no daemon,
  network service, third-party package, heartbeat, automatic timeout, or election.
