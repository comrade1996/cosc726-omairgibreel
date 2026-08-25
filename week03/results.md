# Week 3 Results

The same twelve fixtures and four validation gates were used for every run.

| Technique | Parse | Schema | Fields | False fill | Safety | Tokens/call | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| A - naive | 17% | 17% | 100%* | 0%* | Fail | 192 | 420 ms |
| B - system | 100% | 67% | 85% | 17% | Fail | 352 | 500 ms |
| C - few-shot | 100% | 92% | 92% | 8% | OK | 612 | 610 ms |
| D - reasoning | 100% | 100% | 96% | 8% | OK | 462 | 1,850 ms |
| E - schema-constrained | 100% | 100% | 96% | 8% | OK | 357 | 540 ms |

\*The naive field score and false-fill score are misleading because ten of its
twelve responses do not parse. The simulator still holds the correct payload
inside prose, but a real caller cannot safely consume it.

Every technique still fabricates `A1102` on fixture E11. It matches the schema,
but Gate 3 rejects it because that order does not exist.
