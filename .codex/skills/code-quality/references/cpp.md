# C and C++ rules

- Keep engine changes inside `engine/`; preserve header/source and namespace ownership.
- Prefer RAII and value semantics. Make ownership explicit with references or smart
  pointers; avoid raw owning pointers and manual cleanup paths.
- Check integer/size conversions, nullability, iterator lifetime, string/view/span
  lifetime, and error propagation at I/O and FFI boundaries.
- Avoid hidden global initialization, blocking work under shared locks, and unchecked
  concurrent mutation.
- Keep public engine interfaces backward-compatible or document migration.
- Never format or modify `engine/vendor/**` or generated amalgamations.

Run clang-format check for owned changed files, then the relevant configured build and
ctest path. Normally:

```bash
./trade configure linux-clang
./trade build linux-clang
./trade test linux-clang
```

Add focused ctest coverage for success, invalid inputs, boundary sizes, resource
cleanup, and relevant concurrency/error paths.
