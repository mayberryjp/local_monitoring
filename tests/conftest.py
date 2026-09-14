"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from webtest import TestApp

from local_monitoring.api.app import create_app


@pytest.fixture()
def client() -> Iterator[TestApp]:
    yield TestApp(create_app())
