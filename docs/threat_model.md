# Threat model: MCP ambulance handoff gateway

Scope: the stdio/HTTP MCP server (`project/server.py`), the agent host (`project/agent/host.py`)
and the synthetic dataset. Assets: (1) patient records, even synthetic ones, treated as PHI by design;
(2) the integrity of the "handoff sent" state; (3) the clinician's authority to approve.

## Trust boundaries

```
 untrusted                     |  host (trusted)                         |  server (trusted)
 -----------------------------+-----------------------------------------+------------------------------
 LLM output (tool calls, text) | approval gate, keys, budgets, critic   | session scope, gates, audit
 crew narrative / free text    | session token issued to the server     | validator, patient match
 any MCP client over HTTP      |                                         | bearer + Origin check (HTTP)
```

The model is treated as an untrusted planner. Every decision that matters (scope, approval, version,
idempotency, validity) is enforced in code the model cannot reach.

## OWASP Top 10 for Agentic Applications (2026) mapping

| ASI | Threat in this system | Control | Evidence |
|---|---|---|---|
| ASI01 Agent Goal Hijack | Narrative tells the agent to confirm, or to fetch another patient (A07, A08) | Narrative is returned as `untrusted_narrative` with an injection screen; it is withheld from drafts when flagged; confirmation needs a host-signed clinician token; reads are scope-checked server-side | `tests/test_security.py::test_injection_screen_and_draft_withholds_instructions`, eval A07/A08 |
| ASI02 Tool Misuse and Exploitation | Confirm without approval, duplicate sends, extra arguments (A06, A10, A11) | Strict schemas (`additionalProperties: false`, unknown args rejected and audited); idempotency keys; `destructiveHint` annotation; draft/version binding | `test_discovery_and_strict_schemas`, `test_idempotent_retry_and_no_duplicates` |
| ASI03 Identity and Privilege Abuse | `role="doctor"` or `patient_id` arguments; cross-crew / cross-tenant reads (A09, A11) | Scope comes only from an HMAC session token issued by the host (stdio env) or bearer header (HTTP); no tool argument carries authority | `test_cross_crew_read_is_forbidden_and_audited`, `test_session_token_cannot_be_widened`, HTTP 401 probe |
| ASI04 Agentic Supply Chain | Compromised SDK / model / server package | Pinned dependencies (`requirements.txt`), versions recorded beside every result, model weights pulled by digest (Ollama), dataset archive pinned by SHA-256 | `evals/results/summary.json` meta |
| ASI05 Unexpected Code Execution | Agent-generated code executed | No code-execution tool exists; the server only reads committed JSON | Tool list |
| ASI06 Memory & Context Poisoning | Poisoned record fields steer later steps; stale versions (A05) | Every tool result is re-derived from the source record; approvals bind to case version + draft hash; stale replays rejected | `test_stale_version_replay_rejected`, `test_approval_bound_to_exact_draft` |
| ASI07 Insecure Inter-Agent Communication | Spoofed HTTP client | Localhost bind, bearer session tokens, Origin allow-list (DNS-rebinding protection) | HTTP probe: 401 / 401 / 403 |
| ASI08 Cascading Failures | Mapping error propagates into a wrong handoff; runaway loops | Deterministic validator + completeness gate before any draft is confirmable; turn cap, token budget, repeated-call detection | `test_runaway_loop_is_stopped`, `test_token_budget_is_enforced` |
| ASI09 Human-Agent Trust Exploitation | Clinician rubber-stamps a fluent but wrong summary | Approval screen shows the grounded draft with evidence references, gaps and validation errors, not the model's prose; impressions labelled "provisional, not a diagnosis"; critic rejects unsupported numbers | `test_hallucinated_tool_and_invented_value_are_caught_then_recovered` |
| ASI10 Rogue Agents | Agent ignores workflow, stops early or acts out of scope | Policy critic rejects early stops and escalations that hide gaps; server gates hold even if the host is bypassed (attack driver in eval) | Eval attack phase; `run_llm_eval` out-of-scope counts |

## Red-team procedure (Week 10 pattern: attack, impact, patch, re-test)

1. **Attack.** `python -m evals.run_eval --configs C3` runs the 12 adversarial cases against the
   server with gates off. Impact: wrong-patient handoffs sent, cross-patient disclosures,
   unconfirmed and duplicate sends (see `evals/results/results.md`).
2. **Patch.** Gates on: session scope, patient match, clinician token, version and idempotency.
3. **Re-test.** `python -m evals.run_eval --configs C4 --check` shows 0 on every safety metric,
   and CI fails if that regresses.

## Residual risks (not mitigated)

- HMAC keys live in process environment variables. A production system would use an identity
  provider (SMART on FHIR / OAuth 2.1) and a KMS.
- The injection screen is regex-based and will miss paraphrased attacks. The real defence is
  structural: nothing an injection can make the model do is enough to send a handoff.
- The simulated clinician approves whatever it is shown. Real approval quality (automation bias)
  is a human-factors question this prototype cannot measure.
- Structural validation uses `fhir.resources` R4B models rather than the official HL7 Java validator.
