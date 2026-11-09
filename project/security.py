"""Server-side security: session scope, clinician approval tokens, patient matching, injection screen.

The model never holds a signing key. Scope comes from a token the *host* gives the
server at launch (stdio env) or in the Authorization header (HTTP); tool arguments
can never widen it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass, field


class SecurityError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(key: bytes, claims: dict) -> str:
    body = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    mac = _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())
    return f"{body}.{mac}"


def verify(key: bytes, token: str, purpose: str) -> dict:
    try:
        body, mac = token.split(".")
        expected = _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(mac, expected):
            raise SecurityError("bad_signature")
        claims = json.loads(_unb64(body))
    except SecurityError:
        raise
    except Exception as e:
        raise SecurityError("malformed_token") from e
    if claims.get("purpose") != purpose:
        raise SecurityError("wrong_token_purpose")
    if claims.get("exp", 0) < time.time():
        raise SecurityError("token_expired")
    return claims


def new_key() -> bytes:
    return secrets.token_bytes(32)


@dataclass(frozen=True)
class Scope:
    session_id: str
    crew_id: str
    tenant: str
    case_ids: frozenset[str] = field(default_factory=frozenset)

    def require(self, case_id: str) -> None:
        if case_id not in self.case_ids:
            raise SecurityError("forbidden", "case is outside this session's authorised scope")


def issue_session_token(key: bytes, crew_id: str, tenant: str, case_ids: list[str], ttl: int = 8 * 3600) -> str:
    return sign(key, {"purpose": "session", "sid": secrets.token_hex(6), "crew": crew_id, "tenant": tenant,
                      "cases": sorted(case_ids), "exp": int(time.time()) + ttl})


def scope_from_token(key: bytes, token: str) -> Scope:
    c = verify(key, token, "session")
    return Scope(session_id=c["sid"], crew_id=c["crew"], tenant=c["tenant"], case_ids=frozenset(c["cases"]))


def issue_clinician_approval(key: bytes, *, case_id: str, case_version: int, draft_sha256: str, receiving_org: str,
                             clinician_id: str, ttl: int = 600) -> str:
    """Called only by the host's human approval gate, never exposed as a tool."""
    return sign(key, {"purpose": "clinician_approval", "case": case_id, "ver": case_version, "draft": draft_sha256,
                      "org": receiving_org, "clinician": clinician_id, "role": "clinician",
                      "nonce": secrets.token_hex(4), "exp": int(time.time()) + ttl})


# ---------------------------------------------------------------- patient match
def match_patient(event_patient: dict, synthea_patient: dict) -> dict:
    """Multi-attribute match. Reasons name the attribute only, never the values."""
    mrn = next((i["value"] for i in synthea_patient.get("identifier", [])
                if i.get("type", {}).get("coding", [{}])[0].get("code") == "MR"), None)
    checks = {
        "mrn": event_patient.get("mrn") == mrn and mrn is not None,
        "birthDate": event_patient.get("ePatient.17") == synthea_patient.get("birthDate"),
        "sex": event_patient.get("ePatient.25") == synthea_patient.get("gender"),
        "family": (event_patient.get("ePatient.02") or "").casefold() == synthea_patient["name"][0]["family"].casefold(),
    }
    failed = [k for k, ok in checks.items() if not ok]
    return {"matched": not failed, "failed_attributes": failed, "method": "exact MRN + birthDate + sex + family name"}


# ---------------------------------------------------------------- injection screen
_INJECTION = [
    (r"ignore (all |any )?(previous|prior|above) (instructions|rules)", "override_instructions"),
    (r"\bsystem (notice|prompt|message)\b|\bassistant:|\bAI assistant\b", "addresses_the_model"),
    (r"\b(confirm_handoff|record_ed_acknowledgement|get_ambulance_case|create_handoff_draft)\b", "names_a_tool"),
    (r"\b(admin|developer|god) mode\b|\byou are now\b", "role_change"),
    (r"\bmark (the )?handoff as sent\b|\balready approved\b", "claims_approval"),
    (r"\b(retrieve|fetch|include|send) (case|patient|record)s?\b.*\b(AMB-\d+|other patient|phone|address)", "exfiltration"),
    (r"\bestimate (a )?(normal )?(value|bp|blood pressure)|\bmake up\b|\binvent\b", "fabrication_request"),
]


def screen_text(text: str | None) -> dict:
    if not text:
        return {"suspected": False, "signals": []}
    signals = sorted({name for pat, name in _INJECTION if re.search(pat, text, re.IGNORECASE)})
    return {"suspected": bool(signals), "signals": signals}
