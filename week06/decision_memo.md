# Decision Memo

## Which layer helped most

Recursive chunking improved keyword recall from 67% to 83% because sentences
kept policy facts together. Replacing recursive keyword search with embeddings
raised recall and the answer rate to 100%. Q5 was the clearest gain: the
question says “charged twice,” while the policy says “duplicate charges,” so a
lexical search has no useful shared phrase.

## Which layer made things worse

Parent-child retrieval kept the same 100% answer rate as recursive embeddings
but increased average context from 91 to 240 tokens. Episodic, semantic, and
procedural memory then raised it to 312 without moving the measured answer
rate. For this small policy question set, those layers were regressions. The
result does not mean they are always useless; it means the evaluator needs a
question that actually depends on each layer before paying its cost on every
request.

## Embeddings versus keywords

Embeddings beat the recursive keyword retriever on the paraphrased billing
question and improved overall recall by 17 percentage points. In production I
would keep a hybrid retriever: exact keyword or identifier matching for IDs and
policy names, vector search for paraphrases, and a reranker or minimum-score
rule before context reaches the model. I would evaluate retrieval separately
from answer quality so a confident wrong passage is visible.

## What episodic memory made possible

The policy document can say that repeated complaints require escalation, but it
cannot prove that this customer complained before. Episodic memory supplies the
two dated events and their outcomes. It makes “this is the second complaint in
60 days” checkable. The current ablation already awards Q6 from the general
policy text, so it understates this benefit and reveals a weakness in the
answer metric.

## Authorization

Every read and write carries a `MemoryScope`, and the store rejects a missing
user ID. The authenticated server, not the model, must construct that scope. A
model-controlled `user_id` would only turn a required field into an insecure
direct-object reference. I would enforce access in the store, repeat it at the
tool boundary, log the decision, and test cross-user reads and writes.

## What the measurement did not show

Five short policy documents are not a production corpus, and six questions
written by one person are only a smoke test. The answer checker looks for a
required word rather than judging a complete grounded response. The run used
one embedding model, `nomic-embed-text`; changing it changes vector dimensions,
requires a full re-index, and can change every number. The lab did not measure
index updates, long-term forgetting, concurrency, multilingual queries,
retrieval latency, malicious stored text, or whether two episodes are enough to
justify a permanent procedure.

The poisoning stretch also shows that scope is not provenance. An authorized
user can still store a false threshold. Learned facts need a trusted source,
validation, review state, and a way to revoke or supersede them.
