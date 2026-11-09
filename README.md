# COSC726 - Agentic AI project: MCP Ambulance Handoff Gateway (HL7 FHIR R4)

Omair Gibreel - COSC726 Agentic Artificial Intelligence

An agent prepares an ambulance-to-emergency-department handoff through a Model Context Protocol
(MCP) server. The server maps a synthetic NEMSIS-style ambulance record onto an HL7 FHIR R4 document
Bundle, validates it, checks completeness, and builds a grounded MIST/SBAR draft. A
**human clinician must approve** before anything is marked as sent. The model never holds the keys
that make that possible. All patients are synthetic (Synthea). The system does **not** diagnose,
recommend treatment, calculate doses, choose a destination or dispatch.

- Demo video (unlisted): **VIDEO_URL_PLACEHOLDER**
- Report: `COSC726_Project_OmairGibreel_Report.pdf` (submitted separately; source in `report/`)

## 1. Quick start (clean machine, about 3 minutes, no API key, no `.env`)

Requirements: **Python 3.11 or newer** and **Git**. Nothing else; no GPU and no account.

```bash
git clone https://github.com/comrade1996/cosc726-omairgibreel.git
cd cosc726-omairgibreel
python3 -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Then run these four commands. Each one is self-contained:

```bash
# 1. Agent prepares a handoff over MCP stdio; you are the clinician (answer y or n)
python -m project.agent.host --case AMB-001

# 2. Incomplete record: the agent escalates the gap instead of guessing (no approval asked)
python -m project.agent.host --case AMB-019 --approve auto

# 3. Controlled failure and recovery: hallucinated tool + invented BP are caught, then fixed
python -m project.agent.host --case AMB-001 --model faulty --approve auto

# 4. Tests (151) and the full evaluation (40 cases x 4 configurations), gated on thresholds
python -m pytest -q tests
python -m evals.run_eval --check
```

Expected: run 1 prints the THINK/ACT/OBS trace, shows the draft and asks
`Approve sending this handoff? [y/N]`. Answer `y` and you get `Stop reason: final_answer`
plus an audit trail ending `confirm_handoff:ok, record_ed_acknowledgement:ok`. Answer `n` and it
reports `NOT sent: clinician_declined`. Run 2 ends with `NOT sent (blocked_incomplete) ... vitals.spo2`.
Run 3 reports `critic rejections 1 | unknown-tool calls 1` and still sends correctly.
`run_eval --check` prints the results table and `All thresholds met.`
Traces are written to `project/runtime/traces/` and evaluation outputs to `evals/results/`.

## 2. What is in the box

| Path | What it is |
|---|---|
| `project/server.py` | MCP server: 7 tools, 5 resources, 3 prompts; stdio and Streamable HTTP |
| `project/service.py` | `HandoffService`: every gate (scope, patient match, approval, version, idempotency) |
| `project/mapper.py`, `validator.py`, `completeness.py`, `draft.py` | NEMSIS-style event to FHIR R4 Bundle, profile validation, MIST completeness, grounded drafts |
| `project/security.py`, `audit.py` | HMAC session and clinician tokens, patient matching, injection screen, redacted audit (FHIR AuditEvent view) |
| `project/agent/host.py` | MCP host: ReAct loop, approval gate, grounding/policy critic, turn/token budgets, loop and unknown-tool detection |
| `project/agent/model.py` | ModelClient seam: `mock` (offline default), `faulty` (fault injection), `openai` (any OpenAI-compatible endpoint) |
| `project/http_client.py` | Second, independent MCP client over Streamable HTTP with bearer auth |
| `project/data/` | 20 Synthea patients, 40 labelled cases, NEMSIS v3.5 field list, `mapping_v1.csv` |
| `evals/` | `run_eval.py` (4 configurations), `run_llm_eval.py` (real LLM), `thresholds.json`, `results/` |
| `tests/` | Pipeline, security and end-to-end MCP tests (stdio and HTTP) |
| `docs/threat_model.md` | OWASP Agentic Top 10 (ASI01-ASI10) mapping and red-team procedure |
| `notebooks/COSC726_Project_Demo_Colab.ipynb` | Google Colab run-through |
| `weekNN/` | Weekly labs 1-5 (the proposal is in `week05/`) |

MCP capabilities:
- **Tools:** `list_assigned_cases`, `get_ambulance_case`, `validate_fhir_bundle`,
  `check_handoff_completeness`, `create_handoff_draft`, `confirm_handoff` (consequential),
  `record_ed_acknowledgement`.
- **Resources:** `ambulance://cases/{id}/source|fhir|validation|audit` and `ambulance://profiles/handoff-r4`.
- **Prompts:** `prepare_mist_handoff`, `prepare_sbar_handoff`, `explain_validation_failure`.

## 3. More ways to run it

**Streamable HTTP and a second client.** This starts a localhost server with fresh keys and runs
a scripted SBAR handoff. It first shows that a missing token gets 401, a forged token gets 401 and a
foreign Origin gets 403:

```bash
python -m project.http_client --spawn --case AMB-002
```

**Cross-crew access denial.** The CREW-B session asks for a CREW-A case and gets `forbidden`,
which is audited:

```bash
python -m project.agent.host --case AMB-001 --crew CREW-B --approve auto
```

**Real LLM (local open-weight model, no key).** This follows the course labs.
Install [Ollama](https://ollama.com), then:

```bash
ollama pull qwen2.5:7b-instruct
cp .env.example .env                 # defaults already point at http://127.0.0.1:11434/v1
python -m project.agent.host --case AMB-001 --model openai
python -m evals.run_llm_eval         # 40 cases with the LLM as agent + RQ3 probe (slow on CPU)
```

Any OpenAI-compatible hosted endpoint works through `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY`
in `.env`. Never commit `.env`; it is git-ignored and only `.env.example` is tracked.

**MCP Inspector (third-party client).** Requires Node.js.

```bash
python scripts/dev_session.py env --crew CREW-A     # prints AMBULANCE_* variables
npx @modelcontextprotocol/inspector -e AMBULANCE_SESSION_KEY=... -e AMBULANCE_APPROVAL_KEY=... \
    -e AMBULANCE_SESSION_TOKEN=... python -m project.server
```

**Google Colab.** Open `notebooks/COSC726_Project_Demo_Colab.ipynb`, then choose
Runtime > Run all.

**Rebuild the report and demo video (optional; macOS, needs pandoc and Google Chrome).** Every
number in the report is filled in from `evals/results/`:

```bash
python report/build_report.py --video-url https://youtu.be/<id>
bash report/video/capture.sh /tmp/vid
python -m pip install imageio-ffmpeg==0.6.0
python report/video/build_video.py --captures /tmp/vid --out demo.mp4
```

**Rebuild the dataset (optional; outputs are committed).**
`python scripts/select_synthea.py` re-downloads the pinned Synthea archive (85 MB, hash-checked).
`python scripts/build_cases.py` regenerates the 40 cases deterministically.

## 4. Evaluation at a glance

`python -m evals.run_eval` runs every case through four configurations:

1. custom JSON processed by direct Python functions;
2. FHIR mapping and validation without MCP;
3. MCP plus FHIR with the gates off;
4. secured MCP plus FHIR with all gates on.

Each case has a capability phase (a well-behaved agent) and an attack phase (a compromised driver
replaying the case's attack). The current numbers are in `evals/results/results.md`. The real-LLM
results are in `evals/results/llm/llm_results.md`. CI (`.github/workflows/lab0.yml`) runs the tests
and `run_eval --check`, so a safety regression fails the build.

## 5. Data and responsible use

- **Synthetic only.** 20 patients from the Synthea FHIR R4 sample (nov2021, SHA-256 pinned),
  minimised to identity, active disorders and allergies. Ambulance events are generated from
  versioned templates. NEMSIS v3.5.0 is used for field definitions only; no NEMSIS data is used.
  Codes and doses in the templates are illustrative, not clinical guidance.
- **Human authority.** Only the host's clinician approval gate can mint the token that
  `confirm_handoff` requires. That token is bound to the case version, the draft hash and the
  receiving organisation.
- **Not a medical device.** This is a research prototype for a university module. Do not use it
  with real patient data.
- **AI assistance.** Parts of this repository were developed with an AI coding assistant (Devin).
  See the commit trailers and the declaration in the report.

## 6. Troubleshooting

- `python3: command not found` or version below 3.11: install Python 3.11+ from python.org. On
  Windows use `py -3.11 -m venv .venv`.
- `AMBULANCE_SESSION_KEY is not set` when running `python -m project.server` directly: the server
  is meant to be launched by a host. Use the commands above, or `scripts/dev_session.py env`.
- Token counts use `tiktoken`. With no internet access on first run it falls back to a
  chars/4 estimate, and the results header says which tokenizer was used.
