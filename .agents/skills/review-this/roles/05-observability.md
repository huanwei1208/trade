# Judge 5: Observability & Operability

Audit for: CLI usability, logging quality, health/doctor/status commands, web
dashboard usefulness, audit trail / decision traceability, error message
actionability, backup/DR, SRE basics (SLO/alerting/metrics).

## Checklist

- CLI: how many ways can an operator get to "is the system healthy"? If >1,
  that's overlap that should be collapsed. Does `trade <cmd> --help` give
  discoverable paths? Are there dead/deprecated commands without clear shims?
- Logging: consistent format, -v/-q propagation, file logs for daemon mode,
  date in timestamps, module-level loggers used, no stray print() in production
  paths, uvicorn level respects global verbosity, no dead log-setup code.
- Health commands: is there ONE command that gives pass/warn/fail with exit
  code 0/1/2 suitable for cron?
- Recovery actions: when doctor/status finds a problem, does it print a
  copy-pasteable repair command?
- Network error classification: is RemoteDisconnected/timeout/429/5xx mapped to
  self-serve text ("transient, retry in a few minutes" vs "check credentials")?
- Web: /healthz and /readyz for external monitoring? Prometheus /metrics?
  Non-200 status codes for errors? Request-id middleware for tracing?
- Audit trail: can you answer "why did the system recommend X at time T"?
  Is RecommendationTrace.data_fingerprint a real hash of features, or trivial?
  Are tracebacks persisted on job failure or only printed to stderr?
- Backup/DR: tested? Integrity verified (sha256)? Path-traversal safe?
- Metrics: latency counters, error counters, event lag? Webhook alerting fires
  on SLO breach, not just per-job success/failure noise?
- Scheduler overlaps: can a slow gate pile up multiple concurrent runs
  (minute-gate stacking if the previous minute's work isn't done)?
- Stuck-job detection: stale-running policies exist and cover all job classes?

## Operator friction

List the top 5 things a daily operator has to fight with.

## Rate each finding CRIT/HIGH/MED/LOW with file:line.
