## ADDED Requirements

### Requirement: Linux Clang builds vendored Arrow with libc++ bit operations

The `linux-clang` build SHALL compile vendored Arrow/Parquet with Clang 13 and
libc++ even when libc++ provides `std::bit_width` but omits the
`__cpp_lib_bitops` feature-test macro.

#### Scenario: libc++ bit operations are available without the macro

- **WHEN** `./trade configure linux-clang` creates vendored Arrow/Parquet targets
  under Clang plus libc++
- **THEN** owned CMake configuration applies a scoped compatibility definition to
  the relevant Arrow/Parquet compile targets
- **AND** Arrow/Parquet compile their existing `std::bit_width` branch instead of
  selecting unavailable `std::log2p1`
- **AND** no files under `engine/vendor/**` are modified

#### Scenario: Build commands remain stable

- **WHEN** a developer runs `./trade build linux-clang`
- **THEN** the command surface, preset name, compiler selection, C++ standard,
  standard-library selection, and generated artifact layout remain compatible
