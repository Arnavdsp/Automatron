"""Static review of strategy code, and proof that reviewing it never runs it."""

import pytest

import automatron_quant as quant


@pytest.fixture(scope="module", autouse=True)
def samples():
    quant.ensure_samples()


def test_the_risky_sample_trips_every_rule():
    """The sample exists to exercise the whole rule set, so all ten must fire."""
    result = quant.static_scan.invoke(
        {"sample_name": "strategy_risky", "deployment_target": "live"})
    found = {finding["rule_id"] for finding in result["findings"]}
    assert found == {f"QC-{n:03d}" for n in range(1, 11)}
    assert all(finding["line"] > 0 for finding in result["findings"])


def test_the_clean_sample_trips_none():
    result = quant.static_scan.invoke(
        {"sample_name": "strategy_clean", "deployment_target": "live"})
    assert result["findings"] == []
    mapped = quant.map_findings_to_controls.invoke(
        {"sample_name": "strategy_clean", "deployment_target": "live"})
    assert mapped["level"] == "NO_ISSUES_FOUND"


def test_scanning_a_file_never_executes_it(tmp_path):
    """The security property this whole workflow rests on.

    The file below would create a sentinel on import or exec. After scanning it,
    that sentinel must not exist, and the scan must still have parsed the file.
    """
    sentinel = tmp_path / "executed.marker"
    hostile = tmp_path / "hostile_strategy.py.txt"
    hostile.write_text(
        "import pathlib\n"
        f"pathlib.Path({str(sentinel)!r}).write_text('the file was executed')\n"
        "\n"
        "def build_signal(prices):\n"
        "    return prices\n",
        encoding="utf-8",
    )

    result = quant.static_scan.invoke({"file_path": str(hostile)})
    structure = quant.extract_structure.invoke({"file_path": str(hostile)})

    assert not sentinel.exists(), "scanning the file executed it"
    assert result["parsed"] is True
    assert result["executed"] is False
    assert structure["executed"] is False
    assert [f["name"] for f in structure["functions"]] == ["build_signal"]


def test_a_file_that_does_not_parse_is_reported_not_raised(tmp_path):
    broken = tmp_path / "broken.py.txt"
    broken.write_text("def build_signal(  :\n    return\n", encoding="utf-8")
    result = quant.static_scan.invoke({"file_path": str(broken)})
    assert result["parsed"] is False
    assert "does not parse" in result["error"]


def test_a_file_above_the_size_limit_is_refused(tmp_path):
    large = tmp_path / "large.py.txt"
    large.write_text("x = 1\n" * 60_000, encoding="utf-8")
    result = quant.static_scan.invoke({"file_path": str(large)})
    assert "error" in result and "200 KB" in result["error"]


def test_findings_that_block_depend_on_where_the_code_is_going():
    """Some controls only matter for live deployment; the level must say which."""
    live = quant.map_findings_to_controls.invoke(
        {"sample_name": "strategy_risky", "deployment_target": "live"})
    paper = quant.map_findings_to_controls.invoke(
        {"sample_name": "strategy_risky", "deployment_target": "paper"})
    assert live["blocking_count"] > paper["blocking_count"]
    assert live["deployment_target"] == "live"
    assert paper["deployment_target"] == "paper"
    assert live["level"] == "BLOCKING_ISSUES"


def test_a_credential_literal_is_never_echoed_back(tmp_path):
    """Reporting the finding must not repeat the secret into the brief or the log."""
    leaky = tmp_path / "leaky.py.txt"
    secret = "sk_live_" + "a1b2c3d4e5f6" * 2
    leaky.write_text(f'API_KEY = "{secret}"\n\ndef go():\n    return API_KEY\n', encoding="utf-8")

    result = quant.static_scan.invoke({"file_path": str(leaky)})
    structure = quant.extract_structure.invoke({"file_path": str(leaky)})

    assert any(f["rule_id"] == "QC-001" for f in result["findings"])
    assert secret not in repr(result)
    assert secret not in repr(structure)
    assert structure["module_constants"][0]["value"] == "[redacted]"


def test_every_rule_maps_to_a_control_theme_that_exists():
    rules = quant.load_code_controls()
    for rule_id, spec in rules["rules"].items():
        assert spec["theme"] in rules["control_themes"], rule_id
        assert spec["severity"] in {"low", "medium", "high"}
        assert set(spec["blocking"]) <= {"paper", "live"}


def test_the_result_says_static_checks_are_not_a_full_review():
    result = quant.static_scan.invoke({"sample_name": "strategy_clean"})
    assert "not that the strategy is safe to deploy" in result["disclaimer"]
