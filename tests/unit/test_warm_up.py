"""Startup pays first-use costs, and no run reads the knowledge base half-seeded."""

import threading
import time

import pytest

import automatron_core as core
from tests import testsector


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOMATRON_FAKE_LLM", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "empty-data"))
    core.reset_settings_cache()
    core.reset_rag_cache()
    core.reset_knowledge_readiness()
    testsector.install()
    yield
    core.reset_knowledge_readiness()
    core.clear_registry()
    try:
        core.get_qdrant().close()
    except Exception:
        pass
    core.reset_rag_cache()
    core.reset_settings_cache()


def test_warm_up_seeds_and_imports(env):
    timings = core.warm_up()
    assert "seed" in timings and "import sklearn.ensemble" in timings


def test_a_search_during_seeding_waits_for_it(env, monkeypatch):
    """The first run after a restart used to search an empty collection and get a
    brief written without references. Now it waits for the seed to land."""
    seeding_started = threading.Event()
    release = threading.Event()

    def slow_seed(force=False):
        seeding_started.set()
        release.wait(5)
        return {}

    monkeypatch.setattr(core, "seed_knowledge", slow_seed)
    warmer = threading.Thread(target=core.warm_up)
    warmer.start()
    seeding_started.wait(5)
    finished = []
    searcher = threading.Thread(target=lambda: finished.append(core.wait_for_knowledge()))
    searcher.start()
    time.sleep(0.3)
    assert not finished, "the search went ahead while seeding was still running"
    release.set()
    searcher.join(5)
    warmer.join(5)
    assert finished == [True]


def test_without_seeding_under_way_nothing_waits(env):
    started = time.perf_counter()
    assert core.wait_for_knowledge() is True
    assert time.perf_counter() - started < 0.1


def test_a_failed_seed_still_releases_waiting_searches(env, monkeypatch):
    def broken_seed(force=False):
        raise RuntimeError("qdrant unreachable")

    monkeypatch.setattr(core, "seed_knowledge", broken_seed)
    core.warm_up()
    assert core.wait_for_knowledge() is True


def test_every_search_checks_readiness_first(env, monkeypatch):
    asked = []
    monkeypatch.setattr(core, "wait_for_knowledge", lambda: asked.append(True) or True)
    core.search_knowledge("anything", "space", k=1)
    assert asked == [True]
