"""Loads the committed synthetic dataset: Synthea subset, cases, crews."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def _cases() -> dict[str, dict]:
    with (DATA / "cases.jsonl").open() as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return {r["case_id"]: r for r in rows}


@lru_cache(maxsize=1)
def _crews() -> dict:
    return json.loads((DATA / "crews.json").read_text())


@lru_cache(maxsize=None)
def _synthea(patient_id: str) -> dict:
    return json.loads((DATA / "synthea_subset" / f"{patient_id}.json").read_text())


def case_ids() -> list[str]:
    return sorted(_cases())


def load_case(case_id: str) -> dict | None:
    row = _cases().get(case_id)
    return copy.deepcopy(row) if row else None


def all_cases() -> list[dict]:
    return [copy.deepcopy(_cases()[k]) for k in case_ids()]


def synthea_bundle(patient_id: str) -> dict:
    return copy.deepcopy(_synthea(patient_id))


def crews() -> dict:
    return copy.deepcopy(_crews()["crews"])


def receiving_organizations() -> dict[str, str]:
    return dict(_crews()["receiving_organizations"])
