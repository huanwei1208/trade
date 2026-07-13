# Judge 3: Architecture & Design

Audit for: module boundaries, abstraction quality, meta-driven extensibility,
separation of concerns, plugin/registry patterns, cohesion of CLI domains,
leaky abstractions, hardcoded vs config-driven, god-modules, duplication.

## Checklist

- Does the meta-registry (asset_registry, pipeline_dag, model_registry) achieve
  its stated goal, or are there hardcoded if/elif branches that require code
  changes to add a new asset/class/venue?
- Module layout: do files have single responsibilities? Any >1000-line god
  files? Are there two parallel implementations of the same concept (e.g., two
  event stores, two settings systems, two health commands)?
- Abstraction boundaries: does the AssetIngestor / DataSource Protocol cover
  what it should, or do implementations reach around it?
- CLI cohesion: each top-level domain should map to one operator intent
  (run / observe / configure / research / fix). Overlapping commands (5 ways to
  see health) are a design failure, not a feature.
- Deprecation path: when concepts are renamed (cross_asset → crypto/fx/...) are
  shims clean with DeprecationWarning and a clear removal timeline?
- Dependency direction: do lower-level modules (db, data) avoid importing from
  higher-level modules (cli, web)?
- Web backend: route handlers should be thin; business logic should live in
  service modules. Handlers with 200+ lines of raw SQL are a red flag.
- Config vs code: are asset lists, QPS budgets, schedule times, thresholds in
  config YAML / DB, or hardcoded?

## Propose a CLI domain map

List current top-level commands with cohesion rating 1-10 and verdict
(KEEP / MERGE into X / SPLIT / REMOVE).

## Rate each finding CRIT/HIGH/MED/LOW with file:line.
