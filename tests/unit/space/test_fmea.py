"""Telemetry analysis and failure-mode ranking."""

import automatron_space as space


def loaded(sample="telemetry_rw_fault"):
    return space.load_telemetry.invoke({"sample_name": sample})


class TestTelemetry:
    def test_a_bundled_scenario_loads_with_its_channels(self):
        result = loaded()
        assert result["rows"] == 2 * 24 * 60
        assert {"battery_v", "rw1_current_a", "heater_on"} <= set(result["channels"])
        assert result["channels"]["battery_v"]["unit"] == "V"

    def test_an_unknown_sample_is_an_error_not_an_exception(self):
        assert "error" in space.load_telemetry.invoke({"sample_name": "nope"})

    def test_the_wheel_scenario_shows_current_and_temperature_rising(self):
        loaded("telemetry_rw_fault")
        found = space.detect_anomalies.invoke({})
        directions = {f["channel"]: f["direction"] for f in found["findings"]}
        assert directions.get("rw1_current_a") == "up"
        assert directions.get("rw1_temp_c") == "up"

    def test_the_wheel_scenario_yields_the_expected_symptoms(self):
        loaded("telemetry_rw_fault")
        symptoms = space.detect_anomalies.invoke({})["symptoms"]
        assert "rw_current_rise" in symptoms
        assert "rw_temp_rise" in symptoms

    def test_correlation_reports_direction_of_lead_or_lag(self):
        loaded("telemetry_rw_fault")
        result = space.correlate_channels.invoke({"target": "rw1_current_a"})
        assert result["top"]
        assert all("relationship" in row for row in result["top"])

    def test_correlating_an_unknown_channel_is_an_error(self):
        loaded()
        assert "error" in space.correlate_channels.invoke({"target": "not_a_channel"})

    def test_the_timeline_picks_up_state_changes(self):
        loaded("telemetry_battery_eclipse.csv")
        timeline = space.build_timeline.invoke({})
        assert timeline["events"]
        assert any(
            "heater_on" in event["event"] or "eclipse" in event["event"]
            for event in timeline["events"]
        )

    def test_tools_fall_back_to_the_most_recent_dataset(self):
        loaded("telemetry_rw_fault")
        assert "error" not in space.detect_anomalies.invoke({"dataset_id": ""})


class TestHypothesisRanking:
    def test_wheel_symptoms_rank_bearing_degradation_first(self):
        ranked = space.rank_hypotheses.invoke(
            {"symptoms": ["rw_current_rise", "rw_temp_rise", "rw_speed_oscillation"]}
        )["ranked"]
        assert ranked[0]["id"] == "FM-RW-BEARING"
        assert ranked[0]["score"] > 0

    def test_the_heater_symptoms_rank_the_stuck_heater(self):
        ranked = space.rank_hypotheses.invoke(
            {
                "symptoms": [
                    "bus_current_rise",
                    "battery_voltage_sag",
                    "heater_on_during_eclipse_exit",
                ]
            }
        )["ranked"]
        assert ranked[0]["id"] == "FM-HEATER-STUCK"

    def test_unmatched_symptoms_are_reported_for_each_candidate(self):
        ranked = space.rank_hypotheses.invoke({"symptoms": ["rw_current_rise"]})["ranked"]
        assert any(mode["unmatched_symptoms"] for mode in ranked)

    def test_every_candidate_carries_diagnostics_and_a_safety_note(self):
        for mode in space.rank_hypotheses.invoke({"symptoms": ["rw_current_rise"]})["ranked"]:
            assert mode["diagnostics"]
            assert mode["safety_note"]

    def test_symptoms_matching_nothing_rank_nothing(self):
        assert space.rank_hypotheses.invoke({"symptoms": ["unrelated_symptom"]})["ranked"] == []

    def test_ranking_is_stable_for_the_same_input(self):
        first = space.rank_hypotheses.invoke({"symptoms": ["rw_current_rise", "rw_temp_rise"]})
        second = space.rank_hypotheses.invoke({"symptoms": ["rw_current_rise", "rw_temp_rise"]})
        assert first["ranked"] == second["ranked"]

    def test_the_table_is_reported_as_considered(self):
        result = space.rank_hypotheses.invoke({"symptoms": ["rw_current_rise"]})
        assert result["considered"] == 10
