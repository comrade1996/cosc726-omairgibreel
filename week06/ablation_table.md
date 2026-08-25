# Week 6 Ablation

This is the saved run using ChromaDB and `nomic-embed-text`.

| Configuration | Recall | Precision | Answered | Avg. context tokens |
|---|---:|---:|---:|---:|
| No memory at all | 0% | 0% | 0% | 0 |
| Fixed + keyword | 67% | 33% | 67% | 88 |
| Recursive + keyword | 83% | 47% | 83% | 106 |
| Recursive + embeddings | 100% | 64% | 100% | 91 |
| Parent-child + embeddings | 100% | 64% | 100% | 240 |
| + episodic | 100% | 64% | 100% | 269 |
| + episodic + semantic | 100% | 64% | 100% | 278 |
| Everything | 100% | 64% | 100% | 312 |

The clearest quality gain came from recursive chunking and embeddings. The
parent-child and memory layers added context without improving this harness's
answer rate. That is a measured regression, not a reason to hide the rows.
