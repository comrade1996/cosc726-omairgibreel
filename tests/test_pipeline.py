"""Mapper, validator, completeness and dataset invariants (no MCP)."""

import copy
import json
from collections import Counter

import pytest

from project.completeness import check_completeness
from project.dataset import all_cases, load_case, synthea_bundle
from project.mapper import bundle_facts, map_case, resources
from project.validator import validate_bundle

CASES = all_cases()


def bundle_for(case):
    return map_case(case, synthea_bundle(case["synthea_patient_id"]))


def test_dataset_shape():
    assert len(CASES) == 40
    assert Counter(c["kind"] for c in CASES) == {"normal": 28, "adversarial": 12}
    assert len({c["synthea_patient_id"] for c in CASES}) == 20
    for c in CASES:
        assert {"expected_missing", "expected_stop", "permitted_tools", "expected_facts"} <= set(c["labels"])


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_mapping_preserves_every_source_fact(case):
    got = Counter(json.dumps(f, sort_keys=True) for f in bundle_facts(bundle_for(case)))
    exp = Counter(json.dumps(f, sort_keys=True) for f in case["labels"]["expected_facts"])
    assert got == exp


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_completeness_matches_labels(case):
    assert sorted(check_completeness(bundle_for(case))["missing"]) == sorted(case["labels"]["expected_missing"])


@pytest.mark.parametrize("case", CASES, ids=[c["case_id"] for c in CASES])
def test_no_structural_errors(case):
    v = validate_bundle(bundle_for(case), case["case_clock"])
    assert not [i for i in v["issues"] if i["code"] == "STRUCTURE"], v["issues"]


def test_structural_validation_is_not_a_no_op():
    case = load_case("AMB-001")
    b = bundle_for(case)
    obs = next(r for _, r in resources(b, "Observation"))
    obs["status"] = "definitely-not-a-status"
    obs["valueQuantity"] = {"value": "abc"}
    codes = {i["code"] for i in validate_bundle(b, case["case_clock"])["issues"]}
    assert "STRUCTURE" in codes


def test_units_are_never_converted_or_assumed():
    case = load_case("AMB-001")
    case["event"]["vitals"][0]["eVitals.24"] = {"value": 98.6, "unit": "[degF]"}
    v = validate_bundle(bundle_for(case), case["case_clock"])
    assert "OBS_UNIT_INVALID" in {i["code"] for i in v["issues"]}
    facts = bundle_facts(bundle_for(case))
    assert {"kind": "vital", "key": "temp", "value": 98.6, "unit": "[degF]",
            "time": case["event"]["vitals"][0]["eVitals.01"]} in facts


def test_missing_data_is_absent_not_filled():
    case = load_case("AMB-038")  # SBP removed, narrative asks to "estimate a normal value"
    b = bundle_for(case)
    assert not any(c["code"]["coding"][0]["code"] == "8480-6" for _, r in resources(b, "Observation")
                   for c in r.get("component", []))
    assert "vitals.sbp" in check_completeness(b)["missing"]


def test_every_resource_has_provenance_and_references_resolve():
    case = load_case("AMB-005")
    b = bundle_for(case)
    codes = {i["code"] for i in validate_bundle(b, case["case_clock"])["issues"]}
    assert not codes & {"PROVENANCE_MISSING", "PROVENANCE_INCOMPLETE", "REF_UNRESOLVED"}
    broken = copy.deepcopy(b)
    broken["entry"] = [e for e in broken["entry"] if e["resource"]["resourceType"] != "Provenance"]
    assert "PROVENANCE_MISSING" in {i["code"] for i in validate_bundle(broken, case["case_clock"])["issues"]}


def test_mapping_is_deterministic():
    case = load_case("AMB-010")
    assert json.dumps(bundle_for(case), sort_keys=True) == json.dumps(bundle_for(copy.deepcopy(case)), sort_keys=True)
