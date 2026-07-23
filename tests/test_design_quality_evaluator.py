from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.evaluate import evaluate_change, evaluate_changes
from trade_py.devtools.design_quality.models import DesignReport, EvidenceSchema
from trade_py.devtools.design_quality.policy import load_policy
from trade_py.devtools.design_quality.render import render_report_text
from trade_py.devtools.design_quality.snapshot import load_snapshots, verify_snapshot
from trade_py.devtools.design_quality.v1_contract import exception_state
from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.executor import SubprocessExecutor
from trade_py.devtools.quality.models import CheckStep, FailureKind, ResultStatus

REPO_ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 7, 20)


CORE_SECTIONS = (
    "Requirements and acceptance",
    "Ownership and boundaries",
    "Data and state invariants",
    "Contracts and compatibility",
    "Failure and recovery",
    "Performance and capacity",
    "Observability and operations",
    "Validation strategy",
    "Alternatives and trade-offs",
    "Rollout and rollback",
)
IMPACTS = (
    "public_contract",
    "persistent_write",
    "schema_migration",
    "point_in_time",
    "predictive_model",
    "external_event_data",
    "runtime_concurrency",
)


@pytest.mark.parametrize(
    ("days", "expected"),
    ((-1, "expired"), (0, "expiring"), (14, "expiring"), (15, "applied")),
)
def test_v1_exception_state_boundaries_are_shared(days: int, expected: str) -> None:
    assert exception_state(TODAY + timedelta(days=days), TODAY) == expected


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "openspec" / "changes").mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "design-policy", tmp_path / "design-policy")
    return tmp_path


def _design(extra: dict[str, str] | None = None) -> str:
    sections = {
        name: (
            f"Evidence for {name} names the owner, affected boundary, failure state, "
            "compatibility behavior, bounded validation, and explicit acceptance result."
        )
        for name in CORE_SECTIONS
    }
    sections.update(extra or {})
    body = "\n\n".join(f"### {name}\n\n{text}" for name, text in sections.items())
    return f"## Context\n\nFixture context.\n\n## Design Quality Brief\n\n{body}\n"


def _write_change(
    repo: Path,
    name: str,
    *,
    applied: frozenset[str] = frozenset(),
    design: str | None = None,
    exceptions: str = "",
) -> Path:
    change = repo / "openspec" / "changes" / name
    spec_dir = change / "specs" / "fixture-capability"
    spec_dir.mkdir(parents=True)
    (change / ".openspec.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
    (change / "proposal.md").write_text("## Why\n\nFixture proposal.\n", encoding="utf-8")
    (change / "design.md").write_text(design or _design(), encoding="utf-8")
    (change / "tasks.md").write_text(
        "## 1. Validation\n\n"
        "- [ ] 1.1 Run focused validation. "
        "[validates:fixture.contract] [validation:test]\n",
        encoding="utf-8",
    )
    (spec_dir / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: Fixture contract\n"
        "The system SHALL preserve the fixture contract.\n\n"
        "#### Scenario: Fixture\n- **WHEN** it runs\n- **THEN** it passes\n",
        encoding="utf-8",
    )
    impact_rows = "\n\n".join(
        "\n".join(
            (
                "[[impacts]]",
                f'id = "{impact}"',
                f"applies = {'true' if impact in applied else 'false'}",
                f'reason = "The fixture explicitly declares whether {impact} affects this change."',
            )
        )
        for impact in IMPACTS
    )
    marker = f"""schema_version = 1
policy_version = "v1"

{impact_rows}

[[obligations]]
id = "fixture.contract"
owner = "tests.fixture"
paths = ["tests/fixture.py"]
contracts = ["fixture"]
failure_states = ["fixture_failure"]
spec_requirements = ["fixture-capability:Fixture contract"]
validation_tasks = ["1.1"]
{exceptions}
"""
    (change / "design-quality.toml").write_text(marker, encoding="utf-8")
    return change


def _rule_ids(report: DesignReport) -> set[str]:
    return {item.rule_id for item in report.findings}


def _add_profile_evidence(
    repo: Path,
    change: Path,
    profile_name: str,
    *,
    missing: str | None = None,
    override: tuple[str, object] | None = None,
) -> None:
    policy = load_policy(repo)
    profile = next(item for item in policy.profiles if item.name == profile_name)
    design = change / "design.md"
    additions = "\n\n".join(
        f"### {section}\n\nStructured evidence for {section} is owned, bounded, testable, and auditable."
        for section in profile.required_sections
        if section not in CORE_SECTIONS
    )
    if additions:
        design.write_text(f"{design.read_text(encoding='utf-8')}\n{additions}\n", encoding="utf-8")
    rows = [f"[evidence.{profile_name}]"]
    for field in profile.required_evidence:
        if field == missing:
            continue
        schema = profile.evidence_schema.get(field, EvidenceSchema(kind="text"))
        value = override[1] if override and override[0] == field else _valid_evidence(schema, field)
        rows.append(f"{field} = {_toml_literal(value)}")
    marker = change / "design-quality.toml"
    marker.write_text(
        f"{marker.read_text(encoding='utf-8')}\n\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def _valid_evidence(schema: EvidenceSchema, field: str) -> object:
    if schema.kind == "text":
        return f"Structured evidence for {field} is explicit, owned, bounded, and validated."
    if schema.kind == "identifier":
        return f"source/{field}.v1"
    if schema.kind == "boolean":
        return schema.equals if isinstance(schema.equals, bool) else True
    if schema.kind == "integer":
        return max(1, int(schema.minimum or 1))
    if schema.kind == "number":
        return max(0.0, float(schema.minimum or 0))
    if schema.kind == "enum":
        return schema.values[0]
    if schema.kind == "string_set":
        return list(schema.required_values or schema.values[:1])
    if schema.kind == "table":
        return {name: _valid_evidence(child, name) for name, child in schema.fields.items()}
    raise AssertionError(f"Unsupported fixture schema: {schema.kind}")


def _toml_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{ " + ", ".join(f"{key} = {_toml_literal(item)}" for key, item in value.items()) + " }"
        )
    raise AssertionError(f"Unsupported TOML fixture value: {value!r}")


def _invalid_evidence(schema: EvidenceSchema) -> object:
    if schema.kind == "boolean":
        return not schema.equals if isinstance(schema.equals, bool) else "not-a-boolean"
    if schema.kind in {"integer", "number"}:
        return (schema.minimum or 0) - 1
    if schema.kind == "enum":
        return "invalid-policy-value"
    if schema.kind == "string_set":
        return []
    if schema.kind == "table":
        return {}
    if schema.kind == "identifier":
        return "unknown-source"
    return "short"


def _write_review(
    repo: Path,
    change: Path,
    *,
    reviewed_at: str = "2026-07-20",
    reviewed_commit: str = "a" * 40,
) -> Path:
    policy = load_policy(repo)
    digest = load_snapshots(repo, (change.name,), policy)[0].artifact_digest
    judges = "\n\n".join(
        f'[[judges]]\nrole = "{role}"\nstatus = "approved"' for role in policy.required_roles
    )
    review = change / "design-review.toml"
    review.write_text(
        f'''schema_version = 1
policy_version = "v1"
policy_digest = "{policy.digest}"
artifact_digest_algorithm = "sha256-path-content-v1"
artifact_digest = "{digest}"
reviewed_commit = "{reviewed_commit}"
reviewed_at = "{reviewed_at}"
status = "approved"

{judges}
''',
        encoding="utf-8",
    )
    return review


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def test_valid_governed_change_passes_pre_review_diagnostics(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_change(repo, "valid-change")

    report = evaluate_change(repo, "valid-change", today=TODAY)

    assert report.status == "DIAGNOSTIC"
    assert report.exit_code == 0
    assert report.governance_status == "GOVERNED"
    assert report.profiles == ("core",)
    assert report.findings == ()


def test_repository_bootstrap_change_passes_strict_self_check() -> None:
    report = evaluate_change(REPO_ROOT, "add-design-quality-gates", strict=True)

    assert report.status == "PASS"
    assert report.approval_eligible is True
    assert report.findings == ()


def test_missing_governance_is_distinct_from_pass(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = repo / "openspec" / "changes" / "historical-change"
    change.mkdir()
    (change / "proposal.md").write_text("historical\n", encoding="utf-8")

    historical = evaluate_change(repo, "historical-change", today=TODAY)
    required = evaluate_change(repo, "historical-change", today=TODAY, require_governance=True)

    assert historical.status == "NOT_GOVERNED"
    assert historical.exit_code == 0
    assert required.status == "FAIL"
    assert "core.governance.missing" in _rule_ids(required)


@pytest.mark.parametrize(
    ("impact", "expected_rule"),
    (
        ("predictive_model", "forecast.evidence.missing"),
        ("persistent_write", "storage.write_safety.missing"),
        ("external_event_data", "external_event.evidence.missing"),
    ),
)
def test_profile_missing_evidence_is_a_blocker(
    tmp_path: Path, impact: str, expected_rule: str
) -> None:
    repo = _repo(tmp_path)
    _write_change(repo, "profile-change", applied=frozenset({impact}))

    report = evaluate_change(repo, "profile-change", today=TODAY)

    assert report.exit_code == 1
    assert expected_rule in _rule_ids(report)
    assert "core.brief.section" in _rule_ids(report)


@pytest.mark.parametrize(
    ("profile_name", "impact"),
    (
        ("contract", "public_contract"),
        ("storage", "persistent_write"),
        ("forecast", "predictive_model"),
        ("external_event", "external_event_data"),
        ("concurrency", "runtime_concurrency"),
    ),
)
def test_complete_structured_profile_evidence_passes(
    tmp_path: Path, profile_name: str, impact: str
) -> None:
    repo = _repo(tmp_path)
    applied = {impact}
    if profile_name == "forecast":
        applied.add("point_in_time")
    change = _write_change(
        repo, f"{profile_name}-evidence".replace("_", "-"), applied=frozenset(applied)
    )
    _add_profile_evidence(repo, change, profile_name)

    report = evaluate_change(repo, change.name, today=TODAY)

    assert report.exit_code == 0
    assert report.findings == ()


def test_complete_schema_migration_requires_storage_and_transition_evidence(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "migration-evidence", applied=frozenset({"schema_migration"}))
    _add_profile_evidence(repo, change, "storage")
    _add_profile_evidence(repo, change, "migration")

    report = evaluate_change(repo, change.name, today=TODAY)

    assert report.exit_code == 0
    assert {"core", "storage", "migration"} <= set(report.profiles)


def test_false_forecast_impact_signal_conservatively_enables_profile(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    exceptions = """
[[exceptions]]
rule = "core.impact.contradiction"
owner = "reviewer"
reason = "Temporary exception while applicability is corrected with owned evidence."
expires = 2026-08-30
"""
    change = _write_change(repo, "false-forecast", exceptions=exceptions)
    (change / "proposal.md").write_text(
        "This change introduces a forecast ranking for trading decisions.\n", encoding="utf-8"
    )
    _write_review(repo, change)

    report = evaluate_change(repo, change.name, strict=True, today=TODAY)

    assert "forecast" in report.profiles
    assert "forecast.evidence.missing" in _rule_ids(report)
    assert report.approval_eligible is False


@pytest.mark.parametrize(
    "claim",
    (
        "The system SHALL produce a daily forecast of expected next-day returns.",
        "The service emits a directional probability for the next session.",
        "The job predicts future market direction for each instrument.",
        "The pipeline ranks assets by expected forward returns.",
    ),
)
def test_false_forecast_synonyms_cannot_skip_safety_profile(tmp_path: Path, claim: str) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "false-forecast-synonym")
    (change / "proposal.md").write_text(f"{claim}\n", encoding="utf-8")

    report = evaluate_change(repo, change.name, today=TODAY)

    assert "forecast" in report.profiles
    assert "core.impact.contradiction" in _rule_ids(report)
    assert "forecast.evidence.missing" in _rule_ids(report)


def test_typed_forecast_contract_rejects_numeric_unknown_fallback(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "numeric-fallback", applied=frozenset({"predictive_model"}))
    _add_profile_evidence(repo, change, "forecast")
    marker = change / "design-quality.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            "no_numeric_fallback = true", "no_numeric_fallback = false"
        ),
        encoding="utf-8",
    )
    _write_review(repo, change)

    report = evaluate_change(repo, change.name, strict=True, today=TODAY)

    assert "forecast.evidence.missing" in _rule_ids(report)
    assert report.approval_eligible is False


def test_typed_external_event_contract_rejects_ingestion_time_fallback(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "unsafe-event-clock", applied=frozenset({"external_event_data"}))
    _add_profile_evidence(repo, change, "external_event")
    marker = change / "design-quality.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            'source = "source_event_time"', 'source = "ingestion_now"', 1
        ),
        encoding="utf-8",
    )
    _write_review(repo, change)

    report = evaluate_change(repo, change.name, strict=True, today=TODAY)

    assert "external_event.evidence.missing" in _rule_ids(report)
    assert report.approval_eligible is False


def test_typed_external_event_contract_rejects_extreme_integer_without_crashing(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "extreme-event-quota", applied=frozenset({"external_event_data"}))
    policy = load_policy(repo)
    profile = next(item for item in policy.profiles if item.name == "external_event")
    quota = _valid_evidence(profile.evidence_schema["quota"], "quota")
    assert isinstance(quota, dict)
    quota["amount"] = 10**4000
    _add_profile_evidence(repo, change, "external_event", override=("quota", quota))

    report = evaluate_change(repo, change.name, today=TODAY)

    assert "external_event.evidence.missing" in _rule_ids(report)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        (
            "source_identity",
            {
                "known": True,
                "source_id": "unknown-source",
                "source_kind": "publisher",
            },
        ),
        (
            "provenance",
            {
                "status": "verified",
                "source_id": "different/source.v1",
                "reference": "contract/reference.v1",
            },
        ),
        (
            "provenance",
            {
                "status": "verified",
                "source_id": "source/source_id.v1",
                "reference": "unknown-provenance",
            },
        ),
        (
            "idempotency",
            {
                "enabled": False,
                "key_fields": ["source_id", "event_id"],
                "dedup_window_seconds": 3600,
                "persistence": "durable",
                "conflict_policy": "quarantine_conflict",
            },
        ),
    ),
)
def test_external_event_identity_provenance_and_idempotency_fail_closed(
    tmp_path: Path, field: str, value: object
) -> None:
    repo = _repo(tmp_path)
    change = _write_change(
        repo,
        f"unsafe-external-{field}".replace("_", "-"),
        applied=frozenset({"external_event_data"}),
    )
    _add_profile_evidence(repo, change, "external_event", override=(field, value))

    report = evaluate_change(repo, change.name, today=TODAY)

    assert "external_event.evidence.missing" in _rule_ids(report)


def test_schema_migration_without_compatibility_profile_is_blocked(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "unsafe-migration", applied=frozenset({"schema_migration"}))
    _add_profile_evidence(repo, change, "storage")
    (change / "design.md").write_text(
        _design(
            {
                "Schema migration compatibility": (
                    "Existing readers break immediately and no backward-compatible transition "
                    "is provided during the cutover."
                )
            }
        ),
        encoding="utf-8",
    )
    _write_review(repo, change)

    report = evaluate_change(repo, change.name, strict=True, today=TODAY)

    assert "migration.compatibility.missing" in _rule_ids(report)
    assert report.approval_eligible is False


PROFILE_FIELD_CASES = tuple(
    (profile.name, profile.impacts[0], field, profile.finding_rule)
    for profile in load_policy(REPO_ROOT).profiles
    if profile.name != "core"
    for field in profile.required_evidence
)

TYPED_PROFILE_CASES = tuple(
    (profile.name, profile.impacts[0], field, schema, profile.finding_rule)
    for profile in load_policy(REPO_ROOT).profiles
    if profile.name != "core"
    for field, schema in profile.evidence_schema.items()
)


@pytest.mark.parametrize(("profile_name", "impact", "missing", "rule_id"), PROFILE_FIELD_CASES)
def test_every_structured_profile_field_is_required(
    tmp_path: Path,
    profile_name: str,
    impact: str,
    missing: str,
    rule_id: str,
) -> None:
    repo = _repo(tmp_path)
    change = _write_change(
        repo, f"missing-{profile_name}-{missing}".replace("_", "-"), applied=frozenset({impact})
    )
    _add_profile_evidence(repo, change, profile_name, missing=missing)

    report = evaluate_change(repo, change.name, today=TODAY)

    assert rule_id in _rule_ids(report)
    assert any(missing in item.message for item in report.findings)


@pytest.mark.parametrize(
    ("profile_name", "impact", "field", "schema", "rule_id"), TYPED_PROFILE_CASES
)
def test_every_typed_profile_field_rejects_invalid_values(
    tmp_path: Path,
    profile_name: str,
    impact: str,
    field: str,
    schema: EvidenceSchema,
    rule_id: str,
) -> None:
    repo = _repo(tmp_path)
    change = _write_change(
        repo, f"invalid-{profile_name}-{field}".replace("_", "-"), applied=frozenset({impact})
    )
    _add_profile_evidence(
        repo,
        change,
        profile_name,
        override=(field, _invalid_evidence(schema)),
    )

    report = evaluate_change(repo, change.name, today=TODAY)

    assert rule_id in _rule_ids(report)
    assert any(field in item.message for item in report.findings if item.rule_id == rule_id)


def test_false_impact_with_behavior_signal_is_visible_warning(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "contradictory-impact")
    (change / "proposal.md").write_text(
        "This change introduces a forecast ranking for trading decisions.\n", encoding="utf-8"
    )

    report = evaluate_change(repo, change.name, today=TODAY)

    assert "core.impact.contradiction" in _rule_ids(report)


def test_obligation_references_must_exist(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "orphan-obligation")
    marker = change / "design-quality.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8")
        .replace("fixture-capability:Fixture contract", "missing:Unknown requirement")
        .replace('["1.1"]', '["9.9"]'),
        encoding="utf-8",
    )

    report = evaluate_change(repo, "orphan-obligation", today=TODAY)

    assert "core.obligation.reference" in _rule_ids(report)


def test_obligation_requires_exact_capability_and_requirement_scenario(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    wrong_capability = _write_change(repo, "wrong-capability")
    marker = wrong_capability / "design-quality.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            "fixture-capability:Fixture contract", "other-capability:Fixture contract"
        ),
        encoding="utf-8",
    )
    missing_scenario = _write_change(repo, "missing-scenario")
    (missing_scenario / "specs" / "fixture-capability" / "spec.md").write_text(
        "### Requirement: Fixture contract\nThe contract exists without a scenario.\n",
        encoding="utf-8",
    )

    wrong_report = evaluate_change(repo, wrong_capability.name, today=TODAY)
    scenario_report = evaluate_change(repo, missing_scenario.name, today=TODAY)

    assert "core.obligation.reference" in _rule_ids(wrong_report)
    assert "core.obligation.reference" in _rule_ids(scenario_report)


def test_validation_task_requires_explicit_obligation_and_validation_semantics(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "decorative-review-task")
    tasks = change / "tasks.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8").replace(
            "Run focused validation. [validates:fixture.contract] [validation:test]",
            "Review the design color palette. [validates:fixture.contract] [validation:review]",
        ),
        encoding="utf-8",
    )

    report = evaluate_change(repo, change.name, today=TODAY)

    assert "core.obligation.reference" in _rule_ids(report)
    assert any("non_validation_tasks=1.1" in item.message for item in report.findings)


def test_duplicate_requirement_and_task_identifiers_fail_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    duplicate_requirement = _write_change(repo, "duplicate-requirement")
    spec = duplicate_requirement / "specs" / "fixture-capability" / "spec.md"
    spec.write_text(
        f"{spec.read_text(encoding='utf-8')}\n"
        "### Requirement: Fixture contract\nThe duplicate has no scenario.\n",
        encoding="utf-8",
    )
    duplicate_task = _write_change(repo, "duplicate-task")
    tasks = duplicate_task / "tasks.md"
    tasks.write_text(
        f"{tasks.read_text(encoding='utf-8')}\n- [ ] 1.1 Run another focused validation.\n",
        encoding="utf-8",
    )

    requirement_report = evaluate_change(repo, duplicate_requirement.name, today=TODAY)
    task_report = evaluate_change(repo, duplicate_task.name, today=TODAY)

    assert any(
        "Duplicate capability requirement" in item.message for item in requirement_report.findings
    )
    assert any("Duplicate task identifiers" in item.message for item in task_report.findings)


@pytest.mark.parametrize("missing", (".openspec.yaml", "proposal.md", "design.md", "tasks.md"))
def test_governed_change_requires_root_artifacts(tmp_path: Path, missing: str) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, f"missing-{missing.strip('.').replace('.', '-')}")
    (change / missing).unlink()

    report = evaluate_change(repo, change.name, today=TODAY)

    assert "core.artifact.missing" in _rule_ids(report)


def test_strict_review_requires_current_complete_provenance(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    valid = _write_change(repo, "valid-review")
    _write_review(repo, valid)
    stale = _write_change(repo, "stale-review")
    _write_review(repo, stale, reviewed_at="2026-07-19")
    malformed = _write_change(repo, "malformed-review")
    review = _write_review(repo, malformed)
    review.write_text(
        review.read_text(encoding="utf-8")
        + """
[[findings]]
id = "REVIEW-1"
status = "resolved"
resolution = "The issue was resolved with current evidence."
""",
        encoding="utf-8",
    )

    valid_report = evaluate_change(repo, valid.name, strict=True, today=TODAY)
    stale_report = evaluate_change(repo, stale.name, strict=True, today=TODAY)
    malformed_report = evaluate_change(repo, malformed.name, strict=True, today=TODAY)

    assert valid_report.approval_eligible is True
    text = render_report_text(valid_report)
    assert "reviewed_at=2026-07-20" in text
    assert "reviewed_commit=" in text
    assert "reviewed_commit_status=" in text
    assert "counts blockers=0 warnings=0 suppressed=0 exit_code=0" in text
    assert "core.review.stale" in _rule_ids(stale_report)
    assert "core.review.incomplete" in _rule_ids(malformed_report)


def test_strict_review_commit_tree_must_match_attested_artifacts(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "commit-bound-review")
    extra_spec = change / "specs" / "extra-capability" / "spec.md"
    extra_spec.parent.mkdir()
    extra_spec.write_text(
        "### Requirement: Extra contract\nRequirement.\n\n"
        "#### Scenario: Extra\n- **WHEN** extra runs\n- **THEN** it is visible\n",
        encoding="utf-8",
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "design@example.test")
    _git(repo, "config", "user.name", "Design Test")
    _git(repo, "add", "--", "design-policy", "openspec")
    _git(repo, "commit", "-m", "reviewed design")
    reviewed_commit = _git(repo, "rev-parse", "HEAD")
    _write_review(repo, change, reviewed_commit=reviewed_commit)

    valid = evaluate_change(repo, change.name, strict=True, today=TODAY)
    extra_spec.unlink()
    extra_spec.parent.rmdir()
    _write_review(repo, change, reviewed_commit=reviewed_commit)
    stale_inventory = evaluate_change(repo, change.name, strict=True, today=TODAY)
    design = change / "design.md"
    design.write_text(
        design.read_text(encoding="utf-8")
        + "\n### Commit tree divergence\n\nCurrent evidence differs from the reviewed tree.\n",
        encoding="utf-8",
    )
    _write_review(repo, change, reviewed_commit=reviewed_commit)
    stale = evaluate_change(repo, change.name, strict=True, today=TODAY)

    assert valid.approval_eligible is True
    assert "core.review.stale" in _rule_ids(stale_inventory)
    assert "core.review.stale" in _rule_ids(stale)
    assert any("Reviewed commit" in item.message for item in stale.findings)


def test_strict_review_content_binding_survives_squash_clone(tmp_path: Path) -> None:
    source = _repo(tmp_path / "source")
    change = _write_change(source, "portable-review")
    _git(source, "init")
    _git(source, "config", "user.email", "design@example.test")
    _git(source, "config", "user.name", "Design Test")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "reviewed design")
    reviewed_commit = _git(source, "rev-parse", "HEAD")
    _write_review(source, change, reviewed_commit=reviewed_commit)
    _git(source, "add", ".")
    _git(source, "commit", "-m", "review evidence")
    squash_tree = _git(source, "rev-parse", "HEAD^{tree}")
    squash_commit = _git(source, "commit-tree", squash_tree, "-m", "squashed design")
    _git(source, "update-ref", "refs/heads/master", squash_commit)
    clone = tmp_path / "clone"
    subprocess.run(
        [
            "git",
            "clone",
            "--no-local",
            "--single-branch",
            "--branch",
            "master",
            str(source),
            str(clone),
        ],
        check=True,
        capture_output=True,
    )
    missing = subprocess.run(
        ["git", "cat-file", "-e", f"{reviewed_commit}^{{commit}}"],
        cwd=clone,
        check=False,
        capture_output=True,
    )

    report = evaluate_change(clone, change.name, strict=True, today=TODAY)

    assert missing.returncode != 0
    assert report.status == "PASS"
    assert report.metadata["reviewed_commit_status"] == "missing"


def test_malformed_change_marker_is_policy_rejection_not_infrastructure(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "malformed-change")
    (change / "design-quality.toml").write_text("[[broken\n", encoding="utf-8")

    report = evaluate_change(repo, "malformed-change", today=TODAY)

    assert report.exit_code == 1
    assert "core.governance.invalid" in _rule_ids(report)


def test_invalid_and_expired_exceptions_do_not_suppress_warning(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    exceptions = """
[[exceptions]]
rule = "structure.catch_all"
owner = "qa"
reason = "Temporary fixture ownership while the domain module is created."
expires = "2026-07-19"
"""
    change = _write_change(repo, "exception-change", exceptions=exceptions)
    marker = change / "design-quality.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            'paths = ["tests/fixture.py"]', 'paths = ["tests/utils.py"]'
        ),
        encoding="utf-8",
    )

    report = evaluate_change(repo, "exception-change", strict=True, today=TODAY)

    assert {item.state for item in report.exceptions} == {"expired"}
    assert "core.exception.invalid" in _rule_ids(report)
    assert any(
        item.rule_id == "structure.catch_all" and not item.suppressed for item in report.findings
    )


def test_parent_preserves_real_invalid_exception_as_quality_failure(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    exceptions = """
[[exceptions]]
rule = "structure.catch_all"
owner = "qa"
reason = "not applicable"
expires = "2026-08-30"
"""
    change = _write_change(repo, "invalid-exception", exceptions=exceptions)
    marker = change / "design-quality.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            'paths = ["tests/fixture.py"]', 'paths = ["tests/utils.py"]'
        ),
        encoding="utf-8",
    )
    report = evaluate_change(repo, change.name, strict=True, today=TODAY)
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": 1,
        "reports": [report.to_dict()],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": 1,
            "not_governed": 0,
            "errors": 0,
        },
    }
    script = f"import json,sys; print({json.dumps(json.dumps(payload))}); sys.exit(1)"

    result = SubprocessExecutor(repo, QualityConfig()).run_step(
        CheckStep(
            "design.invalid-exception",
            "design",
            "real invalid exception report",
            (sys.executable, "-c", script),
            exit_code_kinds=((1, FailureKind.QUALITY), (2, FailureKind.INFRASTRUCTURE)),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    assert report.status == "FAIL"
    assert report.exceptions[0].state == "invalid"
    assert result.failure_kind is FailureKind.QUALITY
    assert result.aggregate_exit_code == 1


@pytest.mark.parametrize("require_governance", (False, True))
def test_parent_preserves_real_marker_missing_state(
    tmp_path: Path, require_governance: bool
) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "marker-missing")
    (change / "design-quality.toml").unlink()
    report = evaluate_change(
        repo,
        change.name,
        strict=True,
        today=TODAY,
        require_governance=require_governance,
    )
    payload = {
        "schema_version": "trade.design.batch.v1",
        "exit_code": report.exit_code,
        "reports": [report.to_dict()],
        "summary": {
            "changes": 1,
            "passed": 0,
            "failed": report.exit_code,
            "not_governed": int(not require_governance),
            "errors": 0,
        },
    }
    script = (
        f"import json,sys; print({json.dumps(json.dumps(payload))}); sys.exit({report.exit_code})"
    )

    result = SubprocessExecutor(repo, QualityConfig()).run_step(
        CheckStep(
            "design.marker-missing",
            "design",
            "real marker missing report",
            (sys.executable, "-c", script),
            exit_code_kinds=((1, FailureKind.QUALITY), (2, FailureKind.INFRASTRUCTURE)),
            structured_output_schema="trade.design.batch.v1",
        )
    )

    if require_governance:
        assert report.governance_status == "REQUIRED_MISSING"
        assert result.failure_kind is FailureKind.QUALITY
        assert result.aggregate_exit_code == 1
    else:
        assert report.status == "NOT_GOVERNED"
        assert result.status is ResultStatus.WARN
        assert result.aggregate_exit_code == 0


def test_valid_exception_remains_visible_and_suppresses_warning(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    exceptions = """
[[exceptions]]
rule = "structure.catch_all"
owner = "qa"
reason = "Temporary fixture ownership while the domain module is created."
expires = 2026-08-30
"""
    change = _write_change(repo, "valid-exception", exceptions=exceptions)
    marker = change / "design-quality.toml"
    marker.write_text(
        marker.read_text(encoding="utf-8").replace(
            'paths = ["tests/fixture.py"]', 'paths = ["tests/utils.py"]'
        ),
        encoding="utf-8",
    )

    report = evaluate_change(repo, "valid-exception", strict=True, today=TODAY)

    assert report.exceptions[0].state == "applied"
    assert any(
        item.rule_id == "structure.catch_all" and item.suppressed for item in report.findings
    )


def test_historical_effective_date_cannot_grant_strict_approval(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_change(repo, "replay-change")

    with pytest.raises(DesignQualityError, match="historical --as-of is diagnostic-only"):
        evaluate_change(
            repo,
            "replay-change",
            strict=True,
            effective_date=date(2026, 7, 19),
            today=TODAY,
        )


def test_snapshot_rejects_symlink_and_oversized_artifact(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "unsafe-change")
    (change / "design.md").unlink()
    (change / "design.md").symlink_to(repo / "design-policy" / "v1.toml")

    with pytest.raises(DesignQualityError, match="unsafe design artifact"):
        evaluate_change(repo, "unsafe-change", today=TODAY)

    (change / "design.md").unlink()
    (change / "design.md").write_text(_design(), encoding="utf-8")
    policy = load_policy(repo)
    tiny = replace(policy, limits=replace(policy.limits, max_file_bytes=8))
    with pytest.raises(DesignQualityError, match="limit is 8"):
        load_snapshots(repo, ("unsafe-change",), tiny)


def test_snapshot_bounds_capability_enumeration_before_sorting(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "too-many-capabilities")
    specs = change / "specs"
    for index in range(128):
        capability = specs / f"capability-{index:03d}"
        capability.mkdir()
        (capability / "spec.md").write_text("Requirement.\n", encoding="utf-8")

    with pytest.raises(DesignQualityError, match="capability count exceeds"):
        load_snapshots(repo, (change.name,), load_policy(repo))


def test_snapshot_verification_detects_inventory_addition(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "inventory-change")
    policy = load_policy(repo)
    snapshot = load_snapshots(repo, (change.name,), policy)[0]
    added = change / "specs" / "added-capability"
    added.mkdir()
    (added / "spec.md").write_text(
        "### Requirement: Added\nRequirement.\n\n#### Scenario: Added\n- **WHEN** added\n- **THEN** fail\n",
        encoding="utf-8",
    )

    with pytest.raises(DesignQualityError, match="inventory changed"):
        verify_snapshot(snapshot, policy)


def test_batch_count_is_checked_before_change_paths(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    policy = load_policy(repo)
    names = tuple(f"change-{index}" for index in range(101))

    with pytest.raises(DesignQualityError, match="Batch has 101 changes"):
        evaluate_changes(repo, names, policy=policy, today=TODAY)


@pytest.mark.parametrize("change_count", (2, 10, 100))
def test_live_batch_evaluation_scales_to_policy_limit(tmp_path: Path, change_count: int) -> None:
    repo = _repo(tmp_path)
    names = tuple(f"batch-change-{index}" for index in range(change_count))
    for name in names:
        _write_change(repo, name)

    reports = evaluate_changes(repo, names, today=TODAY)

    assert len(reports) == change_count
    assert all(report.exit_code == 0 for report in reports)


def test_task_checkbox_completion_does_not_stale_artifact_digest(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    change = _write_change(repo, "digest-change")
    policy = load_policy(repo)
    before = load_snapshots(repo, ("digest-change",), policy)[0].artifact_digest
    tasks = change / "tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("[ ]", "[x]"), encoding="utf-8")
    after = load_snapshots(repo, ("digest-change",), policy)[0].artifact_digest

    assert before == after
