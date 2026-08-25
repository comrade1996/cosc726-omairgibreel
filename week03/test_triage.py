from __future__ import annotations

import json
import unittest

try:
    from . import lab2_kit as K
    from . import triage
except ImportError:
    import lab2_kit as K
    import triage


class TriageGateTests(unittest.TestCase):
    def test_fenced_json_is_not_repaired(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            triage.gate_1_parses('```json\n{"intent":"other"}\n```')

    def test_unknown_order_is_rejected_by_reference_gate(self) -> None:
        fixture = next(item for item in K.FIXTURES if item.id == "E11")
        data = dict(fixture.gold, order_id="A1102")
        triage.gate_2_conforms(data)
        with self.assertRaises(ValueError):
            triage.gate_3_refers(data, fixture)

    def test_below_threshold_credit_is_rejected(self) -> None:
        data = {
            "intent": "late_delivery",
            "order_id": "A1080",
            "days_late": 1,
            "proposed_action": "request_approval",
            "evidence_ids": ["MSG-E08", "POL-LATE"],
        }
        with self.assertRaises(ValueError):
            triage.gate_4_coheres(data)

    def test_schema_constrained_score(self) -> None:
        score = K.score_technique(
            "E-constrained",
            K.MockModelClient(),
            triage.PROMPT_E,
            schema=K.SCHEMA,
            validator=triage.validate_all,
        )
        self.assertEqual(score.parsed, 12)
        self.assertEqual(score.valid, 12)
        self.assertEqual(score.violations, 0)


if __name__ == "__main__":
    unittest.main()
