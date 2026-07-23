from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from trade_py.devtools.design_quality.errors import DesignQualityError
from trade_py.devtools.design_quality.models import Severity
from trade_py.devtools.design_quality.policy import load_policy

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repository_design_policy_is_immutable_typed_and_complete() -> None:
    policy = load_policy(REPO_ROOT)

    assert policy.policy_version == "v1"
    assert policy.digest.startswith("sha256:")
    assert policy.limits.max_changes_per_batch == 100
    assert policy.limits.max_total_bytes_per_batch == 16 * 1024 * 1024
    assert set(policy.required_root_files) == {
        ".openspec.yaml",
        "design-quality.toml",
        "proposal.md",
        "design.md",
        "tasks.md",
    }
    assert policy.minimum_spec_files == 1
    assert set(policy.required_roles) == {
        "reliability",
        "performance",
        "architecture",
        "data_quality",
        "observability",
        "news_future",
    }
    assert len({item.rule_id for item in policy.rules}) == len(policy.rules)
    assert all(not item.suppressible for item in policy.rules if item.severity is Severity.BLOCKER)
    assert all(
        item.finding_rule and item.required_evidence
        for item in policy.profiles
        if item.name != "core"
    )
    external = next(item for item in policy.profiles if item.name == "external_event")
    assert set(external.required_evidence) == {
        "event_time",
        "publication_time",
        "first_seen_time",
        "available_time",
        "revision_time",
        "timestamp_confidence",
        "source_identity",
        "provenance",
        "licensing",
        "availability_states",
        "quota",
        "cost",
        "concurrency",
        "retry_classification",
        "circuit_breaker",
        "bounded_queue_backpressure",
        "idempotency",
        "poison_handling",
        "dlq",
        "replay",
        "correction",
        "tombstone",
        "finality",
        "degraded_mode",
        "unavailable_fallback",
    }
    assert set(external.evidence_schema) == set(external.required_evidence)
    assert external.evidence_schema["source_identity"].kind == "table"
    assert external.evidence_schema["source_identity"].fields["source_id"].kind == "identifier"
    assert external.evidence_schema["provenance"].fields["source_id"].kind == "identifier"
    assert external.evidence_schema["idempotency"].kind == "table"
    assert external.evidence_schema["idempotency"].fields["enabled"].equals is True
    migration = next(item for item in policy.profiles if item.name == "migration")
    assert migration.impacts == ("schema_migration",)
    assert {"compatibility_modes", "dual_read_write"} <= set(migration.evidence_schema)


def test_policy_rejects_duplicate_rule_ids(tmp_path: Path) -> None:
    target = tmp_path / "design-policy"
    shutil.copytree(REPO_ROOT / "design-policy", target)
    path = target / "v1.toml"
    text = path.read_text(encoding="utf-8")
    duplicate = text[text.index("[[rules]]") :]
    path.write_text(
        f"{text}\n{duplicate.split('[[rules]]', 2)[1].join(['[[rules]]', ''])}", encoding="utf-8"
    )

    with pytest.raises(DesignQualityError):
        load_policy(tmp_path)


def test_policy_rejects_symlinked_version(tmp_path: Path) -> None:
    target = tmp_path / "design-policy"
    target.mkdir()
    (target / "real.toml").write_text("schema_version = 1\npolicy_version = 'v1'\n")
    (target / "v1.toml").symlink_to(target / "real.toml")

    with pytest.raises(DesignQualityError, match="Missing immutable design policy"):
        load_policy(tmp_path)


def test_policy_rejects_symlinked_policy_directory(tmp_path: Path) -> None:
    real = tmp_path / "real-policy"
    shutil.copytree(REPO_ROOT / "design-policy", real)
    (tmp_path / "design-policy").symlink_to(real, target_is_directory=True)

    with pytest.raises(DesignQualityError, match="Missing immutable design policy"):
        load_policy(tmp_path)


def test_v1_policy_rejects_unimplemented_spec_pattern(tmp_path: Path) -> None:
    target = tmp_path / "design-policy"
    shutil.copytree(REPO_ROOT / "design-policy", target)
    path = target / "v1.toml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'spec_pattern = "specs/*/spec.md"', 'spec_pattern = "requirements/*.md"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(DesignQualityError, match="spec_pattern must be exactly"):
        load_policy(tmp_path)
