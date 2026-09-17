"""The audit log is append-only and hash-chained, so an edited entry is detectable."""

import json

import pytest

import automatron_core as core


@pytest.fixture
def audit_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path))
    core.reset_settings_cache()
    yield tmp_path
    core.reset_settings_cache()


def entry(run_id="r1", action="approve", reviewer="Arnav"):
    return {
        "run_id": run_id,
        "sector": "space",
        "workflow_id": "space.conjunction_triage",
        "action": action,
        "reviewer": reviewer,
        "notes": "",
        "brief_sha256": "a" * 64,
        "providers_used": ["groq:openai/gpt-oss-20b"],
    }


class TestAppend:
    def test_the_first_entry_follows_the_genesis_hash(self, audit_dir):
        record = core.append_audit(entry())
        assert record["prev_hash"] == core.GENESIS_HASH
        assert len(record["hash"]) == 64
        assert record["ts"]

    def test_each_entry_commits_to_the_one_before(self, audit_dir):
        first = core.append_audit(entry("r1"))
        second = core.append_audit(entry("r2"))
        assert second["prev_hash"] == first["hash"]

    def test_entries_are_written_one_per_line(self, audit_dir):
        core.append_audit(entry("r1"))
        core.append_audit(entry("r2"))
        lines = (audit_dir / core.AUDIT_FILENAME).read_text().strip().splitlines()
        assert len(lines) == 2
        assert all(json.loads(line)["hash"] for line in lines)


class TestRead:
    def test_reading_an_absent_log_is_empty_not_an_error(self, audit_dir):
        assert core.read_audit() == []

    def test_entries_can_be_filtered_by_run(self, audit_dir):
        core.append_audit(entry("r1"))
        core.append_audit(entry("r2"))
        assert [e["run_id"] for e in core.read_audit("r2")] == ["r2"]

    def test_a_corrupt_line_is_skipped_rather_than_fatal(self, audit_dir):
        core.append_audit(entry("r1"))
        with (audit_dir / core.AUDIT_FILENAME).open("a") as handle:
            handle.write("this is not json\n")
        assert len(core.read_audit()) == 1


class TestChainVerification:
    def test_an_untouched_chain_verifies(self, audit_dir):
        for run in ("r1", "r2", "r3"):
            core.append_audit(entry(run))
        valid, problems = core.verify_audit_chain()
        assert valid, problems

    def test_an_empty_chain_verifies(self, audit_dir):
        assert core.verify_audit_chain()[0] is True

    def test_editing_a_field_is_detected(self, audit_dir):
        core.append_audit(entry("r1"))
        core.append_audit(entry("r2"))

        entries = core.read_audit()
        entries[0]["reviewer"] = "Someone Else"
        valid, problems = core.verify_audit_chain(entries)
        assert not valid
        assert any("altered" in p for p in problems)

    def test_removing_an_entry_is_detected(self, audit_dir):
        for run in ("r1", "r2", "r3"):
            core.append_audit(entry(run))
        entries = core.read_audit()
        del entries[1]
        valid, problems = core.verify_audit_chain(entries)
        assert not valid
        assert any("does not follow" in p for p in problems)

    def test_reordering_entries_is_detected(self, audit_dir):
        core.append_audit(entry("r1"))
        core.append_audit(entry("r2"))
        entries = core.read_audit()
        valid, _ = core.verify_audit_chain([entries[1], entries[0]])
        assert not valid

    def test_a_rewritten_chain_still_fails_on_the_first_link(self, audit_dir):
        """Recomputing one entry's hash does not repair the chain after it."""
        core.append_audit(entry("r1"))
        core.append_audit(entry("r2"))
        entries = core.read_audit()
        entries[0]["reviewer"] = "Someone Else"
        entries[0]["hash"] = core._entry_hash(entries[0]["prev_hash"], entries[0])

        valid, problems = core.verify_audit_chain(entries)
        assert not valid
        assert any("does not follow" in p for p in problems)
