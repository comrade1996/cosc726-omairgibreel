# Validation Results

The deterministic self-test checks the same controls without downloading a
language model:

- a shape-valid but nonexistent `A9999` is rejected by Gate 3;
- a credit request for an order one day late is rejected by Gate 4;
- the happy path stops at a pending approval and applies nothing;
- an unsupported final claim is rejected by Gate 5;
- an identical repeated tool call triggers the no-progress stop.

Result: `ALL SELF-TESTS PASSED`.

The saved Qwen 1.5B notebook run needed six fence/prose repairs and six retries,
with zero complete give-ups, during its initial trace. It also proposed the
illegal approval kind `late_delivery`; Pydantic rejected it before execution,
and the model recovered by escalating. These are observations from the saved
run, not a guarantee that a fresh Colab run will follow the same path.
