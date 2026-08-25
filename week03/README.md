# Week 3 - Prompt Engineering Portfolio

This assignment compares five prompt techniques on the same twelve support
emails. It runs offline with the supplied deterministic model, so no API key is
needed and the reported scores are reproducible.

## Files

- `lab2_prompt_portfolio.ipynb` - completed and executed Colab notebook
- `lab2_pydantic_colab.ipynb` - completed real-model Colab extension
- `triage.py` - prompts, validation gates, and portfolio runner
- `schema.py` - reusable Pydantic contract and semantic gates
- `lab2_kit.py` - supplied fixtures and deterministic model
- `prompts/` - five separately versioned prompt files
- `results.md` - measured comparison table
- `decision_memo.md` - answers to the six assessed questions
- `test_triage.py` - checks for the important validation behaviour

## Run

```bash
python -m pip install -r week03/requirements.txt
python week03/triage.py
python -m unittest week03.test_triage
```

For Google Colab, upload or clone the full repository, change into `week03`,
and use **Runtime > Run all**. The notebook relies only on local files in this
folder. The real-model extension downloads Qwen and should be run on a T4 GPU;
its scores can vary by library and model version.
