# Predeclared registry-match evaluation

`registry_match_evaluation.py` is a safety evaluator for the two AI stages:

1. a registry-blind extractor reads a manual; then
2. a registry-visible matcher proposes `unique_match`, `ambiguous`,
   `no_match`, or `needs_clarification`.

It is a **PILOT: NO CLINICAL USE** tool. It cannot approve a catalogue,
clinical pathway, binding, release, or deployment.

## Included frozen matrix

The bundled plan has 36 synthetic mini-manuals: four each for positive,
clarification, no-match, ambiguity, and adversarial cases; plus sixteen cases
that expose missing registry semantics. It measures the two stages separately
and counts a false `unique_match` separately from ordinary errors.

The included adapter is a recorded perfect replay that tests the evaluator,
not an AI model. Its 36/36 result is therefore **not** an accuracy estimate.
It is evidence E2 only for the recorded mechanics. A real run must inject a
model adapter and retain its model identity, prompts, requests, raw responses,
timestamps, and frozen plan digest before anyone interprets its results.

## Finding and contract work

The matrix reports four required semantics:

- parameter value sets;
- parameter requiredness;
- parameter ownership; and
- reference-data identity, version, and digest.

The first three already exist in governed data-concept records, but the
registry-visible catalogue does not yet project them and the current approved
tracer fixture has incomplete parameter-to-concept bindings. The fourth is not
represented by the governed capability contract at all.

The next registry revision must therefore be versioned, require complete
parameter concept bindings for an approved capability, project the three linked
concept facts into the read-only catalogue, and add a content-addressed
reference-data contract. It must preserve the current v2 tracer until the new
contract and migrations have independent tests. Do not patch these facts into
an AI prompt or use synthetic pilot values as production registry data.
