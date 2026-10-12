"""Shared pytest configuration for the integration test suites."""

import datetime
import os
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).parent.parent.resolve()


def pytest_addoption(parser):
    parser.addoption('--output-dir', default=None,
                     help="Directory for test artifacts (default: _test_runs/<timestamp>)")


@pytest.fixture(scope='session')
def output_base(request):
    """Root directory for test artifacts."""
    path = request.config.getoption('--output-dir')
    if path is None:
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        path = REPO_DIR / '_test_runs' / ts
    os.makedirs(path, exist_ok=True)
    return str(path)
