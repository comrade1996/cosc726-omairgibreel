# Week 01 - Lab 0

## Engineering Baseline & Trace Literacy

This assignment verifies the Python/Git environment and demonstrates how to
classify and audit a deterministic agent trace. It requires no API key, model,
network service, or paid account.

## Files

- `lab0.ipynb` - executed guided notebook containing the environment checks,
  12-step trace classification, evidence audit, PEAS analysis, and decision
  memo.
- `COSC726_W01_hello_agent_mock.py` - deterministic trace simulator and
  annotation checker.
- `requirements.txt` - Week 1 dependency declaration.

## Requirements

- Python 3.11 or newer
- Git
- A virtual environment when running locally

From the repository root, install this week's requirements:

```bash
python -m pip install -r week01/requirements.txt
```

## Run and test

From the repository root:

```bash
python week01/COSC726_W01_hello_agent_mock.py --self-test
python week01/COSC726_W01_hello_agent_mock.py --check
python week01/COSC726_W01_hello_agent_mock.py --mock --fast
```

Expected results:

- Self-test: `TRACE SELF-TEST PASSED`
- Annotation check: `Score: 12/12`

Open `week01/lab0.ipynb` in Google Colab or Jupyter and run all cells from top
to bottom. The final readiness cell should print `READY TO SUBMIT`.

## Submission checkpoint

- Notebook: `week01/lab0.ipynb`
- Script: `week01/COSC726_W01_hello_agent_mock.py`
- Git tag: `week-01-complete`
- CI: the `Lab 0 checks` workflow must pass
