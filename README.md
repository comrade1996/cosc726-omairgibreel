# COSC726 - Agentic Artificial Intelligence

Weekly coursework repository for Omair Gibreel. 

## Repository structure

```text
cosc726-omairgibreel/
|-- week01/
|-- week02/
|-- week03/
|-- week04/
|-- week05/
|-- .github/workflows/
|-- .gitignore
|-- README.md
`-- requirements.txt
```


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

Each weekly folder contains its own README and requirements file. Weeks 1-4 are
complete. Week 5 contains the MCP ambulance handoff project proposal using HL7
FHIR. Later weeks are added in separate commits.
