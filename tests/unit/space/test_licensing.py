"""Mission validation, requirement checklists and spectrum overlap."""

import automatron_space as space


class TestProfileValidation:
    def test_a_bundled_mission_validates(self):
        result = space.validate_mission_profile.invoke({"sample_name": "mission_eo_leo"})
        assert result["valid"] is True
        assert result["missing_fields"] == []
        assert result["mission_name"] == "Northlight-1"

    def test_missing_fields_are_named(self):
        result = space.validate_mission_profile.invoke({"profile": {"mission_name": "X"}})
        assert result["valid"] is False
        assert "operator" in result["missing_fields"]
        assert "orbit.altitude_km" in result["missing_fields"]

    def test_an_implausible_orbit_is_a_warning_not_a_rejection(self):
        result = space.validate_mission_profile.invoke(
            {
                "profile": {
                    "mission_name": "X",
                    "operator": "Y",
                    "activity_type": "communications",
                    "orbit": {"altitude_km": 12, "inclination_deg": 50},
                    "frequencies": [
                        {
                            "band": "S",
                            "center_mhz": 2200.0,
                            "bandwidth_mhz": 4.0,
                            "direction": "downlink",
                        }
                    ],
                }
            }
        )
        assert any("altitude" in w for w in result["warnings"])

    def test_an_unknown_activity_type_is_warned_about(self):
        result = space.validate_mission_profile.invoke(
            {
                "profile": {
                    "mission_name": "X",
                    "operator": "Y",
                    "activity_type": "time_travel",
                    "orbit": {"altitude_km": 500},
                    "frequencies": [],
                }
            }
        )
        assert any("activity_type" in w for w in result["warnings"])


class TestChecklist:
    def test_earth_observation_covers_the_expected_frameworks(self):
        result = space.requirements_checklist.invoke({"activity_type": "earth_observation"})
        assert "fcc_space_station" in result["frameworks"]
        assert "itu_filing" in result["frameworks"]
        assert result["item_count"] > 10
        assert result["no_established_framework"] is False

    def test_a_novel_activity_is_flagged_for_counsel(self):
        result = space.requirements_checklist.invoke({"activity_type": "in_space_servicing"})
        assert result["no_established_framework"] is True
        assert "counsel" in result["counsel_note"].lower()

    def test_every_item_names_its_authority_and_reference(self):
        for item in space.requirements_checklist.invoke({"activity_type": "communications"})[
            "items"
        ]:
            assert item["authority"]
            assert item["reference"]
            assert item["status"] == "not_assessed"

    def test_an_unknown_activity_lists_what_is_known(self):
        result = space.requirements_checklist.invoke({"activity_type": "teleportation"})
        assert "error" in result
        assert "earth_observation" in result["known"]


class TestSpectrumOverlap:
    def test_overlap_uses_occupied_bandwidth_not_the_centre_frequency(self):
        """Centres 150 MHz apart do not overlap; their occupied bands do."""
        result = space.find_affected_operators.invoke(
            {
                "frequencies": [
                    {
                        "band": "Ku",
                        "center_mhz": 11450.0,
                        "bandwidth_mhz": 250.0,
                        "direction": "downlink",
                    }
                ],
                "orbit": {"altitude_km": 550},
            }
        )
        assert result["party_count"] >= 1
        assert any(m["satellite"] == "HARBOUR-1" for m in result["matches"])

    def test_a_clear_band_finds_nobody(self):
        result = space.find_affected_operators.invoke(
            {
                "frequencies": [
                    {
                        "band": "L",
                        "center_mhz": 1200.0,
                        "bandwidth_mhz": 5.0,
                        "direction": "downlink",
                    }
                ],
            }
        )
        assert result["matches"] == []
        assert result["party_count"] == 0

    def test_the_orbital_regime_is_reported_per_match(self):
        result = space.find_affected_operators.invoke(
            {
                "frequencies": [
                    {
                        "band": "X",
                        "center_mhz": 8200.0,
                        "bandwidth_mhz": 300.0,
                        "direction": "downlink",
                    }
                ],
                "orbit": {"altitude_km": 610},
            }
        )
        assert result["matches"]
        assert any(m["same_orbital_regime"] for m in result["matches"])

    def test_a_malformed_frequency_entry_is_skipped_not_fatal(self):
        result = space.find_affected_operators.invoke(
            {
                "frequencies": [
                    {"band": "X"},
                    {"band": "Ku", "center_mhz": 11450.0, "bandwidth_mhz": 250.0},
                ],
            }
        )
        assert result["party_count"] >= 1


class TestDraftingAndTimeline:
    def test_a_letter_is_marked_draft_and_carries_placeholders(self):
        result = space.draft_coordination_letter.invoke(
            {
                "party": "Northstar Imaging",
                "overlaps": [
                    {
                        "band": "X",
                        "proposed_mhz": "8050.0-8350.0",
                        "satellite": "NORTHSTAR-A",
                        "registered_mhz": "7962.5-8337.5",
                        "overlap_mhz": 287.5,
                    }
                ],
                "mission": {"mission_name": "Northlight-1", "operator": "Northlight Imaging"},
            }
        )
        assert result["body"].startswith("DRAFT")
        assert "Not for sending" in result["body"]
        assert result["placeholders"]

    def test_a_letter_without_details_still_drafts_with_placeholders(self):
        result = space.draft_coordination_letter.invoke({"party": "Someone"})
        assert "[MISSION NAME]" in result["body"]
        assert "[OVERLAP DETAILS]" in result["body"]

    def test_the_timeline_names_a_critical_path_and_labels_itself_indicative(self):
        checklist = space.requirements_checklist.invoke({"activity_type": "earth_observation"})
        result = space.estimate_timeline.invoke({"checklist": checklist})
        assert result["critical_path"] == "itu_filing"
        assert "Indicative" in result["note"]
        assert result["per_framework"]
