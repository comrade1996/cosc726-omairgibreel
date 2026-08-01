# COSC726 - Agentic Artificial Intelligence

Weekly coursework repository for Omair Gibreel. Each week is self-contained in
its own folder so a marker can clone this repository and reproduce the work.

## Repository structure

```text
cosc726-omairgibreel/
|-- week01/
|   |-- README.md
|   |-- requirements.txt
|   |-- lab0.ipynb
|   `-- COSC726_W01_hello_agent_mock.py
|-- .github/workflows/
|-- .gitignore
|-- README.md
`-- requirements.txt
```

Future assignments will use `week02/`, `week03/`, and so on.

## Setup

Python 3.11 or newer and Git are required. From the cloned repository:

```bash
python -m venv .venv
```

Activate the environment on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

Then install the repository requirements:

```bash
python -m pip install -r requirements.txt
```

## Weekly assignments

| Week | Assignment | Status | Instructions |
|---|---|---|---|
| 01 | Lab 0 - Engineering Baseline & Trace Literacy | Complete | [`week01/README.md`](week01/README.md) |

## Quick verification

```bash
python week01/COSC726_W01_hello_agent_mock.py --self-test
python week01/COSC726_W01_hello_agent_mock.py --check
```

Both commands must pass; the annotation checker must report `12/12`.
