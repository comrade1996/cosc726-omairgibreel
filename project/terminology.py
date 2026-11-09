"""Code systems and the project's handoff data dictionary (profile v1)."""

from __future__ import annotations

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
SNOMED = "http://snomed.info/sct"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
V2_0203 = "http://terminology.hl7.org/CodeSystem/v2-0203"
MRN_SYSTEM = "http://hospital.smarthealthit.org"
PROJECT_SYSTEM = "https://example.org/cosc726/ambulance"

# key: (NEMSIS element, LOINC code, display, required UCUM unit)
VITALS: dict[str, tuple[str, str, str, str]] = {
    "sbp": ("eVitals.06", "8480-6", "Systolic blood pressure", "mm[Hg]"),
    "dbp": ("eVitals.07", "8462-4", "Diastolic blood pressure", "mm[Hg]"),
    "hr": ("eVitals.10", "8867-4", "Heart rate", "/min"),
    "spo2": ("eVitals.12", "59408-5", "Oxygen saturation in Arterial blood by Pulse oximetry", "%"),
    "rr": ("eVitals.14", "9279-1", "Respiratory rate", "/min"),
    "glucose": ("eVitals.18", "2339-0", "Glucose [Mass/volume] in Blood", "mg/dL"),
    "gcs": ("eVitals.23", "9269-2", "Glasgow coma score total", "{score}"),
    "temp": ("eVitals.24", "8310-5", "Body temperature", "Cel"),
    "pain": ("eVitals.27", "72514-3", "Pain severity - 0-10 verbal numeric rating [Score] - Reported", "{score}"),
}
NEMSIS_TO_VITAL = {v[0]: k for k, v in VITALS.items()}
LOINC_TO_VITAL = {v[1]: k for k, v in VITALS.items()}
BP_PANEL = ("85354-9", "Blood pressure panel with all children optional")

# Plausibility limits catch unit or typing errors; they are not clinical thresholds.
PLAUSIBLE = {
    "sbp": (30, 300), "dbp": (10, 200), "hr": (10, 300), "spo2": (30, 100), "rr": (0, 80),
    "glucose": (5, 1500), "gcs": (3, 15), "temp": (25, 45), "pain": (0, 10),
}

REQUIRED_VITALS = ("hr", "rr", "sbp", "spo2", "gcs")
REQUIRED_TIMES = {"eTimes.03": "times.dispatch", "eTimes.07": "times.at_patient", "eTimes.09": "times.left_scene"}
TIME_ORDER = ("eTimes.03", "eTimes.06", "eTimes.07", "eTimes.09", "eTimes.11")

PROFILE = {
    "id": "handoff-r4",
    "version": "1.0.0",
    "fhir_version": "4.0.1",
    "required_for_confirmation": {
        "identity": ["patient matched to Synthea record by MRN + birthDate + sex + family name"],
        "times": list(REQUIRED_TIMES.values()),
        "situation": ["situation.symptom", "situation.impression"],
        "vitals": [f"vitals.{k}" for k in REQUIRED_VITALS] + ["each vital has time and UCUM unit"],
        "treatment": ["procedures or medications documented, or treatment_none=true",
                      "each medication has dose value and unit"],
        "people": ["crew", "disposition.destination"],
        "provenance": ["Provenance targets every generated resource"],
    },
    "never_generated": ["diagnosis", "treatment recommendation", "dose calculation",
                        "destination choice", "dispatch decision", "values absent from source"],
}
