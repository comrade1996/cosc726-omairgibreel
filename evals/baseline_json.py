"""Configuration 1 baseline: a typical point-to-point custom JSON integration.

No FHIR, no MCP, no authorization. It checks that top-level keys are present and
non-empty, builds a text summary (appending any caller-supplied notes), and "sends".
It is deliberately ordinary, not deliberately broken: this is what the proposal's
research questions compare against.
"""

from __future__ import annotations

from project.dataset import load_case
from project.terminology import REQUIRED_VITALS, VITALS


class JsonBaseline:
    def __init__(self) -> None:
        self.sends: dict[str, int] = {}

    def read_case(self, case_id: str, **_: object) -> dict | None:
        return load_case(case_id)

    @staticmethod
    def missing(event: dict) -> list[str]:
        out = []
        if not event.get("vitals"):
            out += [f"vitals.{k}" for k in REQUIRED_VITALS]
        if not event.get("crew"):
            out.append("crew")
        if not event.get("disposition"):
            out.append("disposition.destination")
        if not event.get("procedures") and not event.get("medications") and "treatment_none" not in event:
            out.append("treatment")
        if not event.get("situation"):
            out += ["situation.symptom", "situation.impression"]
        if not event.get("times"):
            out += ["times.dispatch", "times.at_patient", "times.left_scene"]
        return out

    @staticmethod
    def summary(case: dict, notes: dict | None = None) -> str:
        ev = case["event"]
        lines = []
        for row in ev.get("vitals", []):
            vals = [f"{k.upper()} {row[v[0]]['value']}" for k, v in VITALS.items() if v[0] in row]
            lines.append("S: " + ", ".join(vals))
        for m in ev.get("medications", []):
            lines.append(f"T: {m['eMedications.03']['text']} {m.get('eMedications.05', '')}")
        for k, v in (notes or {}).items():
            lines.append(f"S: {k.upper()} {v}")
        return "\n".join(lines)

    def send(self, case_id: str, **_: object) -> dict:
        self.sends[case_id] = self.sends.get(case_id, 0) + 1
        return {"status": "sent", "handoff_id": f"JSON-{case_id}-{self.sends[case_id]}"}
