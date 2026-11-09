"""FHIR validation: structural (pydantic FHIR models) + project profile handoff-r4 v1.0.0.

Rule: *present but malformed* data is a validation error; *absent* data is a
completeness gap (see completeness.py). Errors block confirmation.
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache

from pydantic import ValidationError

from .mapper import ARRIVED_AT_PATIENT, resources, source_path
from .terminology import LOINC_TO_VITAL, PLAUSIBLE, TIME_ORDER, UCUM, VITALS

STRUCTURAL_ENGINE = "fhir.resources R4B models (resource structures used here are unchanged from R4 4.0.1)"
_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


@lru_cache(maxsize=None)
def _model(rtype: str):
    from fhir.resources.R4B import get_fhir_model_class
    return get_fhir_model_class(rtype)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def issue(code: str, severity: str, where: str, detail: str) -> dict:
    return {"code": code, "severity": severity, "location": where, "detail": detail}


def structural(bundle: dict) -> list[dict]:
    out = []
    for target in [bundle] + [r for _, r in resources(bundle)]:
        try:
            _model(target["resourceType"]).model_validate(target)
        except ValidationError as e:
            for err in e.errors()[:5]:
                loc = ".".join(str(x) for x in err["loc"])
                out.append(issue("STRUCTURE", "error", f"{target['resourceType']}/{target.get('id', '?')}.{loc}", err["msg"]))
        except (KeyError, TypeError, ValueError) as e:
            out.append(issue("STRUCTURE", "error", target.get("resourceType", "?"), str(e)[:200]))
    return out


def profile(bundle: dict, case_clock: str) -> list[dict]:
    out: list[dict] = []
    entries = bundle.get("entry", [])
    if bundle.get("type") != "document":
        out.append(issue("BUNDLE_TYPE", "error", "Bundle.type", "handoff must be a document Bundle"))
    if not entries or entries[0]["resource"]["resourceType"] != "Composition":
        out.append(issue("COMPOSITION_FIRST", "error", "Bundle.entry[0]", "first entry must be a Composition"))
    urls = {e["fullUrl"] for e in entries}

    def walk(node: object, where: str) -> None:
        if isinstance(node, dict):
            ref = node.get("reference")
            if isinstance(ref, str) and ref not in urls:
                out.append(issue("REF_UNRESOLVED", "error", where, "reference does not resolve inside the Bundle"))
            for k, v in node.items():
                walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")

    clock = _dt(case_clock)
    for url, r in resources(bundle):
        where = f"{r['resourceType']}/{r.get('id')}"
        walk({k: v for k, v in r.items() if k != "identifier"}, where)
        for field in ("effectiveDateTime", "performedDateTime", "onsetDateTime"):
            val = r.get(field)
            if isinstance(val, str):
                if not _DT.match(val):
                    out.append(issue("TIME_FORMAT", "error", f"{where}.{field}", "dateTime must include time zone"))
                elif _dt(val) > clock:
                    out.append(issue("TIME_FUTURE", "error", f"{where}.{field}", "timestamp is after the handoff clock"))

    for url, r in resources(bundle, "Observation"):
        where = f"Observation/{r.get('id')} ({source_path(r)})"
        if "effectiveDateTime" not in r:
            out.append(issue("OBS_TIME_MISSING", "warning", where, "vital sign has no time; reported as a completeness gap"))
        for item in r.get("component") or [r]:
            key = LOINC_TO_VITAL.get(item.get("code", {}).get("coding", [{}])[0].get("code"))
            if key is None:
                if not r.get("component"):
                    out.append(issue("OBS_CODE", "error", where, "vital sign must use a profile LOINC code"))
                continue
            q = item.get("valueQuantity")
            if q is None:
                continue
            if q.get("value") is None:
                out.append(issue("OBS_VALUE_MISSING", "error", where, f"{key} has a unit but no value"))
                continue
            if not q.get("unit"):
                out.append(issue("OBS_UNIT_MISSING", "error", where, f"{key} value has no unit; units are never assumed"))
            elif q.get("system") != UCUM or q.get("code") != VITALS[key][3]:
                out.append(issue("OBS_UNIT_INVALID", "error", where, f"{key} must use UCUM {VITALS[key][3]}; no conversion is performed"))
            lo, hi = PLAUSIBLE[key]
            if isinstance(q.get("value"), (int, float)) and not lo <= q["value"] <= hi:
                out.append(issue("OBS_VALUE_IMPLAUSIBLE", "error", where, f"{key} outside plausibility range {lo}-{hi}"))

    for url, r in resources(bundle, "MedicationAdministration"):
        dose = r.get("dosage", {}).get("dose")
        if dose and dose.get("value") is not None and not dose.get("unit"):
            out.append(issue("MED_DOSE_UNIT_MISSING", "error", f"MedicationAdministration/{r.get('id')}",
                             "dose value without unit"))

    enc = next((r for _, r in resources(bundle, "Encounter")), None)
    if enc:
        period, scene = enc.get("period", {}), (enc.get("location") or [{}])[0].get("period", {})
        arrived = next((x["valueDateTime"] for x in enc.get("extension", []) if x["url"] == ARRIVED_AT_PATIENT), None)
        stamps = dict(zip(TIME_ORDER, (period.get("start"), scene.get("start"), arrived, scene.get("end"), period.get("end"))))
        present = [(k, v) for k, v in stamps.items() if v]
        for (k1, v1), (k2, v2) in zip(present, present[1:]):
            if _dt(v2) < _dt(v1):
                out.append(issue("TIME_ORDER", "error", "Encounter", f"{k2} is earlier than {k1}"))
        for k, v in present:
            if _dt(v) > clock:
                out.append(issue("TIME_FUTURE", "error", "Encounter", f"{k} is after the handoff clock"))

    prov = [r for _, r in resources(bundle, "Provenance")]
    if not prov:
        out.append(issue("PROVENANCE_MISSING", "error", "Bundle", "a Provenance resource is required"))
    else:
        targeted = {t["reference"] for p in prov for t in p.get("target", [])}
        untargeted = urls - targeted - {u for u, r in resources(bundle, "Provenance")}
        if untargeted:
            out.append(issue("PROVENANCE_INCOMPLETE", "error", "Provenance.target", f"{len(untargeted)} resources lack provenance"))
    return out


def validate_bundle(bundle: dict, case_clock: str) -> dict:
    issues = structural(bundle) + profile(bundle, case_clock)
    errors = [i for i in issues if i["severity"] == "error"]
    return {"valid": not errors, "error_count": len(errors), "warning_count": len(issues) - len(errors),
            "issues": issues, "engine": STRUCTURAL_ENGINE, "profile": "handoff-r4|1.0.0"}
