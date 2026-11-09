"""Grounded MIST / SBAR handoff drafts built only from Bundle content.

Every line carries evidence references (Bundle fullUrls). Gaps are stated as
"not documented"; nothing is estimated. Free-text narrative is quoted as
untrusted, or withheld when the injection screen flags it.
"""

from __future__ import annotations

from datetime import date

from .mapper import ARRIVED_AT_PATIENT, resources, sha256_json, source_path
from .terminology import LOINC_TO_VITAL, VITALS

LABEL = {"hr": "HR", "rr": "RR", "sbp": "SBP", "dbp": "DBP", "spo2": "SpO2", "gcs": "GCS", "glucose": "BGL",
         "temp": "Temp", "pain": "Pain"}


def _age(birth: str, on: str) -> int:
    b, d = date.fromisoformat(birth), date.fromisoformat(on[:10])
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def _vital_sets(bundle: dict) -> dict[str, list[tuple[str, str, str]]]:
    """time -> [(label, value-with-unit, evidence url)] in Bundle order."""
    sets: dict[str, list[tuple[str, str, str]]] = {}
    for url, r in resources(bundle, "Observation"):
        when = r.get("effectiveDateTime", "time not documented")
        for item in r.get("component") or [r]:
            key = LOINC_TO_VITAL.get(item["code"]["coding"][0]["code"])
            q = item.get("valueQuantity") or {}
            if key and q.get("value") is not None:
                unit = q.get("unit") or "[unit missing]"
                sets.setdefault(when, []).append((LABEL[key], f"{q['value']} {unit}", url))
    return sets


def build_draft(case_id: str, version: int, bundle: dict, completeness: dict, validation: dict, narrative: dict,
                fmt: str = "MIST") -> dict:
    lines: list[dict] = []

    def line(section: str, text: str, evidence: list[str]) -> None:
        lines.append({"section": section, "text": text, "evidence": evidence})

    patient_url, patient = resources(bundle, "Patient")[0]
    comp = bundle["entry"][0]["resource"]
    age = _age(patient["birthDate"], comp["date"])
    dest = next(((u, r) for u, r in resources(bundle, "Organization") if source_path(r) == "disposition.eDisposition.02"), None)
    enc_url, enc = resources(bundle, "Encounter")[0]
    arrived = next((x["valueDateTime"] for x in enc.get("extension", []) if x["url"] == ARRIVED_AT_PATIENT), None)

    symptom = next(((u, r) for u, r in resources(bundle, "Condition") if source_path(r) == "situation.eSituation.09"), None)
    impression = next(iter(resources(bundle, "ClinicalImpression")), None)
    sets = _vital_sets(bundle)
    treatments = [(u, r) for u, r in resources(bundle) if r["resourceType"] in ("Procedure", "MedicationAdministration")]
    allergies = [(u, r) for u, r in resources(bundle, "AllergyIntolerance")]
    history = [(u, r) for u, r in resources(bundle, "Condition") if source_path(r) is None]

    header = f"{age}-year-old {patient['gender']} (Synthea record matched by MRN)"
    line("Patient", header, [patient_url])
    if dest:
        line("Patient", f"Receiving: {dest[1].get('name')} ({dest[1]['identifier'][0]['value']})", [dest[0]])

    m_text = (f"{symptom[1]['code']['text']}, onset {symptom[1].get('onsetDateTime', 'not documented')}"
              if symptom else "Primary symptom not documented")
    mechanism = [m_text + (f"; crew at patient {arrived}" if arrived else "")]
    info = (f"Provisional EMS impression: {impression[1]['finding'][0]['itemCodeableConcept']['text']} "
            f"(working impression, not a diagnosis)" if impression else "EMS impression not documented")
    if sets:
        signs = []
        for when, vals in sets.items():
            signs.append((f"[{when}] " + ", ".join(f"{lab} {v}" for lab, v, _ in vals), [u for *_, u in vals]))
    else:
        signs = [("No vital signs documented", [])]
    treat = []
    for u, r in treatments:
        if r["resourceType"] == "Procedure":
            treat.append((f"{r['code']['text']} at {r.get('performedDateTime', 'time not documented')}", [u]))
        else:
            dose = r.get("dosage", {}).get("dose")
            dose_txt = f"{dose['value']} {dose.get('unit', '[unit missing]')}" if dose else "dose not documented"
            treat.append((f"{r['medicationCodeableConcept']['text']} {dose_txt} given at "
                          f"{r.get('effectiveDateTime', 'time not documented')}", [u]))
    if not treat:
        treat = [("No treatment given (documented)" if "treatment" not in completeness["missing"]
                  else "Treatment not documented", [bundle["entry"][0]["fullUrl"]])]

    sections = {"MIST": [("M - Mechanism/illness", [(mechanism[0], [u for u in (symptom[0] if symptom else None, enc_url) if u])]),
                         ("I - Information/impression", [(info, [impression[0]] if impression else [])]),
                         ("S - Signs", signs),
                         ("T - Treatment", treat)],
                "SBAR": [("S - Situation", [(m_text, [symptom[0]] if symptom else [])]),
                         ("B - Background", [("Allergies: " + (", ".join(r["code"]["text"] for _, r in allergies) or "none recorded in Synthea record"),
                                              [u for u, _ in allergies] or [patient_url]),
                                             ("Active conditions: " + (", ".join(r["code"]["text"] for _, r in history) or "none recorded"),
                                              [u for u, _ in history] or [patient_url])]),
                         ("A - Assessment", [(info, [impression[0]] if impression else [])] + signs),
                         ("R - Request", [("Receiving clinician to review on arrival. Interventions so far: " +
                                           ("; ".join(t for t, _ in treat)), [u for _, us in treat for u in us])])]}
    for title, rows in sections[fmt]:
        for text, ev in rows:
            line(title, text, ev)
    if fmt == "MIST":
        line("Background", "Allergies: " + (", ".join(r["code"]["text"] for _, r in allergies) or "none recorded in Synthea record"),
             [u for u, _ in allergies] or [patient_url])

    if narrative.get("suspected"):
        line("Crew narrative", "[withheld: free text contains instruction-like content "
                               f"({', '.join(narrative['signals'])}); see source record]", [])
    elif narrative.get("text"):
        line("Crew narrative", f"(unverified free text) \"{narrative['text']}\"", [])

    if completeness["missing"]:
        line("Gaps", "NOT DOCUMENTED - obtain from crew before confirmation: " + ", ".join(completeness["missing"]), [])
    errors = [i["code"] for i in validation["issues"] if i["severity"] == "error"]
    if errors:
        line("Gaps", "VALIDATION ERRORS - cannot be confirmed: " + ", ".join(sorted(set(errors))), [])

    body = {"case_id": case_id, "case_version": version, "format": fmt, "lines": lines,
            "receiving_org": dest[1]["identifier"][0]["value"] if dest else None}
    body["draft_sha256"] = sha256_json(body)
    body["confirmable"] = validation["valid"] and completeness["complete"]
    body["text"] = "\n".join(f"{l['section']}: {l['text']}" for l in lines)
    return body


VITAL_LABELS = {LABEL[k]: k for k in VITALS}
