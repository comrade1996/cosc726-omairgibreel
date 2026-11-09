# COSC726 Agentic AI project: MCP Ambulance Handoff Gateway (HL7 FHIR R4)

Omair Gibreel - Team ID `OmairGibreel` (individual) - domain: **health**

- **Demo video (unlisted):** https://youtu.be/c-H_Bv4VonE
- **Report:** `COSC726_Project_OmairGibreel_Report.pdf` (submitted separately; source in `report/`)

## 1. What it does

When an ambulance crew hands a patient over to an emergency department (ED), facts get lost, re-keyed or
attached to the wrong patient. In this project an AI agent prepares that handoff through a
**Model Context Protocol (MCP)** server. The server maps a synthetic NEMSIS-style ambulance record to an
**HL7 FHIR R4** document Bundle, validates it, matches the patient, checks completeness, and builds a
grounded MIST/SBAR draft. The agent escalates gaps to the crew. A **human clinician must approve** the
exact draft before anything is marked as sent; the model never holds the key that allows this.

All patients are synthetic (Synthea). The system does not diagnose, recommend treatment, calculate
doses, choose a destination or dispatch.

## 2. Prerequisites

- **Python 3.11 or newer** and **Git**. That is all you need for the run, the tests and the evaluation.
  The default agent is a deterministic offline policy (`mock`), so there is no GPU, no account and no API key.
- **Optional real model:** [Ollama](https://ollama.com) with `qwen2.5:7b-instruct` (snapshot digest
  `2bada8a74506`). This is a one-off download of about **4.7 GB**, taking roughly 5-10 minutes. On a laptop
  each case then takes 30-140 s. Alternatively, use any OpenAI-compatible hosted endpoint.

## 3. Install

```bash
git clone https://github.com/comrade1996/cosc726-omairgibreel.git
cd cosc726-omairgibreel
python3 -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 4. Configure

You need no configuration for the default run. A `.env` file is only needed to use a real LLM:

```bash
cp .env.example .env
```

Two variables switch the model provider:

- `LLM_BASE_URL`: the endpoint. The default is local Ollama at `http://127.0.0.1:11434/v1`; use
  `https://api.openai.com/v1` for a hosted provider.
- `LLM_MODEL`: the model name, for example `qwen2.5:7b-instruct`.

Add `LLM_API_KEY` for hosted providers. Set `AGENT_MODEL=openai`, or pass `--model openai`, so the agent
uses that model instead of `mock`. `.env` is git-ignored and has never been committed; only
`.env.example` is tracked.

## 5. Run

```bash
python -m project.agent.host --case AMB-001
```

When it works you see the following:
1. `Connected over stdio as CREW-A. Discovered 7 tools, 5 resources, 3 prompts.`
2. A `THINK / ACT / OBS` trace: get case, validate, completeness, draft.
3. The **clinician approval screen** showing the draft, ending `Approve sending this handoff? [y/N]`.
4. Type `y`. You then see `status: sent`, a simulated ED acknowledgement, and
   `Stop reason: final_answer` followed by an audit trail ending in `confirm_handoff:ok, record_ed_acknowledgement:ok`.

## 6. Test

```bash
python -m pytest -q tests
```

Expected output: `151 passed` in about 5 seconds. The tests need **no API key and no network**: they use
the offline mock model and in-process or localhost MCP servers. Token counting falls back to a chars/4
estimate if `tiktoken` cannot download its vocabulary.

## 7. A worked example

**Input:** case `AMB-019`, a stroke-symptoms call whose record has no SpO2.

```bash
python -m project.agent.host --case AMB-019 --approve auto
```

**Output (correct run):**

```
[3] OBS   {"ok": true, "stop_condition": "blocked_incomplete", "missing": ["vitals.spo2"]}
[4] FINAL
Handoff AMB-019 NOT sent (blocked_incomplete). Issues: none. Missing (crew must supply): vitals.spo2.
```

No approval is requested and nothing is estimated. If you see `sent`, or a made-up SpO2 value, the run is
broken. For the controlled failure and recovery, run
`python -m project.agent.host --case AMB-001 --model faulty --approve auto`. It should end with
`critic rejections 1 | unknown-tool calls 1` and a correct send.

## 8. Reproduce the evaluation

```bash
python -m evals.run_eval --check
```

This runs 40 cases through 4 configurations in about 30 s and prints the table in
`evals/results/results.md`, ending with `All thresholds met.`. The numbers match Table 1 of the report.
The headline rows are:

| Metric | C1 custom JSON | C2 FHIR, no gates | C3 MCP, no gates | C4 secured MCP |
|---|---|---|---|---|
| Safe-block rate | 0.250 | 0.875 | 0.875 | 1.000 |
| Missing-field recall | 0.533 | 1.000 | 1.000 | 1.000 |
| Wrong-patient handoffs sent | 2 | 2 | 2 | 0 |
| Unconfirmed / duplicate sends | 2 / 4 | 2 / 4 | 2 / 4 | 0 / 0 |
| Attacks blocked | 0/7 | 2/7 | 2/7 | 7/7 |

Latency values vary slightly by machine. The real-LLM results (Table 2) come from
`python -m evals.run_llm_eval`, which needs Ollama and takes about an hour for 40 cases on a laptop.
Its output is in `evals/results/llm/`.

## 9. The approval gate

- **Where it lives:** the consequential tool is `confirm_handoff` (`project/server.py`). The server enforces
  it in `HandoffService.confirm` (`project/service.py`). The human gate is `ApprovalGate` in
  `project/agent/host.py`, and it is the only component that holds the approval signing key.
- **How to trigger it:** `python -m project.agent.host --case AMB-001`. Use any complete case, AMB-001 to AMB-018.
- **What the reviewer sees:** the server-built MIST draft, not the model's prose. It shows every line with
  values, units and times, the provisional impression, allergies, any withheld narrative, and the case
  version, receiving organisation and draft hash. Answering `y` mints a token bound to that exact draft;
  `n` gives `NOT sent: clinician_declined`.
- **What it blocks:** a forged string such as `approved-by-system` is rejected with
  `clinician_confirmation_invalid`, and so is a stale or replayed approval.

## 10. Repository map

| Directory | What lives there |
|---|---|
| `project/` | MCP server, `HandoffService`, FHIR mapper, validator, completeness, security, audit, draft builder |
| `project/agent/` | MCP host: ReAct loop, approval gate, critic, task-scope guard, ModelClient seam (mock, faulty, openai) |
| `project/data/` | 20 Synthea patients, 40 labelled cases, NEMSIS field list, NEMSIS-to-FHIR `mapping_v1.csv` |
| `project/prompts/` | Versioned agent system prompt |
| `evals/` | Evaluation harness (4 configurations), real-LLM evaluation, thresholds, `results/` |
| `tests/` | 151 offline tests: pipeline, security gates, MCP over stdio and HTTP |
| `scripts/` | Dataset rebuild (`select_synthea.py`, `build_cases.py`) and `dev_session.py` for MCP Inspector |
| `docs/` | Threat model mapped to the OWASP Top 10 for Agentic Applications (ASI01-ASI10) |
| `notebooks/` | Google Colab run-through |
| `report/` | Report source and builder, figures, slides and demo-video tooling |
| `week01/`-`week05/` | Weekly labs (the proposal is in `week05/`) |
| `.github/workflows/` | CI: labs, tests and the threshold-gated evaluation |

## 11. Limitations

- **Synthetic, template-generated data.** It has not been tested on messy real ePCR exports. Do not use it
  with real patients; it is not a medical device.
- **Simulated clinician.** The simulated clinician approves whatever it is shown, so automation bias
  (rubber-stamping) is not measured.
- **Strict identity matching.** Patient matching is exact (MRN, date of birth, sex, family name), so
  legitimate records with typos are blocked and need a human reconciliation path.
- **Weak real-model completion.** A 7B local model completes only 75% of the handoffs it should. It
  sometimes stops after drafting despite the critic: the result is safe, but nothing is sent.
- **Heuristic injection screen.** The regex screen can be evaded. The defence is structural: nothing the
  model is persuaded to do can send a handoff.
- **Prototype security.** HMAC keys live in environment variables. Production would need SMART on FHIR or
  OAuth scopes, a KMS, and the official HL7 validator.

**What would break it:** running the server with `AMBULANCE_GATES=off` (ablation only, and refused for
HTTP); sharing the approval key with the model process; or a host that skips the approval gate. The
server would still reject a missing token, but a host that mints tokens without a human defeats the oversight.

## More

- **Second MCP client over HTTP:** `python -m project.http_client --spawn --case AMB-002` (401/401/403 security probe, then an SBAR handoff).
- **Cross-crew denial:** `python -m project.agent.host --case AMB-001 --crew CREW-B --approve auto`.
- **MCP Inspector:** `python scripts/dev_session.py env --crew CREW-A`, then `npx @modelcontextprotocol/inspector -e ... python -m project.server`.
- **Rebuild the report, slides or video** (macOS, needs pandoc and Chrome): `python report/build_report.py --video-url <url>`, `report/presentation/`, `report/video/`.

## Licence and acknowledgements

Code: MIT licence (`LICENSE`). Third-party code and data:

- **Synthea** synthetic patients (Apache 2.0; MITRE, synthea_sample_data_fhir_r4_nov2021).
- **NEMSIS v3.5.0** data dictionary: element definitions only, no data.
- **HL7 FHIR R4** specification.
- **MCP Python SDK** (MIT).
- **fhir.resources** (BSD).
- **tiktoken** (MIT).
- **Qwen2.5** (Apache 2.0).

Developed with an AI coding assistant (Devin); see Appendix B of the report and the commit trailers.
