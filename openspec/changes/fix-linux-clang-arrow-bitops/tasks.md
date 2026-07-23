# Implementation Tasks

## 1. Diagnose and specify

- [x] 1.1 Reproduce `./trade build linux-clang` after installing missing local
  Clang/libc++/OpenMP packages and capture the remaining Arrow compile failure.
- [x] 1.2 Verify the local libc++ toolchain compiles `std::bit_width` but does
  not define `__cpp_lib_bitops`, explaining Arrow's bad `std::log2p1` branch.
- [x] 1.3 Record the scoped OpenSpec proposal, alternatives, compatibility
  boundary, validation, and rollback plan before editing build config.

## 2. Build configuration

- [x] 2.1 Add and validate a target-scoped owned CMake compatibility shim after vendored Arrow target creation. `[validates:linux-clang.arrow-bitops] [validation:test]`
- [x] 2.2 Review evidence that the shim is restricted to Clang plus libc++ and does not edit `engine/vendor/**`. `[validates:linux-clang.arrow-bitops] [validation:review]`

## 3. Validation and delivery

- [x] 3.1 Validate with `./trade configure linux-clang` and `./trade build linux-clang`. `[validates:linux-clang.arrow-bitops] [validation:test]`
- [x] 3.2 Run `./trade test linux-clang` if the build completes. `[validates:linux-clang.arrow-bitops] [validation:test]`
- [x] 3.3 Run `./trade dev check --show-plan`, `./trade dev check`, and `git diff --check`; record any tooling blocker. `[validates:linux-clang.arrow-bitops] [validation:test]`
- [ ] 3.4 Review final diff/status evidence, stage only intentional files, commit, push, and create a PR against `master`. `[validates:linux-clang.arrow-bitops] [validation:review]`

## Validation Evidence

- `./trade configure linux-clang`: PASS after the review-driven CMake update.
  Evidence: `TRADE_CXX_HAS_STD_BIT_WIDTH` succeeded,
  `TRADE_CXX_HAS_LIBCXX_BITOPS_MACRO` failed as expected for local libc++ 13,
  and the shim reported 12 patched Arrow/Parquet targets:
  `arrow_array`, `arrow_io`, `arrow_memory_pool`, `arrow_vendored`,
  `arrow_util`, `arrow_compute_core`, `arrow_filesystem`, `arrow_ipc`,
  `arrow_objlib`, `arrow_shared`, `parquet_objlib`, `parquet_shared`.
- `./trade build linux-clang`: PASS after fresh configure; Ninja reported
  `no work to do`, confirming the generated graph was up to date.
- `./trade test linux-clang`: PASS exit status; CTest reported
  `No tests were found!!!` for this preset.
- `./trade dev check --show-plan`: PASS; planned strict design, TOML parse,
  suppression audit, and text hygiene across the nine changed files.
- `./trade dev check`: PASS; strict design, config parse, suppression audit, and
  text hygiene all passed.
- `git diff --check`: PASS after review-driven edits.
- Six-role review consensus: resolved before merge by adding stale-probe cache
  invalidation, macro-presence probing, patched-target counting, clearer
  diagnostics, private vendored compile definitions, and a project-owned
  compatibility interface for first-party consumers.
- Accepted follow-up: split broad `trade_deps` by domain or remove Arrow types
  from public storage headers before attempting narrower first-party macro
  propagation. Current public storage headers expose `arrow::Table` and
  `arrow::Schema`, so a narrower propagation boundary would be a separate public
  API/header refactor.
