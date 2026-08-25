# Decision Memo

## What changed

A is a one-sentence baseline. B adds the agent identity, one-email scope,
checkable safety rules, and an exact JSON contract. C keeps B and adds three
invented examples for missing values, a compound request with no order ID, and
the rare `other` intent. D keeps B but adds named checks for the delay, policy,
action, and evidence. E uses the same words as B and changes only the decoder by
enforcing the schema.

## What moved

B fixed parsing, taking it from 17% to 100%, but its schema rate was only 67%
and it still had a safety failure. C removed the safety failure, raised schema
validity to 92%, and raised field accuracy from 85% to 92%. D and E both reached
100% schema validity and 96% field accuracy. D did not improve quality over E,
but it used 462 tokens and 1,850 ms per call. E used 357 tokens and 540 ms.

## What I would ship

I would ship E, the schema-constrained version, behind all four validation
gates. It matched D's quality with 105 fewer tokens per call and about one third
of the latency. I would also log gate failures and route rejected cases to a
human instead of repairing them silently.

## What still fails

Fixture E11 remains wrong for C, D, and E. The output invents `A1102`, which is
well formed but is not a real order. Gate 2 cannot catch that because a schema
checks shape, not existence. Gate 3 catches it by checking the order system.

## Revert conditions

I would reconsider this choice if the production provider did not support
strict schema decoding, if schema enforcement added unacceptable latency, or if
a larger real-model evaluation showed more semantic errors than the few-shot
version. Any unsupported completed-action claim would block release immediately.

## What this did not measure

This was a deterministic simulator with twelve hand-written fixtures, not a
production model. The labels came from one author, so there was no
inter-annotator agreement. One Arabic email cannot support a claim about broad
multilingual performance. The test also did not measure prompt changes over
time, provider failures, real cost, concurrency, or attacks beyond the included
injection examples. Before production I would use a larger independently
labelled test set, real pinned model versions, multiple languages, and live
latency and cost measurements.
