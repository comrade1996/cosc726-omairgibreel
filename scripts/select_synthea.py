#!/usr/bin/env python3
"""Deterministically select 20 Synthea FHIR R4 patients for the handoff dataset.

The selected, minimised subset is committed under project/data/synthea_subset/,
so a marker never needs to run this script. It is kept for provenance: anyone can
re-download the pinned archive and reproduce the subset byte-for-byte.

    python scripts/select_synthea.py --zip synthea_sample_data_fhir_r4_nov2021.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

SOURCE_URL = (
    "https://synthetichealth.github.io/synthea-sample-data/downloads/"
    "synthea_sample_data_fhir_r4_nov2021.zip"
)
SOURCE_SHA256 = "6d3c5433bcae4791bc5c30469d1445b430fb4894d5c13bda15fee0584bbd7778"
REFERENCE_DATE = date(2026, 1, 1)
N_PATIENTS = 20
OUT = Path(__file__).resolve().parents[1] / "project" / "data" / "synthea_subset"


def age_on(birth: str, ref: date) -> int:
    b = date.fromisoformat(birth)
    return ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day))


def minimise(bundle: dict) -> dict:
    """Keep only what a handoff needs: identity, active disorders, active allergies."""
    resources = [e["resource"] for e in bundle["entry"]]
    patient = next(r for r in resources if r["resourceType"] == "Patient")
    keep_patient = {
        "resourceType": "Patient",
        "id": patient["id"],
        "identifier": [
            i for i in patient.get("identifier", [])
            if i.get("type", {}).get("coding", [{}])[0].get("code") == "MR"
        ],
        "name": [{k: v for k, v in patient["name"][0].items() if k in ("use", "family", "given")}],
        "gender": patient["gender"],
        "birthDate": patient["birthDate"],
    }

    def active(r: dict) -> bool:
        return r.get("clinicalStatus", {}).get("coding", [{}])[0].get("code") == "active"

    conditions = sorted(
        (r for r in resources
         if r["resourceType"] == "Condition" and active(r) and "(disorder)" in r["code"].get("text", "")),
        key=lambda r: r.get("onsetDateTime", ""),
    )[-5:]
    allergies = [r for r in resources if r["resourceType"] == "AllergyIntolerance" and active(r)]
    slim = []
    for r in conditions + allergies:
        subject_key = "subject" if r["resourceType"] == "Condition" else "patient"
        slim.append({
            "resourceType": r["resourceType"],
            "id": r["id"],
            "clinicalStatus": r["clinicalStatus"],
            "code": r["code"],
            subject_key: {"reference": f"Patient/{patient['id']}"},
            **({"onsetDateTime": r["onsetDateTime"]} if "onsetDateTime" in r else {}),
            **({"criticality": r["criticality"]} if "criticality" in r else {}),
        })
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [{"resource": r} for r in [keep_patient, *slim]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=Path("synthea_sample_data_fhir_r4_nov2021.zip"))
    args = ap.parse_args()
    if not args.zip.exists():
        print(f"Downloading {SOURCE_URL}")
        urllib.request.urlretrieve(SOURCE_URL, args.zip)
    digest = hashlib.sha256(args.zip.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise SystemExit(f"Archive hash mismatch: {digest}")

    candidates = []
    with zipfile.ZipFile(args.zip) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".json") or "Information" in name:
                continue
            bundle = json.loads(zf.read(name))
            patient = bundle["entry"][0]["resource"]
            if patient["resourceType"] != "Patient" or "deceasedDateTime" in patient:
                continue
            if not 18 <= age_on(patient["birthDate"], REFERENCE_DATE) <= 90:
                continue
            rank = hashlib.sha256(patient["id"].encode()).hexdigest()
            candidates.append((rank, name, bundle))

    candidates.sort(key=lambda c: c[0])
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    manifest = {
        "source_url": SOURCE_URL,
        "source_sha256": SOURCE_SHA256,
        "selection_rule": "alive, age 18-90 on 2026-01-01, ordered by sha256(patient.id), first 20",
        "minimisation": "Patient(MR identifier, name, gender, birthDate); <=5 active disorders; active allergies",
        "eligible_patients": len(candidates),
        "patients": [],
    }
    for rank, name, bundle in candidates[:N_PATIENTS]:
        slim = minimise(bundle)
        pid = slim["entry"][0]["resource"]["id"]
        (OUT / f"{pid}.json").write_text(json.dumps(slim, indent=1, sort_keys=True) + "\n")
        manifest["patients"].append({"id": pid, "source_file": name})
    (OUT.parent / "synthea_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"Selected {N_PATIENTS} of {len(candidates)} eligible patients -> {OUT}")


if __name__ == "__main__":
    main()
