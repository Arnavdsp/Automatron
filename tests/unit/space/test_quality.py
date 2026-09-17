"""Trend, covariance quality and classification."""

import automatron_space as space


def series(sample):
    return space.parse_cdm.invoke({"sample_name": sample})["messages"]


class TestTrend:
    def test_the_high_risk_series_rises_through_the_red_threshold(self):
        trend = space.pc_trend.invoke({"sample_name": "cdm_high_risk"})
        assert trend["direction"] == "rising"
        assert trend["latest_pc"] >= space.PC_RED
        assert any(
            c["threshold"] == "red" and c["direction"] == "up" for c in trend["threshold_crossings"]
        )

    def test_the_low_risk_series_falls_away(self):
        trend = space.pc_trend.invoke({"sample_name": "cdm_low_risk"})
        assert trend["direction"] == "falling"
        assert trend["latest_pc"] < space.PC_YELLOW

    def test_an_order_of_magnitude_jump_is_reported(self):
        trend = space.pc_trend.invoke({"sample_name": "cdm_jumpy_stale"})
        assert trend["jumps"], "the jumpy series should record a jump"
        assert any(j["direction"] == "increase" for j in trend["jumps"])

    def test_each_point_is_reported_in_scientific_notation(self):
        for point in space.pc_trend.invoke({"sample_name": "cdm_low_risk"})["points"]:
            assert "e" in point["pc_scientific"]

    def test_an_empty_series_is_an_error_not_an_exception(self):
        assert "error" in space.pc_trend.invoke({"cdm_series": [], "sample_name": "nope"})


class TestCovarianceQuality:
    def test_stale_tracking_is_flagged(self):
        quality = space.covariance_quality.invoke({"sample_name": "cdm_jumpy_stale"})
        assert any("days old" in issue for issue in quality["issues"])
        assert quality["per_object"]["secondary"]["od_age_days"] > space.OD_AGE_WARN_DAYS

    def test_fresh_tracking_is_not_flagged_as_stale(self):
        quality = space.covariance_quality.invoke({"sample_name": "cdm_high_risk"})
        assert not any("days old" in issue for issue in quality["issues"])

    def test_dilution_is_detected_on_the_inflated_series(self):
        quality = space.covariance_quality.invoke({"sample_name": "cdm_jumpy_stale"})
        assert quality["dilution_warning"] is True
        assert quality["max_pc_over_scales"] > quality["current_pc"]

    def test_a_well_tracked_conjunction_is_not_called_diluted(self):
        quality = space.covariance_quality.invoke({"sample_name": "cdm_high_risk"})
        assert quality["dilution_warning"] is False

    def test_scaling_the_covariance_changes_the_probability(self):
        quality = space.covariance_quality.invoke({"sample_name": "cdm_high_risk"})
        values = {k: float(v) for k, v in quality["pc_by_scale"].items()}
        assert len(set(values.values())) > 1

    def test_positive_definiteness_is_checked(self):
        message = series("cdm_high_risk")[-1]
        message["primary"]["covariance_m2"] = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        quality = space.covariance_quality.invoke({"cdm": message})
        assert any("positive definite" in issue for issue in quality["issues"])


class TestClassification:
    def test_the_high_risk_sample_classifies_red(self):
        result = space.classify_conjunction.invoke({"sample_name": "cdm_high_risk"})
        assert result["level"] == "RED"
        assert result["reasons"]

    def test_the_low_risk_sample_classifies_green(self):
        result = space.classify_conjunction.invoke({"sample_name": "cdm_low_risk"})
        assert result["level"] == "GREEN"

    def test_dilution_outranks_a_low_probability(self):
        result = space.classify_conjunction.invoke({"sample_name": "cdm_jumpy_stale"})
        assert result["level"] == "INSUFFICIENT_DATA"
        assert any("diluted" in reason for reason in result["reasons"])

    def test_a_probability_between_thresholds_is_yellow(self):
        result = space.classify_conjunction.invoke({"pc": 5e-6})
        assert result["level"] == "YELLOW"

    def test_operator_policy_overrides_the_defaults(self):
        strict = space.classify_conjunction.invoke(
            {"pc": 5e-6, "policy": {"pc_red": 1e-6, "pc_yellow": 1e-9}}
        )
        assert strict["level"] == "RED"
        assert strict["thresholds_used"]["pc_red"] == "1e-06"

    def test_thresholds_are_reported_as_policy(self):
        result = space.classify_conjunction.invoke({"pc": 1e-9})
        assert "pc_red" in result["thresholds_used"]
