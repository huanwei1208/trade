# Java and Maven rules

- Scope Java work to the owning Maven module, currently
  `engine/tradedb-driver/`; do not route JDBC behavior through unrelated engine code.
- Close JDBC, stream, and native resources deterministically with try-with-resources.
- Preserve checked causes and SQL state/vendor codes where callers rely on them.
- Make nullability, thread safety, connection ownership, and native-library loading
  explicit. Avoid mutable static state and hidden network/filesystem work at class
  initialization.
- Keep driver/API compatibility and add JUnit coverage for public behavior, invalid
  URLs/arguments, missing native dependencies, and cleanup.
- Maven checks run offline by default. Prime pinned plugins/dependencies only through
  an explicit setup step; a quality check must not download them.

Run the module formatter check and focused tests through the repository quality gate
or the pinned Maven commands in `engine/tradedb-driver/pom.xml`.
