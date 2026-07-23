from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / ".codex" / "skills" / "design-quality"


def _text(relative: str) -> str:
    return (SKILL_ROOT / relative).read_text(encoding="utf-8")


def test_design_skill_has_complete_progressive_workflow() -> None:
    skill = _text("SKILL.md")

    assert "TODO" not in skill
    assert "$code-quality" in skill
    assert "./trade dev design-check <change>" in skill
    assert "./trade dev design-check <change> --strict" in skill
    assert ".agents/skills/review-this/SKILL.md" in skill
    for reference in ("workflow.md", "brief.md", "profiles.md"):
        assert f"references/{reference}" in skill
        assert (SKILL_ROOT / "references" / reference).is_file()


def test_design_skill_covers_every_policy_impact_and_brief_section() -> None:
    profiles = _text("references/profiles.md")
    brief = _text("references/brief.md")
    policy = (REPO_ROOT / "design-policy" / "v1.toml").read_text(encoding="utf-8")

    for impact in (
        "public_contract",
        "persistent_write",
        "schema_migration",
        "point_in_time",
        "predictive_model",
        "external_event_data",
        "runtime_concurrency",
    ):
        assert f'"{impact}"' in policy
        assert impact in profiles
    for heading in (
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
    ):
        assert f"## {heading}" in brief


def test_repository_governance_routes_design_before_code() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    code_skill = _text("../code-quality/SKILL.md")
    openspec = (REPO_ROOT / "openspec" / "config.yaml").read_text(encoding="utf-8")

    assert ".codex/skills/design-quality/SKILL.md" in agents
    assert "Do not begin code until" in agents
    assert "design-quality gate precedes" in agents
    assert "use `$design-quality` first" in code_skill
    assert "six-role consensus evidence" in openspec


def test_skill_metadata_is_discoverable() -> None:
    metadata = _text("agents/openai.yaml")

    assert 'display_name: "Design Quality Guard"' in metadata
    assert 'default_prompt: "Use $design-quality' in metadata
