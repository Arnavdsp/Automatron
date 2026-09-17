"""CDM parsing, against the bundled synthetic series."""

import automatron_core as core
import automatron_space as space


def parsed(sample="cdm_high_risk"):
    return space.parse_cdm.invoke({"sample_name": sample})


def test_every_bundled_series_parses():
    for sample in ("cdm_low_risk", "cdm_high_risk", "cdm_jumpy_stale"):
        result = parsed(sample)
        assert result["count"] == 4, sample
        assert not result["problems"], sample


def test_messages_come_back_oldest_first():
    stamps = [m["created_utc"] for m in parsed()["messages"]]
    assert stamps == sorted(stamps)


def test_required_fields_are_extracted():
    message = parsed()["messages"][-1]
    assert message["tca_utc"].startswith("2026-03-03")
    assert message["miss_distance_m"] > 0
    assert len(message["rel_pos_rtn_m"]) == 3
    assert len(message["rel_vel_rtn_mps"]) == 3


def test_both_object_blocks_are_separated():
    message = parsed()["messages"][0]
    assert message["primary"]["designator"] == "46001"
    assert message["secondary"]["designator"] == "27831"
    assert message["primary"]["covariance_m2"] != message["secondary"]["covariance_m2"]


def test_covariance_is_rebuilt_symmetrically():
    covariance = parsed()["messages"][0]["primary"]["covariance_m2"]
    for i in range(3):
        for j in range(3):
            assert covariance[i][j] == covariance[j][i]


def test_a_message_missing_its_objects_is_reported_not_raised():
    result = space.parse_cdm.invoke({"text": "CCSDS_CDM_VERS = 1.0\nTCA = 2026-01-01T00:00:00\n"})
    assert result["count"] == 0
    assert result["problems"]


def test_an_unknown_sample_name_is_an_error_not_an_exception():
    assert "error" in space.parse_cdm.invoke({"sample_name": "does_not_exist"})


def test_parsing_is_stable_across_calls():
    assert parsed()["messages"] == parsed()["messages"]


def test_the_samples_carry_a_synthetic_notice():
    path = space.SAMPLE_DIR / "cdm_high_risk.cdm"
    assert "Synthetic" in path.read_text(encoding="utf-8")
    assert core is not None
