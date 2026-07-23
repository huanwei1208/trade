## Why

`./trade build linux-clang` fails while compiling the vendored Arrow/Parquet
sources with Clang 13 and libc++. The failing Arrow code tests for
`__cpp_lib_bitops`; this libc++ build provides the C++20 `<bit>` API used by
Arrow's fallback branch, but it does not define the feature-test macro. Arrow
therefore selects the Clang-specific `std::log2p1` branch, which is absent in
the installed libc++ headers.

The build failure is a toolchain compatibility issue, not an engine behavior,
data, API, or trading-decision change.

## What Changes

- Add a project-owned Linux Clang compatibility shim around the vendored
  Arrow/Parquet targets after `add_subdirectory(vendor/arrow/cpp ...)`.
- For Clang plus libc++ builds, define `__cpp_lib_bitops=201907L` only when
  `std::bit_width` compiles and libc++ does not already publish the feature-test
  macro.
- Apply the definition privately to relevant Arrow/Parquet compile targets and
  expose a project-owned compatibility interface for first-party consumers that
  compile Arrow headers.
- Keep `engine/vendor/**` unchanged and keep the `linux-clang` preset's compiler,
  standard library, link flags, and public build command unchanged.
- Document the local probe evidence in the implementation comments/tasks:
  `std::bit_width(uint64_t{7})` compiles, while the feature-test macro is absent.

## Non-Goals

- No vendored Arrow source patch.
- No compiler, standard library, CMake generator, or preset rename.
- No C++ engine source, Python, Web, CLI contract, DB, parquet, market-data, or
  runtime configuration behavior change.
- No test fixture or generated build output committed.

## Alternatives and Tradeoffs

**Patch vendored Arrow:** rejected. It is the smallest textual change but violates
the repository's vendor boundary and would create local fork drift.

**Switch `linux-clang` away from libc++ or Clang 13:** rejected. That would change
the preset's advertised toolchain and could mask other compatibility issues.

**Preset-wide `CMAKE_CXX_FLAGS` macro:** acceptable fallback, but broader than
needed because it affects first-party engine targets too.

**Target-scoped CMake shim plus project-owned consumer interface:** selected.
Arrow's generated targets are available after `add_subdirectory`, and the
compatibility definition can be attached privately to Arrow/Parquet targets that
compile the affected vendored code. A separate owned interface makes the
first-party propagation explicit without mutating the vendored target public
interface.

## Affected Contracts

- **Build contract:** `./trade configure linux-clang`, `./trade build
  linux-clang`, and `./trade test linux-clang` remain the user-facing commands.
- **Source boundary:** only owned CMake/spec files are changed; vendored Arrow
  remains pinned at the submodule revision.
- **Runtime contracts:** unchanged.

## Data Safety

This change touches only owned build configuration and OpenSpec source. Real
trading data, DB files, parquet files, models, and local runtime assets are
outside the touched surface. Build trees remain generated local artifacts and
are not committed.

## Rollout and Rollback

Rollout is source-only through the existing build preset. Rollback is a source
revert of the CMake shim and this proposal, followed by a clean reconfigure of
`build/linux-clang` if needed. No durable data migration or cleanup is required.

## Validation

- Re-run `./trade configure linux-clang`.
- Re-run `./trade build linux-clang`.
- Run `./trade test linux-clang` if the build completes.
- Run `./trade dev check --show-plan`, `./trade dev check`, and
  `git diff --check`, reporting any baseline/tooling blocker without weakening
  repository rules.
