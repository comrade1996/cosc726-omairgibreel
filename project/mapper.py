"""Deterministic NEMSIS-inspired event -> HL7 FHIR R4 document Bundle mapper (mapping v1.0).

Rules: every value comes from a source field or a documented transformation in
data/mapping_v1.csv. Absent source data stays absent. Units are copied, never
converted. Patient identity is taken from the matched Synthea record, never from
the ambulance event.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from . import MAPPING_VERSION, PROFILE_VERSION, __version__
from .terminology import (BP_PANEL, ICD10, LOINC, NEMSIS_TO_VITAL, OBS_CATEGORY, PROJECT_SYSTEM, RXNORM,
                          SNOMED, UCUM, VITALS)

NS = uuid.UUID("0f1c3a52-7260-4c0e-9b8a-726726726726")
SRC = f"{PROJECT_SYSTEM}/source-path"
ARRIVED_AT_PATIENT = f"{PROJECT_SYSTEM}/StructureDefinition/arrived-at-patient"


def sha256_json(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class _Builder:
    def __init__(self, case_id: str, version: int):
        self.case_id, self.version = case_id, version
        self.entries: list[dict] = []

    def url(self, key: str) -> str:
        return f"urn:uuid:{uuid.uuid5(NS, f'{self.case_id}:v{self.version}:{key}')}"

    def add(self, key: str, resource: dict, source_path: str | None = None, full_url: str | None = None) -> str:
        full_url = full_url or self.url(key)
        resource.setdefault("id", full_url.split(":")[-1])
        if source_path:
            resource.setdefault("identifier", []).append({"system": SRC, "value": source_path})
        self.entries.append({"fullUrl": full_url, "resource": resource})
        return full_url


def _quantity(value: object, unit: object) -> dict:
    q: dict = {"value": value}
    if unit:
        q.update(unit=unit, system=UCUM, code=unit)
    return q


def map_case(case: dict, synthea: dict) -> dict:
    """Return a FHIR R4 document Bundle for one case."""
    ev = case["event"]
    b = _Builder(case["case_id"], case.get("version", 1))
    synthea_resources = [e["resource"] for e in synthea["entry"]]
    patient = dict(next(r for r in synthea_resources if r["resourceType"] == "Patient"))
    patient_url = f"urn:uuid:{patient['id']}"
    p_ref = {"reference": patient_url}

    composition_url = b.url("composition")
    b.add("patient", patient, full_url=patient_url)

    ems_org = b.add("org-ems", {"resourceType": "Organization", "name": f"Synthetic EMS agency {ev.get('eResponse.01', '')}".strip(),
                                "identifier": [{"system": f"{PROJECT_SYSTEM}/ems-agency", "value": ev.get("eResponse.01")}]},
                    "eResponse.01")
    dest = ev.get("disposition", {})
    dest_url = None
    if dest.get("eDisposition.02"):
        dest_url = b.add("org-dest", {"resourceType": "Organization", "name": dest.get("eDisposition.01"),
                                      "identifier": [{"system": f"{PROJECT_SYSTEM}/receiving-org", "value": dest["eDisposition.02"]}]},
                         "disposition.eDisposition.02")
    practitioners = []
    for i, member in enumerate(ev.get("crew", [])):
        practitioners.append(b.add(f"crew-{i}", {"resourceType": "Practitioner",
                                                 "identifier": [{"system": f"{PROJECT_SYSTEM}/crew", "value": member["eCrew.01"]}]},
                                   f"crew[{i}].eCrew.01"))
    performer = [{"actor": {"reference": practitioners[0]}}] if practitioners else []

    times = ev.get("times", {})
    scene_url = b.add("scene", {"resourceType": "Location", "name": "Incident scene (synthetic, no address recorded)", "mode": "instance"})
    scene_loc: dict = {"location": {"reference": scene_url}, "status": "completed"}
    scene_period = {k: times[e] for k, e in (("start", "eTimes.06"), ("end", "eTimes.09")) if times.get(e)}
    if scene_period:
        scene_loc["period"] = scene_period
    encounter: dict = {
        "resourceType": "Encounter", "status": "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER", "display": "emergency"},
        "type": [{"text": "Ambulance attendance and transfer of care"}],
        "subject": p_ref,
        "serviceProvider": {"reference": ems_org, "display": ev.get("eResponse.13")},
        "location": [scene_loc],
    }
    period = {k: times[e] for k, e in (("start", "eTimes.03"), ("end", "eTimes.11")) if times.get(e)}
    if period:
        encounter["period"] = period
    if times.get("eTimes.07"):
        encounter["extension"] = [{"url": ARRIVED_AT_PATIENT, "valueDateTime": times["eTimes.07"]}]
    if dest_url:
        encounter["hospitalization"] = {"destination": {"reference": dest_url}}
    if practitioners:
        encounter["participant"] = [{"individual": {"reference": u}} for u in practitioners]
    encounter_url = b.add("encounter", encounter, "eResponse.03")
    enc_ref = {"reference": encounter_url}
    encounter["identifier"].insert(0, {"system": f"{PROJECT_SYSTEM}/incident", "value": ev.get("eResponse.03")})

    sit = ev.get("situation", {})
    impression_url = None
    symptom_url = None
    if "eSituation.09" in sit:
        cond = {"resourceType": "Condition", "subject": p_ref, "encounter": enc_ref,
                "verificationStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": "provisional"}]},
                "category": [{"text": "EMS primary symptom"}],
                "code": {"coding": [{"system": ICD10, "code": sit["eSituation.09"]["code"], "display": sit["eSituation.09"]["text"]}],
                         "text": sit["eSituation.09"]["text"]}}
        if sit.get("eSituation.01"):
            cond["onsetDateTime"] = sit["eSituation.01"]
        symptom_url = b.add("symptom", cond, "situation.eSituation.09")
    if "eSituation.11" in sit:
        ci: dict = {"resourceType": "ClinicalImpression", "status": "in-progress", "subject": p_ref, "encounter": enc_ref,
                    "description": "Provisional EMS working impression. Not a diagnosis.",
                    "finding": [{"itemCodeableConcept": {"coding": [{"system": ICD10, "code": sit["eSituation.11"]["code"],
                                                                      "display": sit["eSituation.11"]["text"]}],
                                                         "text": sit["eSituation.11"]["text"]}}]}
        if symptom_url:
            ci["problem"] = [{"reference": symptom_url}]
        if practitioners:
            ci["assessor"] = {"reference": practitioners[0]}
        impression_url = b.add("impression", ci, "situation.eSituation.11")

    vital_urls = []
    for i, row in enumerate(ev.get("vitals", [])):
        when = row.get("eVitals.01")
        base = {"resourceType": "Observation", "status": "final", "subject": p_ref, "encounter": enc_ref,
                "category": [{"coding": [{"system": OBS_CATEGORY, "code": "vital-signs"}]}]}
        if when:
            base["effectiveDateTime"] = when
        if practitioners:
            base["performer"] = [{"reference": practitioners[0]}]
        if "eVitals.06" in row or "eVitals.07" in row:
            obs = {**base, "code": {"coding": [{"system": LOINC, "code": BP_PANEL[0], "display": BP_PANEL[1]}]}, "component": []}
            for el in ("eVitals.06", "eVitals.07"):
                if el in row:
                    key = NEMSIS_TO_VITAL[el]
                    obs["component"].append({"code": {"coding": [{"system": LOINC, "code": VITALS[key][1], "display": VITALS[key][2]}]},
                                             "valueQuantity": _quantity(row[el].get("value"), row[el].get("unit"))})
            vital_urls.append(b.add(f"vitals-{i}-bp", obs, f"vitals[{i}].bp"))
        for el, val in row.items():
            key = NEMSIS_TO_VITAL.get(el)
            if key is None or key in ("sbp", "dbp"):
                continue
            obs = {**base, "code": {"coding": [{"system": LOINC, "code": VITALS[key][1], "display": VITALS[key][2]}]},
                   "valueQuantity": _quantity(val.get("value"), val.get("unit"))}
            vital_urls.append(b.add(f"vitals-{i}-{key}", obs, f"vitals[{i}].{el}"))

    treatment_urls = []
    for i, p in enumerate(ev.get("procedures", [])):
        proc = {"resourceType": "Procedure", "status": "completed", "subject": p_ref, "encounter": enc_ref,
                "code": {"coding": [{"system": SNOMED, "code": p["eProcedures.03"]["code"], "display": p["eProcedures.03"]["text"]}],
                         "text": p["eProcedures.03"]["text"]}}
        if p.get("eProcedures.01"):
            proc["performedDateTime"] = p["eProcedures.01"]
        if performer:
            proc["performer"] = performer
        treatment_urls.append(b.add(f"procedure-{i}", proc, f"procedures[{i}]"))
    for i, m in enumerate(ev.get("medications", [])):
        med = {"resourceType": "MedicationAdministration", "status": "completed", "subject": p_ref, "context": enc_ref,
               "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": m["eMedications.03"]["code"],
                                                         "display": m["eMedications.03"]["text"]}], "text": m["eMedications.03"]["text"]},
               "effectiveDateTime": m.get("eMedications.01")}
        if med["effectiveDateTime"] is None:
            med.pop("effectiveDateTime")
        if m.get("eMedications.05") is not None:
            med["dosage"] = {"dose": _quantity(m["eMedications.05"], m.get("eMedications.06"))}
        if performer:
            med["performer"] = performer
        treatment_urls.append(b.add(f"medication-{i}", med, f"medications[{i}]"))

    background = []
    for r in synthea_resources:
        if r["resourceType"] in ("Condition", "AllergyIntolerance"):
            r = json.loads(json.dumps(r).replace(f"Patient/{patient['id']}", patient_url))
            background.append(b.add(f"bg-{r['id']}", r, full_url=f"urn:uuid:{r['id']}"))

    device_url = b.add("device", {"resourceType": "Device", "deviceName": [{"name": "ambulance-handoff-mapper", "type": "model-name"}],
                                  "version": [{"value": f"{__version__} mapping {MAPPING_VERSION}"}]})

    narrative = ev.get("narrative", {}).get("eNarrative.01")
    sections = [
        {"title": "Mechanism / illness", "entry": [{"reference": u} for u in (symptom_url, impression_url) if u]},
        {"title": "Signs (vital signs)", "entry": [{"reference": u} for u in vital_urls]},
        _treatment_section(treatment_urls, ev.get("treatment_none")),
        {"title": "Background (Synthea record)", "entry": [{"reference": u} for u in background]},
    ]
    for s in sections:
        if not s.get("entry"):
            s.pop("entry", None)
            s.setdefault("emptyReason", {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/list-empty-reason",
                                                     "code": "unavailable"}]})
    if narrative is not None:
        sections.append({"title": "Crew narrative (untrusted free text)",
                         "text": {"status": "generated", "div": '<div xmlns="http://www.w3.org/1999/xhtml">Narrative held in source record; '
                                                               'treated as untrusted data.</div>'}})
    composition = {"resourceType": "Composition", "status": "preliminary",
                   "identifier": {"system": f"{PROJECT_SYSTEM}/pcr", "value": ev.get("eRecord.01")},
                   "type": {"coding": [{"system": LOINC, "code": "18761-6", "display": "Transfer summary note"}]},
                   "subject": p_ref, "encounter": enc_ref, "date": case["case_clock"],
                   "author": [{"reference": practitioners[0]}] if practitioners else [{"reference": device_url}],
                   "title": f"Ambulance handoff {case['case_id']} (synthetic)", "section": sections}
    if dest_url:
        composition["custodian"] = {"reference": dest_url}
    b.entries.insert(0, {"fullUrl": composition_url, "resource": {**composition, "id": composition_url.split(":")[-1]}})

    targets = [{"reference": e["fullUrl"]} for e in b.entries]
    b.add("provenance", {"resourceType": "Provenance", "target": targets, "recorded": case["case_clock"],
                         "activity": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-DataOperation", "code": "CREATE"}]},
                         "agent": [{"type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                                                         "code": "assembler"}]}, "who": {"reference": device_url}}],
                         "entity": [{"role": "source", "what": {"identifier": {"system": f"{PROJECT_SYSTEM}/source-event",
                                                                               "value": f"{case['case_id']}:v{case.get('version', 1)}:sha256:{sha256_json(ev)[:16]}"},
                                                                "display": f"NEMSIS-inspired synthetic event, mapping v{MAPPING_VERSION}"}},
                                    {"role": "source", "what": {"reference": patient_url, "display": "Synthea FHIR R4 Patient"}}]})
    return {"resourceType": "Bundle", "id": str(uuid.uuid5(NS, f"{case['case_id']}:v{case.get('version', 1)}:bundle")),
            "meta": {"profile": [f"{PROJECT_SYSTEM}/StructureDefinition/handoff-r4|{PROFILE_VERSION}"]},
            "identifier": {"system": f"{PROJECT_SYSTEM}/handoff", "value": f"{case['case_id']}-v{case.get('version', 1)}"},
            "type": "document", "timestamp": case["case_clock"], "entry": b.entries}


def _treatment_section(urls: list[str], treatment_none: object) -> dict:
    section: dict = {"title": "Treatment"}
    if urls:
        section["entry"] = [{"reference": u} for u in urls]
    elif treatment_none is True:
        section["emptyReason"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/list-empty-reason", "code": "nilknown",
                                              "display": "Nil Known"}], "text": "No treatment given (documented by crew)"}
    return section


def resources(bundle: dict, rtype: str | None = None) -> list[tuple[str, dict]]:
    return [(e["fullUrl"], e["resource"]) for e in bundle.get("entry", [])
            if rtype is None or e["resource"]["resourceType"] == rtype]


def source_path(resource: dict) -> str | None:
    return next((i["value"] for i in resource.get("identifier", []) if isinstance(i, dict) and i.get("system") == SRC), None)


def bundle_facts(bundle: dict) -> list[dict]:
    """Extract facts from a Bundle in the same shape as the case oracle (labels.expected_facts)."""
    from .terminology import LOINC_TO_VITAL
    out = []
    for _, r in resources(bundle, "Observation"):
        items = r.get("component") or [r]
        for item in items:
            key = LOINC_TO_VITAL.get(item["code"]["coding"][0]["code"])
            if key and "valueQuantity" in item:
                q = item["valueQuantity"]
                out.append({"kind": "vital", "key": key, "value": q.get("value"), "unit": q.get("unit"),
                            "time": r.get("effectiveDateTime")})
    for _, r in resources(bundle, "Procedure"):
        out.append({"kind": "procedure", "code": r["code"]["coding"][0]["code"], "time": r.get("performedDateTime")})
    for _, r in resources(bundle, "MedicationAdministration"):
        dose = r.get("dosage", {}).get("dose", {})
        out.append({"kind": "medication", "code": r["medicationCodeableConcept"]["coding"][0]["code"],
                    "dose": dose.get("value"), "unit": dose.get("unit"), "time": r.get("effectiveDateTime")})
    enc = next((r for _, r in resources(bundle, "Encounter")), {})
    period, scene = enc.get("period", {}), (enc.get("location") or [{}])[0].get("period", {})
    for el, val in (("eTimes.03", period.get("start")), ("eTimes.06", scene.get("start")),
                    ("eTimes.07", next((x["valueDateTime"] for x in enc.get("extension", []) if x["url"] == ARRIVED_AT_PATIENT), None)),
                    ("eTimes.09", scene.get("end")), ("eTimes.11", period.get("end"))):
        if val:
            out.append({"kind": "time", "element": el, "value": val})
    for _, r in resources(bundle, "Condition"):
        if source_path(r) == "situation.eSituation.09":
            out.append({"kind": "situation", "element": "eSituation.09", "code": r["code"]["coding"][0]["code"]})
    for _, r in resources(bundle, "ClinicalImpression"):
        out.append({"kind": "situation", "element": "eSituation.11", "code": r["finding"][0]["itemCodeableConcept"]["coding"][0]["code"]})
    for _, r in resources(bundle, "Organization"):
        if source_path(r) == "disposition.eDisposition.02":
            out.append({"kind": "destination", "code": r["identifier"][0]["value"]})
    return out
