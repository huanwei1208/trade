## Context

`./trade build linux-clang` failed in vendored Arrow/Parquet when the preset used
Clang 13 with libc++. The local libc++ headers compile `std::bit_width`, but do
not define the `__cpp_lib_bitops` feature-test macro Arrow checks. Arrow then
selected an older Clang branch that calls unavailable `std::log2p1`.

This is a build compatibility problem. It must be solved in owned build
configuration, not by editing vendored Arrow, changing the advertised
`linux-clang` preset, or changing any engine runtime behavior.

## Design Quality Brief

### Requirements and acceptance

The `linux-clang` developer command surface remains unchanged:
`./trade configure linux-clang`, `./trade build linux-clang`, and
`./trade test linux-clang`. Acceptance requires the configure step to create the
vendored Arrow/Parquet targets, apply a scoped compatibility definition only
when the compiler is Clang and the build uses libc++, and compile Arrow through
its existing `std::bit_width` branch instead of the unavailable `std::log2p1`
branch.

The change is accepted only if no files under `engine/vendor/**` are modified,
the preset variables remain compatible, first-party engine targets that include
Arrow headers also compile, and repository quality checks report any remaining
tooling blockers without weakening rules.

### Ownership and boundaries

`engine/cmake/deps.cmake` owns vendored dependency wiring for the engine. The
new helper lives next to the Arrow `add_subdirectory` integration because that
is the first point where Arrow and Parquet CMake targets are available for
target-scoped compile definitions. `engine/CMakeLists.txt` owns the first-party
`trade_deps` interface and links the project-owned compatibility interface only
when the helper creates it.

Vendored Arrow remains the dependency owner for its headers and sources. The
fix intentionally attaches private metadata to generated Arrow/Parquet targets
from owned CMake code and uses an owned interface for first-party consumer
propagation, keeping the repository's vendor boundary intact. The top-level
`trade` facade, Python services, Web surfaces, C++ engine sources, API
contracts, data access, and trading decision code are outside this change.

### Data and state invariants

No trading data, database file, parquet file, model artifact, market snapshot,
or persistent runtime state is read or written by the source change. Generated
CMake and Ninja files under `build/linux-clang` remain local build output and
are not committed.

The compatibility definition is only valid when configure-time compile probes
prove `std::bit_width(std::uint64_t)` is available with the active toolchain key
and libc++ does not already publish `__cpp_lib_bitops >= 201907L`. The probe
cache is invalidated when the compiler path, compiler id, compiler version, C++
standard, or `CMAKE_CXX_FLAGS` change. If the compiler is not Clang, the
standard library is not libc++, the bit-width probe fails, or libc++ already has
the macro, the shim leaves targets unchanged and the build continues to expose
the real toolchain behavior.

### Contracts and compatibility

The public developer contract is the stable Linux Clang preset and command
surface. The preset name, compiler selection, C++ standard, standard-library
flags, linker flags, build artifact layout, and target aliases remain unchanged.

The CMake helper applies `__cpp_lib_bitops=201907L` privately only to Arrow and
Parquet targets produced by the vendored Arrow subdirectory. It fails configure
with a clear message if the active compatibility path requires the shim but no
patchable Arrow/Parquet target is found. A project-owned
`trade_arrow_libcxx_bitops_compat` interface carries the same definition to
first-party consumers that compile against public Arrow headers through
`trade_deps`. Non-Clang, non-libc++, or already-compatible libc++ builds skip
the helper.

### Failure and recovery

If required local LLVM 13 development packages are missing, configure/build can
still fail before or after this shim. The operator recovery is to install the
matching libc++, libc++abi, libunwind, and libomp packages for Clang 13, verify
the cached OpenMP paths, and rerun configure/build.

If the `std::bit_width` probe fails, the helper emits a warning with the active
compiler, compiler version, `CMAKE_CXX_FLAGS`, and the CMake try-compile log
location, then it does not define the feature-test macro. That preserves a clear
compiler/toolchain failure instead of forcing Arrow into a branch that the
standard library cannot support. If Arrow target names change in a future vendor
update and no patchable target is found, configure fails before the long compile
phase with a message naming the Arrow source directory.

### Performance and capacity

The helper runs during CMake configure and walks only the Arrow subdirectory's
generated target tree. It adds two compile-only probes, one target list
traversal, and one optional interface target; there is no runtime code path, no
additional engine binary work, no data scan, and no change to application memory
or latency.

At 10x source size within the Arrow subproject, the traversal remains bounded by
CMake target count during configure. The build remains Ninja-driven and uses the
same target graph after compile definitions are attached.

### Observability and operations

Configure output prints `Arrow/Parquet: applied Clang libc++ bitops
compatibility definition to <n> target(s): ...` when the shim is active, prints
`not needed` when libc++ already exposes `__cpp_lib_bitops`, and prints an
actionable warning when the `std::bit_width` probe fails. Existing compiler and
linker diagnostics remain the operational evidence for missing local packages,
missing OpenMP paths, or a future incompatible Arrow target graph.

No backend metrics, audit rows, dashboards, or runtime logs are added because
this is build-system behavior only.

### Validation strategy

Validation maps directly to the developer contract: run
`./trade configure linux-clang`, `./trade build linux-clang`, and
`./trade test linux-clang`. The build is the focused regression test because
the failure is a compile-time vendor-header branch selection issue. The
configure log must show either a patched target count or a skip reason. The test
command is still required; if CTest has no registered tests for this preset,
that gap is recorded explicitly.

The repository quality gate is `./trade dev check --show-plan` followed by
`./trade dev check`, plus `git diff --check`. Review validation confirms that
only owned CMake/OpenSpec files changed and that `engine/vendor/**` remains
untouched.

### Alternatives and trade-offs

Patching vendored Arrow would be the smallest textual change, but it violates
the repository's vendor boundary and creates fork drift. Switching the
`linux-clang` preset away from libc++ or Clang 13 would change the command's
meaning and hide the compatibility issue rather than fixing it.

A preset-wide compile definition would be simple, but it would affect every
first-party engine target and could mask unrelated feature-test macro behavior.
Putting a public definition directly on vendored Arrow/Parquet targets would
make first-party compilation pass, but it would blur ownership of a reserved
feature-test macro. The selected target-scoped shim plus owned consumer
interface is more explicit: vendored compilation receives private metadata,
first-party propagation is owned by `trade_deps`, and activation is guarded by
compiler, standard-library, macro-presence, and `std::bit_width` probes.

### Rollout and rollback

Rollout is a source-only CMake change. Developers with the matching LLVM 13
packages rerun `./trade configure linux-clang` and `./trade build linux-clang`
normally. No data migration, cache cleanup, or runtime feature flag is involved.

Rollback is a source revert of the CMake helper and governed OpenSpec artifacts,
followed by reconfiguring `build/linux-clang` if local generated files need to
be refreshed. There is no durable state restoration because the change does not
write application data.
