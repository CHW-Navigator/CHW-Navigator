# Simulated Patient Data Contract v1

## Purpose

Defines the input cases used for:

- reference interpreter evaluation
- DMN comparison
- XLSForm runtime comparison
- Z3 witness replay
- regression and mutation tests

## Accepted Format

- JSON

## Top-Level Shapes

Either:

```json
[
  { "name": "case_1", "values": {}, "missing": [] }
]
```

or:

```json
{
  "cases": [
    { "name": "case_1", "values": {}, "missing": [] }
  ]
}
```

## Per-Case Required Fields

- `values`

## Per-Case Optional Fields

- `name`
- `missing`
- `expected_outputs`
- `expected_predicates`
- `expected_rule_hits`
- `tags`
- `provenance`

## Required Semantics

- `values` must be an object keyed by variable IDs such as `v_...` or `st_...`
- EHR/history-fed variables may use an `_h` suffix within those same families, for example `v_weight_kg_h` or `st_prev_referral_h`
- `missing` must be a list of variable IDs
- do not use `null` inside `values` to represent missingness
- if a variable is missing, include it in `missing`

## Recommended JSON Shape

```json
{
  "cases": [
    {
      "name": "home_treatment_case",
      "values": {
        "v_age_months": 12,
        "v_resp_rate": 40,
        "v_danger_sign": false
      },
      "missing": [],
      "expected_outputs": {
        "o_referral": false,
        "o_home_treatment": true,
        "o_no_action": false
      },
      "expected_predicates": {
        "p_danger_sign": false,
        "p_fast_breathing": true
      },
      "expected_rule_hits": {
        "r1": false,
        "r2": true,
        "r3": false
      },
      "tags": ["synthetic", "boundary", "pneumonia"],
      "provenance": [
        {
          "source_id": "TEST_SUITE_2026",
          "kind": "gold_case",
          "location": "pneumonia_set/case:2"
        }
      ]
    },
    {
      "name": "missing_resp_rate_case",
      "values": {
        "v_age_months": 6
      },
      "missing": ["v_resp_rate"],
      "tags": ["synthetic", "missingness"]
    }
  ]
}
```

## Field Semantics

- `expected_outputs` is optional and useful for clinician-approved gold cases
- `expected_predicates` is optional and useful for detailed drift checks
- `expected_rule_hits` is optional and useful when testing routing priority
- `tags` is optional and useful for grouping by module, risk, or generation method

## Generation Categories

Recommended tags for Z3-generated or synthetic cases:

- `z3_rule_witness`
- `z3_output_witness`
- `z3_overlap_probe`
- `boundary`
- `missingness`
- `gold_case`
- `mutation_probe`

## Naming Guidance

- prefer stable `name` values because comparison logs use them as anchors
- names should be unique within a file

## Provenance

When provenance is included on a case, use structured provenance objects in the same shape used elsewhere in the contracts. Do not use a single free-text citation string.
