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


@pytest.fixture(autouse=True, scope="session")
def hermetic_settings():
    """Ignore any .env the developer keeps locally.

    Settings would otherwise read real provider keys from disk, so results would
    differ between a machine that has run the app and a clean checkout.
    """
    import automatron_core as core

    core.Settings.model_config["env_file"] = None
    core.reset_settings_cache()
    yield
    core.reset_settings_cache()


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return ROOT


@pytest.fixture(scope="session")
def build_dir() -> pathlib.Path:
    return BUILD_DIR
