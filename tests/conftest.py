"""Shared test setup: build the notebook modules once and import them offline."""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "automatron_build"

# Every test runs without provider keys or network access.
os.environ.setdefault("AUTOMATRON_FAKE_LLM", "1")


def pytest_configure(config):
    subprocess.run(
        [sys.executable, "scripts/build_notebooks.py"],
        check=True,
        cwd=ROOT,
        capture_output=True,
    )
    if str(BUILD_DIR) not in sys.path:
        sys.path.insert(0, str(BUILD_DIR))


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return ROOT


@pytest.fixture(scope="session")
def build_dir() -> pathlib.Path:
    return BUILD_DIR
