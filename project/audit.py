"""Redacted, append-only audit trail (JSONL) with a FHIR AuditEvent view.

Entries hold case IDs, session IDs, tool names, outcomes and argument *hashes*;
never names, narratives or tokens.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REDACT_KEYS = {"clinician_confirmation", "token", "authorization", "narrative", "text"}


def _hash_args(args: dict) -> str:
    safe = {k: ("<redacted>" if k in REDACT_KEYS else v) for k, v in sorted(args.items())}
    return hashlib.sha256(json.dumps(safe, sort_keys=True, default=str).encode()).hexdigest()[:16]


class AuditLog:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.events: list[dict] = []
        self._lock = threading.Lock()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, session_id: str, crew_id: str, action: str, outcome: str, case_id: str | None = None,
               reason: str | None = None, args: dict | None = None, **extra: object) -> dict:
        event = {"id": str(uuid.uuid4()), "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 "mono_ms": round(time.monotonic() * 1000, 1), "session": session_id, "crew": crew_id,
                 "case_id": case_id, "action": action, "outcome": outcome, "reason": reason,
                 "args_sha256": _hash_args(args or {}), **extra}
        with self._lock:
            self.events.append(event)
            if self.path:
                with self.path.open("a") as fh:
                    fh.write(json.dumps(event) + "\n")
        return event

    def for_case(self, case_id: str) -> list[dict]:
        return [e for e in self.events if e["case_id"] == case_id]

    @staticmethod
    def as_fhir(event: dict) -> dict:
        return {"resourceType": "AuditEvent", "id": event["id"],
                "type": {"system": "http://dicom.nema.org/resources/ontology/DCM", "code": "110110", "display": "Patient Record"},
                "subtype": [{"code": event["action"]}], "recorded": event["ts"],
                "outcome": "0" if event["outcome"] in ("ok", "replayed") else "4",
                "outcomeDesc": event.get("reason") or event["outcome"],
                "agent": [{"who": {"identifier": {"value": event["crew"]}}, "requestor": True,
                           "altId": event["session"]}],
                "source": {"observer": {"display": "ambulance-handoff-mcp"}},
                "entity": [{"what": {"identifier": {"value": event["case_id"] or "-"}}}]}
