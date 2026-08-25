# Week 6 - Memory and Knowledge

This lab compares chunking and retrieval strategies, exposes policy search as a
tool, separates episodic/semantic/procedural memory, enforces two-user
isolation, and measures every layer with an ablation.

## Files

- `COSC726_W06_Lab5_colab.ipynb` - completed Colab notebook and saved table
- `layla_memory.py` - tool, stores, isolation test, and ablation harness
- `lab6_kit.py` - supplied corpus, vector-store adapter, stores, and fixtures
- `ablation_table.md` - measured comparison
- `decision_memo.md` - assessed analysis

## Offline safety checks

```bash
python week06/layla_memory.py --self-test
```

The self-test uses keyword retrieval and needs no external service. To reproduce
the full vector ablation, open the notebook in Google Colab and choose
**Runtime > Run all**. The setup installs Ollama, pulls `nomic-embed-text`, and
builds temporary Chroma collections. No API key is required.

For a local full run, install ChromaDB, start Ollama, pull
`nomic-embed-text`, then run:

```bash
python week06/layla_memory.py --ablation
```
