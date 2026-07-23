"""Load and validate immutable design policy versions."""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.models import (
    EvidenceSchema,
    Limits,
    Policy,
    Profile,
    Rule,
    Severity,
)
from trade_py.devtools.quality.toml_compat import tomllib


def _table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise DesignQualityError(f"design policy: {key} must be a table")
    return value


def _strings(raw: dict[str, Any], key: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise DesignQualityError(f"design policy: {key} must be an array of non-empty strings")
    if not value and not allow_empty:
        raise DesignQualityError(f"design policy: {key} must not be empty")
    return tuple(value)


def _positive_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DesignQualityError(f"design policy: {key} must be a positive integer")
    return value


def _evidence_schema(raw: Any, path: str, *, depth: int = 0) -> EvidenceSchema:
    if depth > 4 or not isinstance(raw, dict):
        raise DesignQualityError(f"design policy: {path} must be a bounded schema table")
    allowed = {
        "kind",
        "minimum",
        "maximum",
        "equals",
        "values",
        "required_values",
        "fields",
        "allow_extra",
        "min_length",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise DesignQualityError(
            f"design policy: {path} has unknown schema keys: {', '.join(unknown)}"
        )
    kind = raw.get("kind")
    if kind not in {
        "text",
        "identifier",
        "boolean",
        "integer",
        "number",
        "enum",
        "string_set",
        "table",
    }:
        raise DesignQualityError(f"design policy: {path}.kind is unsupported")
    minimum = raw.get("minimum")
    maximum = raw.get("maximum")
    for name, value in (("minimum", minimum), ("maximum", maximum)):
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise DesignQualityError(f"design policy: {path}.{name} must be numeric")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise DesignQualityError(f"design policy: {path} has an inverted numeric range")
    equals = raw.get("equals")
    if equals is not None and not isinstance(equals, (str, int, float, bool)):
        raise DesignQualityError(f"design policy: {path}.equals must be scalar")
    if kind == "boolean" and equals is not None and not isinstance(equals, bool):
        raise DesignQualityError(f"design policy: {path}.equals must be boolean")
    if (
        kind in {"integer", "number"}
        and equals is not None
        and (not isinstance(equals, (int, float)) or isinstance(equals, bool))
    ):
        raise DesignQualityError(f"design policy: {path}.equals must be numeric")
    values_raw = raw.get("values", [])
    required_raw = raw.get("required_values", [])
    if not isinstance(values_raw, list) or not all(
        isinstance(item, str) and item for item in values_raw
    ):
        raise DesignQualityError(f"design policy: {path}.values must contain strings")
    if not isinstance(required_raw, list) or not all(
        isinstance(item, str) and item for item in required_raw
    ):
        raise DesignQualityError(f"design policy: {path}.required_values must contain strings")
    values = tuple(values_raw)
    required_values = tuple(required_raw)
    if len(values) != len(set(values)) or len(required_values) != len(set(required_values)):
        raise DesignQualityError(f"design policy: {path} contains duplicate enum values")
    if required_values and not set(required_values) <= set(values):
        raise DesignQualityError(f"design policy: {path}.required_values must be allowed values")
    if kind in {"enum", "string_set"} and not values:
        raise DesignQualityError(f"design policy: {path}.values must not be empty")
    fields_raw = raw.get("fields", {})
    if not isinstance(fields_raw, dict):
        raise DesignQualityError(f"design policy: {path}.fields must be a table")
    fields = {
        name: _evidence_schema(value, f"{path}.fields.{name}", depth=depth + 1)
        for name, value in fields_raw.items()
        if isinstance(name, str) and name
    }
    if len(fields) != len(fields_raw):
        raise DesignQualityError(f"design policy: {path}.fields has an invalid name")
    if kind == "table" and not fields:
        raise DesignQualityError(f"design policy: {path}.fields must not be empty")
    if kind != "table" and fields:
        raise DesignQualityError(f"design policy: {path}.fields is only valid for table schemas")
    allow_extra = raw.get("allow_extra", False)
    if not isinstance(allow_extra, bool):
        raise DesignQualityError(f"design policy: {path}.allow_extra must be boolean")
    min_length = raw.get("min_length", 12)
    if not isinstance(min_length, int) or isinstance(min_length, bool) or min_length <= 0:
        raise DesignQualityError(f"design policy: {path}.min_length must be positive")
    return EvidenceSchema(
        kind=kind,
        minimum=float(minimum) if minimum is not None else None,
        maximum=float(maximum) if maximum is not None else None,
        equals=equals,
        values=values,
        required_values=required_values,
        fields=fields,
        allow_extra=allow_extra,
        min_length=min_length,
    )


def _load_profiles(
    raw: dict[str, Any], supported_impacts: set[str], rules: tuple[Rule, ...]
) -> tuple[Profile, ...]:
    profiles: list[Profile] = []
    rule_ids = {item.rule_id for item in rules}
    for name, value in sorted(raw.items()):
        if not isinstance(value, dict):
            raise DesignQualityError(f"design policy: profiles.{name} must be a table")
        impacts = _strings(value, "impacts", allow_empty=True)
        unknown = sorted(set(impacts) - supported_impacts)
        if unknown:
            raise DesignQualityError(
                f"design policy: profiles.{name} has unknown impacts: {', '.join(unknown)}"
            )
        finding_rule = value.get("finding_rule")
        required_evidence = _strings(value, "required_evidence", allow_empty=True)
        schema_raw = value.get("evidence_schema", {})
        if not isinstance(schema_raw, dict):
            raise DesignQualityError(
                f"design policy: profiles.{name}.evidence_schema must be a table"
            )
        unknown_schema = sorted(set(schema_raw) - set(required_evidence))
        if unknown_schema:
            raise DesignQualityError(
                f"design policy: profiles.{name}.evidence_schema has unknown fields: "
                + ", ".join(unknown_schema)
            )
        evidence_schema = {
            field_name: _evidence_schema(
                schema,
                f"profiles.{name}.evidence_schema.{field_name}",
            )
            for field_name, schema in schema_raw.items()
        }
        if name == "core":
            if finding_rule is not None or required_evidence:
                raise DesignQualityError(
                    "design policy: profiles.core cannot define evidence enforcement"
                )
        elif (
            not isinstance(finding_rule, str)
            or finding_rule not in rule_ids
            or not required_evidence
        ):
            raise DesignQualityError(
                f"design policy: profiles.{name} requires a known finding_rule "
                "and non-empty required_evidence"
            )
        profiles.append(
            Profile(
                name=name,
                impacts=impacts,
                required_sections=_strings(value, "required_sections", allow_empty=True),
                finding_rule=finding_rule if isinstance(finding_rule, str) else None,
                required_evidence=required_evidence,
                evidence_schema=evidence_schema,
            )
        )
    if "core" not in {item.name for item in profiles}:
        raise DesignQualityError("design policy: profiles.core is required")
    finding_rule_counts = Counter(item.finding_rule for item in profiles if item.finding_rule)
    duplicated_rules = sorted(
        rule_id for rule_id, count in finding_rule_counts.items() if count > 1
    )
    if duplicated_rules:
        raise DesignQualityError("design policy: profile finding_rule values must be unique")
    return tuple(profiles)


def _load_impact_signals(
    raw: dict[str, Any], supported_impacts: tuple[str, ...]
) -> dict[str, tuple[str, ...]]:
    unknown = sorted(set(raw) - set(supported_impacts))
    if unknown:
        raise DesignQualityError(
            f"design policy: impact_signals has unknown impacts: {', '.join(unknown)}"
        )
    signals: dict[str, tuple[str, ...]] = {}
    for impact in supported_impacts:
        patterns = _strings(raw, impact, allow_empty=True) if impact in raw else ()
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise DesignQualityError(
                    f"design policy: invalid impact signal for {impact}: {pattern!r}"
                ) from exc
        signals[impact] = patterns
    return signals


def _load_rules(raw: Any) -> tuple[Rule, ...]:
    if not isinstance(raw, list) or not raw:
        raise DesignQualityError("design policy: rules must be a non-empty array of tables")
    rules: list[Rule] = []
    for index, value in enumerate(raw, 1):
        if not isinstance(value, dict):
            raise DesignQualityError(f"design policy: rules[{index}] must be a table")
        try:
            rule_id = value["id"]
            severity = Severity(value["severity"])
            suppressible = value["suppressible"]
            remediation = value["remediation"]
        except (KeyError, ValueError) as exc:
            raise DesignQualityError(f"design policy: rules[{index}] is invalid") from exc
        if (
            not isinstance(rule_id, str)
            or not rule_id
            or not isinstance(suppressible, bool)
            or not isinstance(remediation, str)
            or not remediation
        ):
            raise DesignQualityError(f"design policy: rules[{index}] has invalid fields")
        if severity is Severity.BLOCKER and suppressible:
            raise DesignQualityError(f"design policy: blocker {rule_id} cannot be suppressible")
        rules.append(
            Rule(
                rule_id=rule_id,
                severity=severity,
                suppressible=suppressible,
                remediation=remediation,
            )
        )
    identifiers = [item.rule_id for item in rules]
    duplicates = sorted(item for item, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        raise DesignQualityError(f"design policy: duplicate rule IDs: {', '.join(duplicates)}")
    return tuple(rules)


def load_policy(repo_root: Path, version: str = "v1") -> Policy:
    if not version or "/" in version or "\\" in version or version in {".", ".."}:
        raise DesignQualityError(f"Invalid design policy version: {version!r}")
    root = repo_root.resolve()
    policy_dir = root / "design-policy"
    path = policy_dir / f"{version}.toml"
    if policy_dir.is_symlink() or path.is_symlink() or not path.is_file():
        raise DesignQualityError(f"Missing immutable design policy: design-policy/{version}.toml")
    descriptor = None
    try:
        directory_descriptor = os.open(
            policy_dir,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            descriptor = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_descriptor,
            )
        finally:
            os.close(directory_descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(1_048_577)
        if len(payload) > 1_048_576:
            raise DesignQualityError(f"Design policy {path.name} exceeds the 1 MiB limit")
    except OSError as exc:
        raise DesignQualityError(f"Cannot safely read immutable policy {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        raw = tomllib.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise DesignQualityError(f"Invalid design policy {path.name}: {exc}") from exc
    if raw.get("schema_version") != 1 or raw.get("policy_version") != version:
        raise DesignQualityError(f"Unsupported design policy schema/version in {path.name}")

    limits = _table(raw, "limits")
    artifacts = _table(raw, "artifacts")
    brief = _table(raw, "brief")
    impacts = _table(raw, "impacts")
    review = _table(raw, "review")
    required_impacts = _strings(impacts, "required")
    if len(set(required_impacts)) != len(required_impacts):
        raise DesignQualityError("design policy: impacts.required contains duplicates")

    rules = _load_rules(raw.get("rules"))
    required_root_files = _strings(artifacts, "required_root_files")
    root_files = _strings(artifacts, "root_files")
    spec_pattern = artifacts.get("spec_pattern")
    if spec_pattern != "specs/*/spec.md":
        raise DesignQualityError(
            "design policy: artifacts.spec_pattern must be exactly 'specs/*/spec.md' in v1"
        )
    if not set(required_root_files) <= set(root_files):
        raise DesignQualityError(
            "design policy: required_root_files must be included in root_files"
        )
    policy = Policy(
        schema_version=1,
        policy_version=version,
        digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        limits=Limits(
            max_files_per_change=_positive_int(limits, "max_files_per_change"),
            max_file_bytes=_positive_int(limits, "max_file_bytes"),
            max_total_bytes_per_change=_positive_int(limits, "max_total_bytes_per_change"),
            max_findings=_positive_int(limits, "max_findings"),
            max_changes_per_batch=_positive_int(limits, "max_changes_per_batch"),
            max_total_bytes_per_batch=_positive_int(limits, "max_total_bytes_per_batch"),
        ),
        root_files=root_files,
        required_root_files=required_root_files,
        minimum_spec_files=_positive_int(artifacts, "minimum_spec_files"),
        spec_pattern=spec_pattern,
        digest_excludes=_strings(artifacts, "digest_excludes", allow_empty=True),
        required_sections=_strings(brief, "required_sections"),
        placeholders=_strings(brief, "placeholders"),
        minimum_section_characters=_positive_int(brief, "minimum_section_characters"),
        required_impacts=required_impacts,
        impact_signals=_load_impact_signals(_table(raw, "impact_signals"), required_impacts),
        profiles=_load_profiles(_table(raw, "profiles"), set(required_impacts), rules),
        required_roles=_strings(review, "required_roles"),
        bootstrap_changes=_strings(review, "bootstrap_changes", allow_empty=True),
        rules=rules,
    )
    required_rule_ids = {
        "core.governance.missing",
        "core.governance.invalid",
        "core.artifact.missing",
        "core.policy.immutable",
        "core.impact.incomplete",
        "core.impact.contradiction",
        "core.brief.missing",
        "core.brief.section",
        "core.obligation.invalid",
        "core.obligation.reference",
        "core.review.missing",
        "core.review.stale",
        "core.review.incomplete",
        "core.exception.invalid",
        "contract.compatibility.missing",
        "storage.write_safety.missing",
        "migration.compatibility.missing",
        "forecast.evidence.missing",
        "external_event.evidence.missing",
        "concurrency.evidence.missing",
        "structure.catch_all",
        "structure.abstraction_evidence",
    }
    missing = sorted(required_rule_ids - {item.rule_id for item in policy.rules})
    if missing:
        raise DesignQualityError(f"design policy: missing required rules: {', '.join(missing)}")
    return policy
