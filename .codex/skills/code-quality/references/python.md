# Python rules

## Design and typing

- Keep public/service/domain boundaries typed. Prefer dataclasses or small typed
  records over unstructured dictionaries when the shape is owned and stable.
- Use `Path`, context managers, timezone-aware datetime values, and explicit units.
- Keep pandas/Arrow transformations at adapter/data boundaries; return domain-shaped
  results instead of leaking mutable frames across layers.
- Avoid import-time I/O, DB construction, network calls, and optional heavy imports in
  CLI startup paths.

## Errors and state

- Never use mutable defaults or `except Exception: pass`.
- Catch the narrowest expected exception. Preserve the cause with contextual errors.
- Do not use truthiness when zero/empty is valid and `None` means unavailable.
- Make file/DB writes atomic, idempotent, and testable with temporary roots.

## Tests and commands

- Add focused pytest for public behavior and regression cases.
- Run `./trade dev check` for changed Python files.
- Run `uv run pytest -q tests/<focused>.py`.
- For shared modules, run source syntax/compile validation requested by repository
  policy without writing into real data roots.
- BasedPyright is gradual: fix changed-boundary diagnostics; do not disable it for the
  project to avoid dynamic-code noise.

Ruff owns formatting/import order/lint. Do not add Black, isort, Flake8, or Pylint
configuration that duplicates that ownership.
