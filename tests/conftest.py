from __future__ import annotations

import pytest

from cmip.extract.cochilco import extract_annex_tables
from cmip.validate import normalize_projects


@pytest.fixture(scope="session")
def annex_tables():
    return extract_annex_tables()


@pytest.fixture(scope="session")
def projects(annex_tables):
    return normalize_projects(annex_tables[1])

