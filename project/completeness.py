"""Deterministic handoff completeness checks (MIST minimum dataset) over the FHIR Bundle.

Missing items are reported by stable field IDs. Nothing is ever filled in.
"""

from __future__ import annotations

import re

from .mapper import ARRIVED_AT_PATIENT, resources, source_path
from .terminology import LOINC_TO_VITAL, REQUIRED_VITALS


def check_completeness(bundle: dict) -> dict:
    missing: list[str] = []
    patient = next((r for _, r in resources(bundle, "Patient")), {})
    if not any(i.get("type", {}).get("coding", [{}])[0].get("code") == "MR" for i in patient.get("identifier", [])):
        missing.append("patient.mrn")
    for field in ("birthDate", "gender"):
        if not patient.get(field):
            missing.append(f"patient.{field}")

    if not resources(bundle, "Practitioner"):
        missing.append("crew")

    enc = next((r for _, r in resources(bundle, "Encounter")), {})
    scene = (enc.get("location") or [{}])[0].get("period", {})
    if not enc.get("period", {}).get("start"):
        missing.append("times.dispatch")
    if not any(x["url"] == ARRIVED_AT_PATIENT for x in enc.get("extension", [])):
        missing.append("times.at_patient")
    if not scene.get("end"):
        missing.append("times.left_scene")

    if not any(source_path(r) == "situation.eSituation.09" for _, r in resources(bundle, "Condition")):
        missing.append("situation.symptom")
    if not resources(bundle, "ClinicalImpression"):
        missing.append("situation.impression")

    seen: set[str] = set()
    untimed: set[int] = set()
    for _, r in resources(bundle, "Observation"):
        m = re.match(r"vitals\[(\d+)\]", source_path(r) or "")
        if "effectiveDateTime" not in r and m:
            untimed.add(int(m.group(1)))
        for item in r.get("component") or [r]:
            key = LOINC_TO_VITAL.get(item["code"]["coding"][0]["code"])
            if key and item.get("valueQuantity", {}).get("value") is not None:
                seen.add(key)
    missing += [f"vitals.{k}" for k in REQUIRED_VITALS if k not in seen]
    missing += [f"vitals[{i}].time" for i in sorted(untimed)]

    procs, meds = resources(bundle, "Procedure"), resources(bundle, "MedicationAdministration")
    comp = bundle["entry"][0]["resource"] if bundle.get("entry") else {}
    treat = next((s for s in comp.get("section", []) if s.get("title") == "Treatment"), {})
    documented_none = treat.get("emptyReason", {}).get("coding", [{}])[0].get("code") == "nilknown"
    if not procs and not meds and not documented_none:
        missing.append("treatment")
    for _, r in meds:
        idx = re.match(r"medications\[(\d+)\]", source_path(r) or "")
        if r.get("dosage", {}).get("dose", {}).get("value") is None:
            missing.append(f"medications[{idx.group(1) if idx else '?'}].dose")
        if "effectiveDateTime" not in r:
            missing.append(f"medications[{idx.group(1) if idx else '?'}].time")

    if not any(source_path(r) == "disposition.eDisposition.02" for _, r in resources(bundle, "Organization")):
        missing.append("disposition.destination")
    return {"complete": not missing, "missing": missing, "checked": "MIST minimum dataset, profile handoff-r4|1.0.0"}
