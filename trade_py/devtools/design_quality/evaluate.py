"""Evaluate governed OpenSpec evidence against immutable policy profiles."""

from __future__ import annotations

import hashlib
import math
import os
import re
import selectors
import signal
import subprocess
import time
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.models import (
    ChangeSnapshot,
    DesignReport,
    EvidenceSchema,
    ExceptionRecord,
    Finding,
    Policy,
    Profile,
    Severity,
)
from trade_py.devtools.design_quality.policy import load_policy
from trade_py.devtools.design_quality.report_binding import (
    selected_profile_names,
    signaled_impacts,
)
from trade_py.devtools.design_quality.snapshot import (
    artifact_payload_digest,
    load_snapshots,
    verify_snapshot,
)
from trade_py.devtools.design_quality.v1_contract import (
    exception_state,
)
from trade_py.devtools.design_quality.v1_contract import (
    is_substantive_reason as _valid_reason,
)
from trade_py.devtools.quality.toml_compat import tomllib

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
_TASK_LINE_RE = re.compile(r"^- \[[ xX]\]\s+(\d+\.\d+)\b\s*(.+)$", re.MULTILINE)
_REQUIREMENT_RE = re.compile(r"^### Requirement: (.+?)\s*$", re.MULTILINE)
_SCENARIO_RE = re.compile(r"^#### Scenario: .+?\s*$", re.MULTILINE)
_SCENARIO_WHEN_RE = re.compile(r"^- \*\*WHEN\*\* .+", re.MULTILINE)
_SCENARIO_THEN_RE = re.compile(r"^- \*\*THEN\*\* .+", re.MULTILINE)
_CATCH_ALL_RE = re.compile(r"(^|/)(common|misc|utils?|helpers?)(\.py|/|$)", re.IGNORECASE)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_REVIEW_ID_RE = re.compile(r"[A-Z][A-Z0-9_-]*-\d+")
_SPEC_PATH_RE = re.compile(r"specs/[^/]+/spec\.md")
_VALIDATION_TASK_RE = re.compile(r"(?i)\b(?:test|pytest|validat|check|smoke)\w*\b")
_REVIEW_TASK_RE = re.compile(
    r"(?i)(?=.*\breview\w*\b)(?=.*\b(?:evidence|finding|consensus|P[0-2])\w*\b)"
)
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{2,127}")
_INVALID_IDENTIFIER_PARTS = frozenset(
    {"anonymous", "missing", "none", "null", "tbd", "todo", "unknown", "unset"}
)
_NEGATED_EVIDENCE_RE = re.compile(
    r"^\s*(?:no\b|none\b|not applicable\b|unsupported\b|missing\b|without\b)",
    re.IGNORECASE,
)
_NEGATION_ALLOWED_FIELDS = {"migration", "rollback", "unavailable_fallback", "no_numeric_fallback"}


def _parse_toml(snapshot: ChangeSnapshot, path: str) -> dict[str, Any] | None:
    text = snapshot.text(path)
    if text is None:
        return None
    try:
        payload = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise DesignQualityError(f"Invalid {path} in {snapshot.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DesignQualityError(f"Invalid {path} in {snapshot.name}: expected a table")
    return payload


def _sections(design: str) -> dict[str, str]:
    brief = re.search(
        r"^## Design Quality Brief\s*$([\s\S]*?)(?=^##\s|\Z)",
        design,
        flags=re.MULTILINE,
    )
    if brief is None:
        return {}
    content = brief.group(1)
    matches = list(_HEADING_RE.finditer(content))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        if match.group(1) != "###":
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        result[match.group(2).strip()] = content[match.end() : end].strip()
    return result


class _Findings:
    def __init__(self, policy: Policy) -> None:
        self._policy = policy
        self.items: list[Finding] = []

    def add(self, rule_id: str, path: str, message: str) -> None:
        rule = self._policy.rule(rule_id)
        self.items.append(
            Finding(
                rule_id=rule.rule_id,
                severity=rule.severity,
                path=path,
                message=message,
                remediation=rule.remediation,
            )
        )


def _marker(
    snapshot: ChangeSnapshot,
    policy: Policy,
    findings: _Findings,
) -> (
    tuple[
        dict[str, bool],
        dict[str, dict[str, Any]],
        tuple[dict[str, Any], ...],
        tuple[dict[str, Any], ...],
    ]
    | None
):
    try:
        raw = _parse_toml(snapshot, "design-quality.toml")
    except DesignQualityError as exc:
        findings.add(
            "core.governance.invalid",
            "design-quality.toml",
            str(exc),
        )
        return {}, {}, (), ()
    if raw is None:
        return None
    if raw.get("schema_version") != 1 or raw.get("policy_version") != policy.policy_version:
        findings.add(
            "core.governance.invalid",
            "design-quality.toml",
            "Marker schema_version or policy_version is unsupported.",
        )

    impact_rows = raw.get("impacts")
    impacts: dict[str, bool] = {}
    if not isinstance(impact_rows, list):
        findings.add(
            "core.impact.incomplete",
            "design-quality.toml",
            "impacts must be an array of tables.",
        )
    else:
        for index, row in enumerate(impact_rows, 1):
            if not isinstance(row, dict):
                findings.add(
                    "core.impact.incomplete",
                    "design-quality.toml",
                    f"Impact entry {index} must be a table.",
                )
                continue
            impact_id = row.get("id")
            applies = row.get("applies")
            if (
                not isinstance(impact_id, str)
                or impact_id not in policy.required_impacts
                or not isinstance(applies, bool)
                or not _valid_reason(row.get("reason"))
                or impact_id in impacts
            ):
                findings.add(
                    "core.impact.incomplete",
                    "design-quality.toml",
                    f"Impact entry {index} has an unknown/duplicate id, non-boolean applies, or weak reason.",
                )
                continue
            impacts[impact_id] = applies
    missing_impacts = sorted(set(policy.required_impacts) - impacts.keys())
    if missing_impacts:
        findings.add(
            "core.impact.incomplete",
            "design-quality.toml",
            f"Missing impact declarations: {', '.join(missing_impacts)}.",
        )

    obligations = raw.get("obligations", [])
    if not isinstance(obligations, list):
        findings.add(
            "core.obligation.invalid",
            "design-quality.toml",
            "obligations must be an array of tables.",
        )
        obligations = []
    exceptions = raw.get("exceptions", [])
    if not isinstance(exceptions, list):
        findings.add(
            "core.exception.invalid",
            "design-quality.toml",
            "exceptions must be an array of tables.",
        )
        exceptions = []
    raw_evidence = raw.get("evidence", {})
    evidence: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_evidence, dict):
        findings.add(
            "core.governance.invalid",
            "design-quality.toml",
            "evidence must be a table of profile tables.",
        )
    else:
        for name, value in raw_evidence.items():
            if not isinstance(name, str) or not isinstance(value, dict):
                findings.add(
                    "core.governance.invalid",
                    "design-quality.toml",
                    "Every evidence profile must be a named table.",
                )
                continue
            evidence[name] = value
    return (
        impacts,
        evidence,
        tuple(item for item in obligations if isinstance(item, dict)),
        tuple(item for item in exceptions if isinstance(item, dict)),
    )


def _check_brief(
    snapshot: ChangeSnapshot,
    policy: Policy,
    profiles: tuple[Profile, ...],
    findings: _Findings,
) -> dict[str, str]:
    design = snapshot.text("design.md")
    if design is None:
        findings.add("core.brief.missing", "design.md", "The governed change has no design.md.")
        return {}
    sections = _sections(design)
    if not sections:
        findings.add("core.brief.missing", "design.md", "The design has no Design Quality Brief.")
        return {}
    required = set(policy.required_sections)
    for profile in profiles:
        required.update(profile.required_sections)
    placeholders = tuple(item.lower() for item in policy.placeholders)
    for name in sorted(required):
        body = sections.get(name, "")
        if len(body) < policy.minimum_section_characters or any(
            token in body.lower() for token in placeholders
        ):
            findings.add(
                "core.brief.section",
                "design.md",
                f"Brief section {name!r} is missing, too short, or contains a placeholder.",
            )
    return sections


def _check_required_artifacts(
    snapshot: ChangeSnapshot, policy: Policy, findings: _Findings
) -> None:
    available = {artifact.path for artifact in snapshot.artifacts}
    missing = sorted(set(policy.required_root_files) - available)
    spec_count = sum(path.startswith("specs/") and path.endswith("/spec.md") for path in available)
    if missing or spec_count < policy.minimum_spec_files:
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if spec_count < policy.minimum_spec_files:
            details.append(
                f"specs={spec_count}/{policy.minimum_spec_files} with at least one scenario"
            )
        findings.add(
            "core.artifact.missing",
            snapshot.name,
            f"Governed artifact set is incomplete: {'; '.join(details)}.",
        )


def _check_profiles(
    profiles: tuple[Profile, ...],
    evidence: dict[str, dict[str, Any]],
    findings: _Findings,
    *,
    policy_profiles: tuple[Profile, ...],
) -> None:
    known_profiles = {profile.name: profile for profile in policy_profiles}
    for name, values in evidence.items():
        known = known_profiles.get(name)
        if known is None:
            findings.add(
                "core.governance.invalid",
                "design-quality.toml",
                f"Unknown evidence profile: {name}.",
            )
            continue
        unknown_fields = sorted(set(values) - set(known.required_evidence))
        if unknown_fields:
            findings.add(
                "core.governance.invalid",
                "design-quality.toml",
                f"Profile {name} has unknown evidence fields: {', '.join(unknown_fields)}.",
            )
    for profile in profiles:
        if profile.finding_rule is None or not profile.required_evidence:
            continue
        values = evidence.get(profile.name, {})
        invalid: list[str] = []
        for key in profile.required_evidence:
            value = values.get(key)
            schema = profile.evidence_schema.get(key, EvidenceSchema(kind="text"))
            if _evidence_error(value, schema, key):
                invalid.append(key)
        if invalid:
            findings.add(
                profile.finding_rule,
                "design-quality.toml",
                f"Profile {profile.name} lacks valid typed evidence fields: {', '.join(invalid)}.",
            )
        if profile.name == "external_event":
            source_identity = values.get("source_identity")
            provenance = values.get("provenance")
            if (
                isinstance(source_identity, dict)
                and isinstance(provenance, dict)
                and source_identity.get("source_id") != provenance.get("source_id")
            ):
                findings.add(
                    profile.finding_rule,
                    "design-quality.toml",
                    "Profile external_event provenance source_id does not match source identity.",
                )


def _evidence_error(value: Any, schema: EvidenceSchema, key: str) -> str | None:
    if schema.kind == "text":
        if not isinstance(value, str) or len(value.strip()) < schema.min_length:
            return "text is missing or too short"
        if any(token.lower() in value.lower() for token in ("TBD", "TODO", "FIXME")):
            return "text contains a placeholder"
        if key not in _NEGATION_ALLOWED_FIELDS and _NEGATED_EVIDENCE_RE.search(value):
            return "text starts with a negated evidence claim"
        return None
    if schema.kind == "identifier":
        if not isinstance(value, str) or len(value.strip()) < schema.min_length:
            return "identifier is missing or too short"
        candidate = value.strip()
        if not _IDENTIFIER_RE.fullmatch(candidate):
            return "identifier contains unsupported characters"
        parts = {part for part in re.split(r"[._:/@-]+", candidate.lower()) if part}
        if parts & _INVALID_IDENTIFIER_PARTS:
            return "identifier contains an unknown or placeholder segment"
        return None
    if schema.kind == "boolean":
        if not isinstance(value, bool) or (schema.equals is not None and value != schema.equals):
            return "boolean does not match the required value"
        return None
    if schema.kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return "value is not an integer"
        numeric: int | float | None = value
    elif schema.kind == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return "value is not numeric"
        numeric = value
    else:
        numeric = None
    if numeric is not None:
        if isinstance(numeric, float) and not math.isfinite(numeric):
            return "value is not finite"
        if schema.minimum is not None and numeric < schema.minimum:
            return "value is below the policy minimum"
        if schema.maximum is not None and numeric > schema.maximum:
            return "value exceeds the policy maximum"
        if schema.equals is not None and numeric != schema.equals:
            return "value does not match the required value"
        return None
    if schema.kind == "enum":
        return None if isinstance(value, str) and value in schema.values else "unknown enum value"
    if schema.kind == "string_set":
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) for item in value)
            or len(value) != len(set(value))
        ):
            return "value is not a unique non-empty string set"
        selected = set(value)
        if not set(schema.required_values) <= selected or not selected <= set(schema.values):
            return "string set is incomplete or contains unknown values"
        return None
    if schema.kind == "table":
        if not isinstance(value, dict):
            return "value is not a table"
        if not schema.allow_extra and set(value) - set(schema.fields):
            return "table contains unknown fields"
        for field_name, field_schema in schema.fields.items():
            if _evidence_error(value.get(field_name), field_schema, field_name):
                return f"table field {field_name} is invalid"
        return None
    return "unsupported evidence schema"


def _check_impact_consistency(
    snapshot: ChangeSnapshot,
    policy: Policy,
    impacts: dict[str, bool],
    findings: _Findings,
) -> set[str]:
    signaled = signaled_impacts(snapshot, policy, impacts)
    for impact in sorted(signaled):
        findings.add(
            "core.impact.contradiction",
            "design-quality.toml",
            f"Impact {impact!r} is false but governed artifacts contain an applicability signal.",
        )
    return signaled


def _spec_index(snapshot: ChangeSnapshot, findings: _Findings) -> set[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    scenario_references: set[tuple[str, str]] = set()
    for artifact in snapshot.artifacts:
        parts = artifact.path.split("/")
        if len(parts) != 3 or parts[0] != "specs" or parts[2] != "spec.md":
            continue
        matches = list(_REQUIREMENT_RE.finditer(artifact.content))
        for index, match in enumerate(matches):
            reference = (parts[1], match.group(1).strip())
            references.append(reference)
            end = matches[index + 1].start() if index + 1 < len(matches) else len(artifact.content)
            requirement_block = artifact.content[match.end() : end]
            if (
                _SCENARIO_RE.search(requirement_block)
                and _SCENARIO_WHEN_RE.search(requirement_block)
                and _SCENARIO_THEN_RE.search(requirement_block)
            ):
                scenario_references.add(reference)
    duplicates = sorted(item for item, count in Counter(references).items() if count > 1)
    if duplicates:
        findings.add(
            "core.obligation.reference",
            "specs",
            "Duplicate capability requirement identifiers are ambiguous: "
            + ", ".join(f"{capability}:{requirement}" for capability, requirement in duplicates),
        )
    return scenario_references


def _check_obligations(
    snapshot: ChangeSnapshot, obligations: tuple[dict[str, Any], ...], findings: _Findings
) -> None:
    if not obligations:
        findings.add(
            "core.obligation.invalid",
            "design-quality.toml",
            "At least one owned design obligation is required.",
        )
        return
    spec_requirements = _spec_index(snapshot, findings)
    task_matches = _TASK_LINE_RE.findall(snapshot.text("tasks.md") or "")
    duplicate_task_ids = sorted(
        task_id
        for task_id, count in Counter(task_id for task_id, _ in task_matches).items()
        if count > 1
    )
    if duplicate_task_ids:
        findings.add(
            "core.obligation.reference",
            "tasks.md",
            "Duplicate task identifiers are ambiguous: " + ", ".join(duplicate_task_ids),
        )
    task_rows = dict(task_matches)
    task_ids = set(task_rows)
    seen: set[str] = set()
    required_lists = (
        "paths",
        "contracts",
        "failure_states",
        "spec_requirements",
        "validation_tasks",
    )
    for index, row in enumerate(obligations, 1):
        obligation_id = row.get("id")
        owner = row.get("owner")
        valid_lists = all(
            isinstance(row.get(key), list)
            and bool(row[key])
            and all(isinstance(item, str) and item for item in row[key])
            for key in required_lists
        )
        if (
            not isinstance(obligation_id, str)
            or not obligation_id
            or obligation_id in seen
            or not isinstance(owner, str)
            or not owner
            or not valid_lists
        ):
            findings.add(
                "core.obligation.invalid",
                "design-quality.toml",
                f"Obligation entry {index} has missing fields or a duplicate id.",
            )
            continue
        seen.add(obligation_id)
        missing_specs = []
        for reference in row["spec_requirements"]:
            capability, separator, requirement = reference.partition(":")
            if not separator or (capability, requirement) not in spec_requirements:
                missing_specs.append(reference)
        missing_tasks = sorted(set(row["validation_tasks"]) - task_ids)
        non_validation_tasks = sorted(
            task_id
            for task_id in set(row["validation_tasks"]) & task_ids
            if f"[validates:{obligation_id}]" not in task_rows[task_id]
            or not (
                (
                    "[validation:test]" in task_rows[task_id]
                    and _VALIDATION_TASK_RE.search(task_rows[task_id])
                )
                or (
                    "[validation:review]" in task_rows[task_id]
                    and _REVIEW_TASK_RE.search(task_rows[task_id])
                )
            )
        )
        if missing_specs or missing_tasks or non_validation_tasks:
            details = []
            if missing_specs:
                details.append(f"specs={','.join(missing_specs)}")
            if missing_tasks:
                details.append(f"tasks={','.join(missing_tasks)}")
            if non_validation_tasks:
                details.append(f"non_validation_tasks={','.join(non_validation_tasks)}")
            findings.add(
                "core.obligation.reference",
                "design-quality.toml",
                f"Obligation {obligation_id} has unresolved references: {'; '.join(details)}.",
            )
        if any(_CATCH_ALL_RE.search(path) for path in row["paths"]):
            findings.add(
                "structure.catch_all",
                "design-quality.toml",
                f"Obligation {obligation_id} assigns ownership to a catch-all path.",
            )


def _check_review(
    snapshot: ChangeSnapshot,
    policy: Policy,
    effective_date: date,
    findings: _Findings,
) -> dict[str, str]:
    try:
        review = _parse_toml(snapshot, "design-review.toml")
    except DesignQualityError as exc:
        findings.add(
            "core.review.incomplete",
            "design-review.toml",
            str(exc),
        )
        return {}
    if review is None:
        findings.add(
            "core.review.missing",
            "design-review.toml",
            "Strict approval requires design-review.toml.",
        )
        return {}
    if review.get("schema_version") != 1 or review.get("policy_version") != policy.policy_version:
        findings.add(
            "core.review.incomplete",
            "design-review.toml",
            "Review schema or policy version is unsupported.",
        )
    if review.get("policy_digest") != policy.digest:
        findings.add(
            "core.review.stale",
            "design-review.toml",
            "Review policy digest does not match the active immutable policy.",
        )
    if review.get("artifact_digest_algorithm") != "sha256-path-content-v1":
        findings.add(
            "core.review.incomplete",
            "design-review.toml",
            "Review artifact digest algorithm is missing or unsupported.",
        )
    if review.get("artifact_digest") != snapshot.artifact_digest:
        findings.add(
            "core.review.stale",
            "design-review.toml",
            "Review artifact digest does not match the current design snapshot.",
        )
    if review.get("status") != "approved":
        findings.add(
            "core.review.incomplete",
            "design-review.toml",
            "Review final status is not approved.",
        )
    reviewed_at = review.get("reviewed_at")
    try:
        reviewed_at_date = (
            reviewed_at
            if isinstance(reviewed_at, date)
            else date.fromisoformat(reviewed_at)
            if isinstance(reviewed_at, str)
            else None
        )
    except ValueError:
        reviewed_at_date = None
    reviewed_commit = review.get("reviewed_commit")
    reviewed_commit_status = "invalid"
    if (
        reviewed_at_date != effective_date
        or not isinstance(reviewed_commit, str)
        or not _COMMIT_RE.fullmatch(reviewed_commit)
    ):
        findings.add(
            "core.review.stale",
            "design-review.toml",
            "Review must attest the current strict date and a full commit SHA.",
        )
    else:
        reviewed_digest, reviewed_commit_status = _reviewed_tree_digest(
            snapshot, policy, reviewed_commit
        )
        if reviewed_digest is not None and reviewed_digest != snapshot.artifact_digest:
            findings.add(
                "core.review.stale",
                "design-review.toml",
                "Reviewed commit does not contain the attested design artifact generation.",
            )
        elif reviewed_commit_status not in {"verified", "missing", "not_git"}:
            findings.add(
                "core.review.stale",
                "design-review.toml",
                "Reviewed commit is reachable but cannot verify the attested policy and artifacts.",
            )
    bootstrap = review.get("bootstrap", False)
    if not isinstance(bootstrap, bool) or (
        bootstrap and snapshot.name not in policy.bootstrap_changes
    ):
        findings.add(
            "core.review.incomplete",
            "design-review.toml",
            "Bootstrap approval is not allowed for this change.",
        )
    judges = review.get("judges")
    approved_roles = {
        item.get("role")
        for item in judges or []
        if isinstance(item, dict) and item.get("status") == "approved"
    }
    if (
        not isinstance(judges, list)
        or len(judges) != len(policy.required_roles)
        or approved_roles != set(policy.required_roles)
    ):
        findings.add(
            "core.review.incomplete",
            "design-review.toml",
            "Review must contain exactly the six required approved roles.",
        )
    review_findings = review.get("findings", [])
    valid_findings = isinstance(review_findings, list)
    finding_ids: set[str] = set()
    if valid_findings:
        for item in review_findings:
            if not isinstance(item, dict):
                valid_findings = False
                break
            finding_id = item.get("id")
            priority = item.get("priority")
            severity = item.get("severity")
            count = item.get("consensus_count")
            status = item.get("status")
            resolution = item.get("resolution")
            evidence = item.get("evidence")
            if (
                not isinstance(finding_id, str)
                or not _REVIEW_ID_RE.fullmatch(finding_id)
                or finding_id in finding_ids
                or priority not in {"P0", "P1", "P2"}
                or severity not in {"CRIT", "HIGH", "MED", "LOW"}
                or not isinstance(count, int)
                or isinstance(count, bool)
                or not 1 <= count <= len(policy.required_roles)
                or status not in {"resolved", "accepted"}
                or (priority == "P0" and status != "resolved")
                or not _valid_reason(resolution)
                or not isinstance(evidence, list)
                or not evidence
                or not all(isinstance(entry, str) and len(entry.strip()) >= 3 for entry in evidence)
            ):
                valid_findings = False
                break
            finding_ids.add(finding_id)
    if not valid_findings:
        findings.add(
            "core.review.incomplete",
            "design-review.toml",
            "Review contains malformed or unresolved P0 findings.",
        )
    return {
        "reviewed_at": reviewed_at_date.isoformat() if reviewed_at_date else "",
        "reviewed_commit": reviewed_commit if isinstance(reviewed_commit, str) else "",
        "reviewed_commit_status": reviewed_commit_status,
    }


def _bounded_git_stdout(
    repo_root: Path, args: list[str], *, limit: int, timeout: float = 3
) -> tuple[int, bytes] | None:
    try:
        process = subprocess.Popen(
            ["git", *args],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None
    if process.stdout is None:
        process.kill()
        process.wait()
        return None
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return None
            for _, _ in selector.select(min(remaining, 0.1)):
                try:
                    chunk = os.read(descriptor, min(65_536, limit + 1 - len(output)))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(process.stdout)
                    continue
                output.extend(chunk)
                if len(output) > limit:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    return None
        try:
            return process.wait(timeout=max(0.1, deadline - time.monotonic())), bytes(output)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return None
    finally:
        selector.close()
        process.stdout.close()


def _git_batch_blobs(
    repo_root: Path,
    object_specs: tuple[str, ...],
    size_limits: tuple[int, ...],
    *,
    artifact_total_limit: int,
) -> tuple[bytes, ...] | None:
    request = "".join(f"{item}\n" for item in object_specs).encode()
    try:
        checked = subprocess.run(
            ["git", "cat-file", "--batch-check"],
            cwd=repo_root,
            input=request,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = checked.stdout.splitlines()
    if checked.returncode != 0 or len(lines) != len(object_specs):
        return None
    sizes: list[int] = []
    for line, size_limit in zip(lines, size_limits, strict=True):
        parts = line.rsplit(b" ", 2)
        try:
            object_type = parts[-2]
            size = int(parts[-1])
        except (IndexError, ValueError):
            return None
        if object_type != b"blob" or size < 0 or size > size_limit:
            return None
        sizes.append(size)
    if sum(sizes[1:]) > artifact_total_limit:
        return None
    try:
        batch = subprocess.run(
            ["git", "cat-file", "--batch"],
            cwd=repo_root,
            input=request,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output_limit = sum(sizes) + len(sizes) * 128
    if batch.returncode != 0 or len(batch.stdout) > output_limit:
        return None
    payloads: list[bytes] = []
    offset = 0
    for expected_size in sizes:
        header_end = batch.stdout.find(b"\n", offset)
        if header_end < 0:
            return None
        header = batch.stdout[offset:header_end].rsplit(b" ", 2)
        try:
            object_type = header[-2]
            reported_size = int(header[-1])
        except (IndexError, ValueError):
            return None
        if object_type != b"blob" or reported_size != expected_size:
            return None
        start = header_end + 1
        end = start + reported_size
        if end >= len(batch.stdout) or batch.stdout[end : end + 1] != b"\n":
            return None
        payloads.append(batch.stdout[start:end])
        offset = end + 1
    return tuple(payloads) if offset == len(batch.stdout) else None


def _reviewed_tree_digest(
    snapshot: ChangeSnapshot, policy: Policy, reviewed_commit: str
) -> tuple[str | None, str]:
    repo_root = Path(snapshot.repo_root)
    if not (repo_root / ".git").exists():
        return None, "not_git"
    try:
        commit_check = subprocess.run(
            ["git", "cat-file", "-e", f"{reviewed_commit}^{{commit}}"],
            cwd=repo_root,
            capture_output=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "error"
    if commit_check.returncode != 0:
        return None, "missing"
    change_prefix = f"openspec/changes/{snapshot.name}/"
    tree_limit = (policy.limits.max_files_per_change + 1) * 1024
    tree = _bounded_git_stdout(
        repo_root,
        ["ls-tree", "-r", "-z", "--name-only", reviewed_commit, "--", change_prefix],
        limit=tree_limit,
    )
    if tree is None:
        return None, "error"
    tree_returncode, tree_stdout = tree
    if tree_returncode != 0:
        return None, "tree_error"
    reviewed_paths = {
        path.removeprefix(change_prefix)
        for raw in tree_stdout.split(b"\0")
        if raw
        for path in [raw.decode("utf-8", "surrogateescape")]
        if path.startswith(change_prefix)
        and (
            path.removeprefix(change_prefix) in policy.root_files
            or _SPEC_PATH_RE.fullmatch(path.removeprefix(change_prefix))
        )
        and path.removeprefix(change_prefix) not in policy.digest_excludes
    }
    current_paths = {
        artifact.path
        for artifact in snapshot.artifacts
        if artifact.path not in policy.digest_excludes
    }
    if reviewed_paths != current_paths:
        return None, "inventory_mismatch"
    current_artifacts = tuple(
        artifact for artifact in snapshot.artifacts if artifact.path not in policy.digest_excludes
    )
    object_specs = (
        f"{reviewed_commit}:design-policy/{policy.policy_version}.toml",
        *(
            f"{reviewed_commit}:openspec/changes/{snapshot.name}/{artifact.path}"
            for artifact in current_artifacts
        ),
    )
    blobs = _git_batch_blobs(
        repo_root,
        object_specs,
        (1_048_576, *(policy.limits.max_file_bytes for _ in current_artifacts)),
        artifact_total_limit=policy.limits.max_total_bytes_per_change,
    )
    if blobs is None:
        return None, "artifact_error"
    if f"sha256:{hashlib.sha256(blobs[0]).hexdigest()}" != policy.digest:
        return None, "policy_mismatch"
    payloads = tuple(
        (artifact.path, payload)
        for artifact, payload in zip(current_artifacts, blobs[1:], strict=True)
    )
    return artifact_payload_digest(payloads, policy.digest_excludes), "verified"


def _apply_exceptions(
    policy: Policy,
    raw_exceptions: tuple[dict[str, Any], ...],
    effective_date: date,
    findings: _Findings,
) -> tuple[ExceptionRecord, ...]:
    records: list[ExceptionRecord] = []
    for index, row in enumerate(raw_exceptions, 1):
        rule_id = row.get("rule")
        owner = row.get("owner")
        reason = row.get("reason")
        expires_raw = row.get("expires")
        try:
            expires = (
                expires_raw
                if isinstance(expires_raw, date)
                else date.fromisoformat(expires_raw)
                if isinstance(expires_raw, str)
                else None
            )
            rule = policy.rule(rule_id) if isinstance(rule_id, str) else None
        except (ValueError, KeyError):
            expires = None
            rule = None
        state = "applied"
        if (
            rule is None
            or not rule.suppressible
            or not _valid_reason(reason)
            or not isinstance(owner, str)
            or len(owner.strip()) < 2
            or expires is None
        ):
            state = "invalid"
        elif expires is not None:
            state = exception_state(expires, effective_date)
        if state in {"invalid", "expired"}:
            findings.add(
                "core.exception.invalid",
                "design-quality.toml",
                f"Exception entry {index} is {state}.",
            )
        elif rule is not None:
            findings.items = [
                replace(item, suppressed=True)
                if item.rule_id == rule.rule_id and not item.suppressed
                else item
                for item in findings.items
            ]
        records.append(
            ExceptionRecord(
                rule_id=str(rule_id or ""),
                owner=str(owner or ""),
                reason=str(reason or ""),
                expires=expires or effective_date,
                state=state,
            )
        )
    return tuple(records)


def _evaluate_snapshot(
    snapshot: ChangeSnapshot,
    policy: Policy,
    *,
    strict: bool,
    effective_date: date,
    require_governance: bool,
) -> DesignReport:
    findings = _Findings(policy)
    marker = _marker(snapshot, policy, findings)
    if marker is None:
        if require_governance:
            findings.add(
                "core.governance.missing",
                "design-quality.toml",
                "A new or previously governed change cannot omit its governance marker.",
            )
        verify_snapshot(snapshot, policy)
        return DesignReport(
            change=snapshot.name,
            policy_version=policy.policy_version,
            policy_digest=policy.digest,
            artifact_digest=snapshot.artifact_digest,
            strict=strict,
            effective_date=effective_date,
            approval_eligible=False,
            governance_status="REQUIRED_MISSING" if require_governance else "NOT_GOVERNED",
            profiles=(),
            findings=tuple(findings.items),
            exceptions=(),
            artifacts=snapshot.inventory,
            metadata={"total_bytes": snapshot.total_bytes},
        )

    impacts, evidence, obligations, raw_exceptions = marker
    _check_impact_consistency(snapshot, policy, impacts, findings)
    selected_names = set(selected_profile_names(snapshot, policy, impacts))
    profiles = tuple(profile for profile in policy.profiles if profile.name in selected_names)
    _check_required_artifacts(snapshot, policy, findings)
    _check_brief(snapshot, policy, profiles, findings)
    _check_profiles(profiles, evidence, findings, policy_profiles=policy.profiles)
    _check_obligations(snapshot, obligations, findings)
    design = snapshot.text("design.md") or ""
    if "new abstraction" in design.lower() and "consumer" not in design.lower():
        findings.add(
            "structure.abstraction_evidence",
            "design.md",
            "A new abstraction is proposed without consumer evidence.",
        )
    review_metadata = _check_review(snapshot, policy, effective_date, findings) if strict else {}
    exceptions = _apply_exceptions(policy, raw_exceptions, effective_date, findings)
    if len(findings.items) > policy.limits.max_findings:
        findings.items = findings.items[: policy.limits.max_findings - 1]
        findings.add(
            "core.governance.invalid",
            "design-quality.toml",
            f"Finding limit {policy.limits.max_findings} reached; report was truncated.",
        )
    verify_snapshot(snapshot, policy)
    ordered = tuple(
        sorted(findings.items, key=lambda item: (item.rule_id, item.path, item.message))
    )
    active_blockers = any(
        item.severity is Severity.BLOCKER and not item.suppressed for item in ordered
    )
    active_warnings = any(
        item.severity is Severity.WARNING and not item.suppressed for item in ordered
    )
    approval_eligible = strict and not active_blockers and not active_warnings
    return DesignReport(
        change=snapshot.name,
        policy_version=policy.policy_version,
        policy_digest=policy.digest,
        artifact_digest=snapshot.artifact_digest,
        strict=strict,
        effective_date=effective_date,
        approval_eligible=approval_eligible,
        governance_status="GOVERNED",
        profiles=tuple(item.name for item in profiles),
        findings=ordered,
        exceptions=exceptions,
        artifacts=snapshot.inventory,
        metadata={"total_bytes": snapshot.total_bytes, **review_metadata},
    )


def evaluate_changes(
    repo_root: Path,
    changes: tuple[str, ...],
    *,
    strict: bool = False,
    effective_date: date | None = None,
    today: date | None = None,
    require_governance: frozenset[str] = frozenset(),
    policy: Policy | None = None,
) -> tuple[DesignReport, ...]:
    current_date = today or datetime.now(timezone.utc).date()
    active_date = effective_date or current_date
    if strict and active_date != current_date:
        raise DesignQualityError(
            "Strict implementation approval requires the current UTC date; "
            "historical --as-of is diagnostic-only"
        )
    active_policy = policy or load_policy(repo_root)
    snapshots = load_snapshots(repo_root, changes, active_policy)
    return tuple(
        _evaluate_snapshot(
            snapshot,
            active_policy,
            strict=strict,
            effective_date=active_date,
            require_governance=snapshot.name in require_governance,
        )
        for snapshot in snapshots
    )


def evaluate_change(
    repo_root: Path,
    change: str,
    *,
    strict: bool = False,
    effective_date: date | None = None,
    today: date | None = None,
    require_governance: bool = False,
    policy: Policy | None = None,
) -> DesignReport:
    required = frozenset({change}) if require_governance else frozenset()
    return evaluate_changes(
        repo_root,
        (change,),
        strict=strict,
        effective_date=effective_date,
        today=today,
        require_governance=required,
        policy=policy,
    )[0]
