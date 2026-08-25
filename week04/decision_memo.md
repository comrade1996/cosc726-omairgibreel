# Decision Memo

## What I built

I built a ReAct-style support agent with four tools. Gate 1 checks that a tool
exists, Gate 2 validates its arguments with Pydantic, Gate 3 checks that an
order really exists, and Gate 4 requires both order evidence and the policy
before a credit approval can be requested. A separate permission check can
disable consequential tools. The controller also has a token budget, turn cap,
no-progress check, explicit stop reason, and a trace for every attempt.

## Which controls caught which failures

A malformed ID such as `1102` fails Gate 2. A well-shaped but invented `A1102`
fails Gate 3. A credit for the one-day-late order `A1080` fails Gate 4 even when
the model asks for it. The saved Qwen run used the illegal kind
`late_delivery`; Gate 2 blocked that call before it reached the tool. Repeated
calls and unfinished runs stop through controller limits rather than looping
forever.

## The missing control

The original four gates only guard tool calls. They do not stop the model from
writing “the refund was applied” in its final answer without calling any tool.
That is why I added Gate 5. It audits the answer against the trace immediately
before return and rejects unsupported action words. On rejection I would
escalate instead of silently rewriting a financial claim.

## Model contract failures

In the saved `Qwen/Qwen2.5-1.5B-Instruct` run, the repair counters were six
fence-or-prose failures, six retries, and zero complete give-ups. That is too
many corrections to treat raw model output as executable. A small model can be
useful here only because every step is parsed, validated, permission-checked,
and bounded before a tool runs.

## Remaining trust

The agent still relies on prompt text to decide whether billing is out of
scope. I would turn that into a routing gate. It also trusts that the order and
policy stores are current, and a real approval service would need authenticated
user identity, idempotency keys, rate limits, and an independent human approval
workflow.

## What the lab did not show

One 1.5B model has a different failure profile from a frontier model. Greedy
decoding makes a single session easier to compare but does not guarantee
reproducibility. The five emails were written by one person and each case was
run once, so there is no variance estimate, multilingual coverage, or reliable
production accuracy. The lab also did not test concurrent calls, tool outages,
hostile tool results, real authentication, or long conversations.
