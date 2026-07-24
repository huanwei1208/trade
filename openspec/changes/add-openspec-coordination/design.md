## Context

The repository mandates isolated worktrees for code changes, but worktrees share the
same OpenSpec namespace and can be driven by multiple long-lived interactive windows.
Git alone cannot answer which coordinator owns one change, whether a resumed window
has been superseded, or whether two create/sync/archive commands overlap. The guard
must be local, auditable, dependency-free, and outside OpenSpec itself.

The requested safety model is lease-free fencing. Ownership persists until the valid
owner releases it or a user explicitly authorizes takeover. Process liveness and age
are diagnostic only; they never transfer authority. An ambiguous or corrupt state
must stop writes rather than guess.

## Goals / Non-Goals

**Goals:**

- Allow at most one current owner record per OpenSpec change while permitting
  unrelated changes to be claimed in parallel.
- Increment a durable epoch for every claim or takeover and reject superseded owner
  and epoch pairs.
- Bind ownership to the exact absolute worktree and branch.
- Make ownership transitions and JSON visibility atomic and record append-only audit
  events for transitions and wrapped commands.
- Serialize named shared OpenSpec operations only for their command duration.
- Reject unsafe branch/diff combinations locally and in CI without trusting
  workstation ownership state in CI.

**Non-Goals:**

- Modify or fork OpenSpec, mediate every filesystem write, or add a daemon, service,
  socket, heartbeat, TTL, automatic release, election, failover, or process killing.
- Automatically infer ownership from branch names, PIDs, task count, worktree count,
  window count, or elapsed time.
- Build a general multi-agent scheduler or change unrelated repository workflows.

## Design Quality Brief

### Requirements and acceptance

`claim` shall atomically create ownership only when no owner exists. `takeover` shall
require interactive confirmation or `--yes`, preserve predecessor identity and
reason, and allocate a larger epoch. `assert-owner` and owner-authorized `release`
shall compare change, owner, epoch, absolute worktree, and branch while holding the
change lock. Every mismatch shall emit `COORDINATOR FENCED` with local and effective
identity and return nonzero without repair or side effects.

`run` shall assert immediately before an argv-preserving child launch, record start
and finish, and reassert after completion. It cannot make a multi-process filesystem
transaction: a human takeover may occur while the child runs, so post-run fencing
must be visible and nonzero even if the child exited zero. Agent policy requires an
additional assert before each later write.

`run-global` shall acquire one nonblocking lock per validated operation name, execute
the supplied argv without shell interpolation, record the result, and release the
kernel lock on normal exit, exception, signal termination, or process death. The Git
boundary checker shall reject worker OpenSpec changes, cross-change coordinator
changes, and unacknowledged shared OpenSpec changes. Acceptance is the sixteen
required temporary-repository scenarios plus corrupt-state, traversal, atomic JSON,
argument-boundary, hook, and CI tests.

### Ownership and boundaries

`scripts/ops_coord.py` owns repository discovery, validated identities, file layout,
locking, atomic JSON, epoch allocation, transition history, fencing, and child
execution. `scripts/ops-coord` is a minimal executable facade. It never imports
OpenSpec or project runtime/data modules.

`scripts/check_openspec_coordination.py` owns Git diff selection and branch/path
policy. `scripts/check-openspec-coordination.py` is its executable facade so tests can
exercise typed Python helpers without shell parsing. The checker consumes committed,
staged, or explicit base/head diffs and does not read live ownership records.

`scripts/install-openspec-coordination-hook` installs the tracked pre-commit hook into
the common Git hooks directory without editing arbitrary hook content silently.
`.github/workflows/openspec-coordination.yml` invokes the checker for pull requests.
`AGENTS.md` and `openspec/config.yaml` own behavioral constraints that filesystem
locking cannot enforce, especially worker prohibitions and fenced-agent response.

The authoritative writer for coordination metadata is `scripts/ops-coord`; agents
must not edit the common-dir state directly. OpenSpec remains authoritative for its
own artifacts and commands.

### Data and state invariants

Change IDs, owner IDs, and operation names are bounded safe slugs: ASCII
alphanumeric first, followed only by ASCII alphanumeric, `.`, `_`, or `-`. Empty,
absolute, separator-containing, dot-segment, control-character, option-like, and
overlength values are rejected before path construction.

The coordination root is the resolved absolute value from
`git rev-parse --path-format=absolute --git-common-dir`. It contains `owners/`,
`locks/`, `history/`, and `epoch/`. Every owner transition holds
`locks/change-<id>.lock` with exclusive `flock`. A new epoch is the previous durable
epoch plus one, stored atomically before the matching owner record. If a crash occurs
between those writes, the epoch may have a gap but can never decrease or be reused.
The owner record is the sole current authority.

Ownership JSON includes `change_id`, `owner_id`, `epoch`, `worktree`, `branch`,
`pid`, `claimed_at`, and optional predecessor/takeover fields. Records are encoded to
a same-directory temporary file, flushed, `fsync`ed, atomically replaced, and the
directory is `fsync`ed. Readers take a shared change lock and reject malformed,
missing-required-field, or identity-inconsistent JSON. Status never creates,
repairs, expires, or removes ownership.

Release appends a history event before atomically removing the owner and syncing its
directory. Claim/takeover publish the owner before appending best-effort history; an
audit append failure is treated as an operation failure and reported, but the
already-published authority is never rolled back to an older owner. History files use
exclusive creation with timestamp/epoch/random identity and complete JSON writes.

### Contracts and compatibility

The additive commands are:

```text
scripts/ops-coord claim <change-id> --owner <owner-id>
scripts/ops-coord status <change-id>
scripts/ops-coord assert-owner <change-id> --owner <owner-id> --epoch <epoch>
scripts/ops-coord release <change-id> --owner <owner-id> --epoch <epoch>
scripts/ops-coord takeover <change-id> --owner <new-owner-id> --reason <reason> [--yes]
scripts/ops-coord run <change-id> --owner <owner-id> --epoch <epoch> -- <argv...>
scripts/ops-coord run-global <operation> [--wait <seconds>] -- <argv...>
scripts/check-openspec-coordination.py [--cached|--base <ref> [--head <ref>]]
```

Human-readable output includes complete owner identity and uses nonzero exits for
invalid invocation, unowned/owned conflicts, fencing, corrupt state, lock
contention, and child failure. Exact numeric nonzero codes are implementation detail
except that a child result is preserved when both pre/post assertions pass.

Coordinator branch policy recognizes `change/<change-id>` and permits ordinary
change files only below `openspec/changes/<change-id>/`. Worker policy recognizes
`agent/<change-id>/<task-id>` and forbids every `openspec/**` path. Shared paths
(`openspec/specs/**`, `openspec/config.yaml`, and archive paths) require an explicit
CI acknowledgement environment variable naming the reviewed shared operation; live
owner files are never CI proof.

Existing OpenSpec CLI and artifact schemas are unchanged. Existing branches outside
the recognized worker/coordinator patterns receive shared-path checks but no inferred
per-change ownership, because guessing would violate fail-closed identity semantics.

### Persistent-write safety

The common-dir coordination root is the only persistent writer scope. The per-change
lock and operation-specific global lock are the concurrency controls. The idempotency
identity is the transition tuple `(change_id, epoch, owner_id, action)`; epochs are
never reused even after release.

JSON is fully staged, validated in memory, flushed, synced, and atomically renamed
before readers can observe it. Corrupt predecessor owner or epoch files are preserved
and block mutation; there is no automatic repair. Partial history failure is reported
without reverting current authority. Readers lock and parse the complete current
record, so they observe either the predecessor or successor owner, never half JSON.

No migration, backup of OpenSpec, or trading-data snapshot is needed. Small-sample
verification uses temporary repositories and inspects every owner/epoch/history file.
Rollback reverts the tracked scripts, hook, workflow, tests, docs, and policy while
leaving the ignored common-dir audit root untouched for manual inspection; removing
that state is an explicit human action outside rollback automation.

### Failure and recovery

Git discovery failure, detached HEAD, invalid identity, malformed JSON, missing
required fields, lock open/acquire failure, epoch overflow, fsync/rename failure, and
identity mismatch all fail closed. Detached HEAD cannot satisfy branch binding. The
tool never switches branches, reclaims an owner, deletes a suspicious lock, or treats
an absent PID as stale.

Claim conflict displays the effective owner, epoch, branch, and worktree. A fenced
assert displays both requested local identity and effective identity. An unowned
assert is also fenced because no effective authority exists. A failed release leaves
ownership untouched. An interrupted takeover before owner publication leaves the old
owner authoritative or only advances the epoch counter; after owner publication the
new owner is authoritative even if audit output fails.

The `run` race cannot be eliminated without holding the ownership lock for the whole
external command, which would prevent intentional takeover. Instead it validates
before launch, records command boundaries, permits explicit takeover, then fences on
return. Coordinators must use narrowly scoped wrappers and reassert before each later
write. `run-global` does hold its independent operation lock for the full child
lifetime because those operations are intentionally serialized.

### Performance and capacity

Normal scale is tens of changes and windows. Per-change transitions perform bounded
small-file I/O under one lock; different lock files permit parallel claims. Owner and
epoch JSON are capped at small fixed input sizes when read. IDs and reasons are
bounded, and history is one event file per transition/command boundary with no
background compaction.

Global operations are short-lived by policy. Default acquisition is nonblocking;
`--wait` uses a finite monotonic deadline and bounded sleep, never an unbounded hidden
wait. Capacity tests launch concurrent subprocesses for same-change, different-change,
and global-operation contention and require deterministic winner counts.

### Observability and operations

`status` is a read-only source of current owner, epoch, worktree, branch, PID, and
claim time. Every transition and wrapped command records UTC time, process identity,
argv as an array, and result. Sensitive shell strings are not reconstructed or
evaluated. Errors name the coordination root or affected record where safe and give a
specific next step without automatic remediation.

Operators distinguish `unowned`, `owned`, `FENCED`, corrupt/unreadable state, and
busy operation locks. Documentation covers checking the old worktree, explicit
takeover, recovery of resumed windows, worker prohibitions, and hook installation.
There are no metrics, alerts, or service health endpoints because there is no service.

### Validation strategy

Focused pytest creates bare-independent temporary Git repositories and linked
worktrees, invokes the real executable with subprocess argv arrays, and covers claim,
concurrent claim, independent changes, assertions, takeover, release, branch and
worktree binding, no TTL, traversal rejection, corrupt records, global locks, command
audit, and post-command fencing.

Boundary tests construct committed/staged diffs for worker, coordinator, allowed own
change, shared paths with and without explicit CI acknowledgement, archive paths, and
renames. Static tests verify the tracked hook and CI workflow invoke the checker and
that agent/config rules retain required prohibitions. Completion runs focused pytest,
`python -m compileall scripts tests`, `./trade dev check --show-plan`,
`./trade dev check`, native strict OpenSpec validation, strict design approval, and
`git diff --check`.

### Alternatives and trade-offs

1. **Atomic `mkdir` ownership** gives a simple exclusive create but crash recovery
   leaves stale directories that require unsafe clear semantics. It also does not
   provide a clean locked read/update path for takeover and release.
2. **One repository-global owner lock** is simple but unnecessarily serializes
   unrelated changes and violates the parallel-change goal.
3. **Hold the per-change lock for a coordinator lifetime** makes crash cleanup easy
   but converts ownership into process liveness, prevents persistent manual ownership,
   and cannot fence a paused process after lock loss without another epoch record.
4. **Per-change short `flock` plus durable epoch and atomic records** is selected. It
   separates transient mutual exclusion from persistent authority, allows unrelated
   parallelism, and makes human takeover fence old windows.
5. **A daemon or distributed consensus store** could close more race windows but is
   explicitly out of scope and adds availability, lifecycle, and dependency burden.
6. **Holding ownership lock across `run`** would make takeover impossible during a
   hung command. Pre/post fencing is selected, with documented limits and narrow
   command use.

### Rollout and rollback

First land the script, tests, policies, hook installer, and CI checker together.
Existing active changes are initially unowned; the first coordinator explicitly runs
`claim` and records returned identity. There is no automatic backfill or inferred
owner. Teams install the tracked pre-commit hook explicitly; CI protection applies
independently.

Rollback removes the tracked coordination surfaces and restores previous agent
guidance. The Git common-dir state remains outside the diff so operators can audit it
or explicitly remove it after confirming no coordinator depends on it. Rollback never
edits OpenSpec artifacts, changes an epoch, releases an owner, or deletes user data.
