# Week 4 - ReAct Agent

This assignment builds the agent loop by hand: typed tool arguments, a JSON
step contract, validation gates, permission tiers, dispatch, explicit stop
conditions, audit output, and final-answer validation.

## Files

- `COSC726_W04_Lab3.ipynb` - completed Colab notebook and five exercises
- `hello_agent.py` - standalone deterministic agent and safety self-tests
- `prompts/system_prompt_v1.txt` - versioned system prompt
- `decision_memo.md` - assessed reflection
- `validation_results.md` - reproducible checks and saved model observation

## Run the deterministic checks

```bash
python -m pip install "pydantic>=2.7,<3"
python week04/hello_agent.py --self-test
python week04/hello_agent.py
```

## Run the real-model notebook

Open `COSC726_W04_Lab3.ipynb` in Google Colab, select a T4 GPU, and choose
**Runtime > Run all**. It downloads the pinned Qwen model and refreshes the
five assessed traces. No API key is required.
