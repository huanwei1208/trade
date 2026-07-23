"""Shared fixtures for observatory tests."""
from __future__ import annotations

import pytest

from tests.observatory.fixtures import build_observatory_fixture


@pytest.fixture()
def observatory_data_root(tmp_path):
    """A frozen synthetic data root with the full fixture set (read-only for tests)."""

    return build_observatory_fixture(tmp_path / "data")
