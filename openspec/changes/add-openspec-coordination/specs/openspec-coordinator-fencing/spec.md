## ADDED Requirements

### Requirement: One explicit owner is authoritative per change

The coordination layer SHALL maintain at most one current owner record for each
validated OpenSpec change ID. A coordinator SHALL claim a change before modifying its
OpenSpec files. Claim SHALL fail without mutation when a current owner exists, and
different change IDs SHALL remain independently claimable.

#### Scenario: Two coordinators claim the same change
- **WHEN** two processes concurrently claim one unowned change
- **THEN** exactly one claim succeeds and the other reports the complete effective owner identity

#### Scenario: Two coordinators claim different changes
- **WHEN** two processes concurrently claim distinct unowned changes
- **THEN** both claims can succeed without waiting on one repository-wide ownership lock

### Requirement: Monotonic epochs fence superseded coordinators

Every successful claim or explicit takeover SHALL allocate a durable epoch larger
than every epoch previously allocated for that change. Owner validation SHALL compare
change ID, owner ID, epoch, current absolute worktree, and current branch. Any missing
or mismatched authority SHALL emit `COORDINATOR FENCED`, show requested and effective
identity, return nonzero, and perform no automatic claim, takeover, branch switch,
release, or lock deletion.

#### Scenario: Old owner resumes after takeover
- **WHEN** the previous owner asserts its old owner ID and epoch after a confirmed takeover
- **THEN** validation reports `COORDINATOR FENCED` and the old process cannot become authoritative

#### Scenario: Owner changes branch or worktree
- **WHEN** a matching owner and epoch assert from a different branch or worktree
- **THEN** validation reports `COORDINATOR FENCED` without repairing the mismatch

### Requirement: Ownership transitions are atomic and fail closed

The coordination layer SHALL store state below the resolved absolute Git common
directory in `openspec-coordination/`, SHALL serialize transitions with per-change
file locks, and SHALL publish complete JSON using same-directory temporary files,
flush, sync, and atomic replace. It SHALL validate path identities before path
construction and reject malformed, inconsistent, oversized, or corrupt predecessor
state without automatic cleanup.

#### Scenario: A path traversal identity is supplied
- **WHEN** a caller supplies a change, owner, or operation identity containing a path separator, dot segment, option prefix, control character, or unsupported length
- **THEN** the command fails before reading or writing outside its owned coordination path

#### Scenario: An owner record is malformed
- **WHEN** a transition or assertion encounters incomplete or invalid owner JSON
- **THEN** it preserves the record, reports an ambiguous coordination state, and stops all mutation

### Requirement: Release and takeover require explicit authority

Only the current owner with the exact current epoch, worktree, and branch SHALL
release a change. Takeover SHALL require a nonempty reason and interactive user
confirmation unless `--yes` is explicitly supplied. PID absence, elapsed time, record
age, or lock appearance SHALL NOT trigger takeover, expiry, release, or cleanup.

#### Scenario: Another coordinator attempts ordinary release
- **WHEN** a caller supplies a non-current owner ID or epoch to release
- **THEN** release fails fenced and leaves the owner record unchanged

#### Scenario: Non-interactive takeover omits confirmation
- **WHEN** stdin is not interactive and takeover does not include `--yes`
- **THEN** takeover fails without changing epoch or owner

### Requirement: Controlled commands preserve arguments and revalidate fencing

The owned-change `run` wrapper SHALL validate authority before launching the supplied
argv without shell string interpolation, audit command start and finish, and validate
authority again after the child exits. The named `run-global` wrapper SHALL hold one
short-lived exclusive operation lock for the complete child lifetime, fail
immediately by default when busy, and support only an explicit finite wait.

#### Scenario: Takeover occurs while an owned command runs
- **WHEN** a child command completes after another user-confirmed owner takeover
- **THEN** post-command validation reports fencing and the wrapper returns nonzero even if the child succeeded

#### Scenario: Two archive operations overlap
- **WHEN** one `run-global archive` child still holds the archive operation lock
- **THEN** a second default archive wrapper fails busy and does not execute its child

### Requirement: Git boundaries are enforced without live CI ownership

The repository checker SHALL reject every `openspec/**` staged or PR-diff path on
`agent/<change-id>/<task-id>` branches. On `change/<change-id>` branches it SHALL
allow ordinary change files only under `openspec/changes/<change-id>/**` and reject
other change directories. Shared specs, configuration, and archive paths SHALL
require an explicit reviewed shared-operation acknowledgement in CI; live workstation
owner files SHALL NOT be sufficient CI evidence.

#### Scenario: Worker stages an OpenSpec file
- **WHEN** a worker branch stages any added, modified, deleted, or renamed `openspec/**` path
- **THEN** the checker fails and identifies the forbidden path

#### Scenario: Coordinator edits another change
- **WHEN** `change/change-a` modifies `openspec/changes/change-b/**`
- **THEN** the checker fails even if local ownership metadata claims change-a

### Requirement: Agent policy preserves coordinator and worker separation

Repository agent instructions SHALL require coordinators to assert before every
OpenSpec write and after long pauses or external calls, restrict them to their owned
change, forbid workers from all OpenSpec mutation and shared OpenSpec operations, and
forbid agents from direct state edits, takeover, force clear, or owner deletion.
Fenced agents SHALL stop writes and Git publication actions, preserve and summarize
local diffs, avoid branch switching or reclaim, and report their fenced state.

#### Scenario: A worker receives an OpenSpec subtask
- **WHEN** a coordinator delegates implementation work to a worker
- **THEN** the worker may read the existing change but cannot edit OpenSpec, create a child change, propose, sync, or archive

#### Scenario: A coordinator fails ownership validation
- **WHEN** `assert-owner` returns fenced before a planned write
- **THEN** the agent stops writes, add, commit, push, branch switching, and automatic claim and reports its uncommitted diff summary
