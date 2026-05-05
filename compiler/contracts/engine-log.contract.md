# Engine Log Contract v1

## Purpose

Defines a normalized JSON shape for execution and QA evidence emitted by:

- Clinical IR reference interpreter
- DMN-imported IR comparison
- generated XLSForm runtime
- Z3 evaluation
- comparison harness

Use this contract for stored QA evidence, bundle artifacts, and cross-engine review.

## Accepted Format

- JSON

## Log Types

Recommended top-level `log_type` values:

- `interpreter_evaluation`
- `dmn_evaluation`
- `xlsform_evaluation`
- `z3_evaluation`
- `comparison_report`
- `z3_checks`

## Common Envelope

```json
{
  "log_type": "comparison_report",
  "contract_version": 1,
  "guideline_id": "pneumonia_catalog_demo",
  "generated_at": "2026-05-01T13:00:00Z",
  "compiler_version": "local-dev",
  "source_artifacts": {},
  "results": []
}
```

## Required Envelope Fields

- `log_type`
- `contract_version`
- `guideline_id`
- `generated_at`
- `results`

## Recommended Envelope Fields

- `compiler_version`
- `source_artifacts`
- `provenance`

All provenance in engine logs should use structured provenance objects matching the same `source_id / kind / location / row / page / section / note` pattern used elsewhere in the contracts.

## Source Artifact Shape

```json
{
  "source_artifacts": {
    "ir_path": "generated/catalog_demo/pneumonia.full.ir.json",
    "dmn_path": "examples/pneumonia.dmn",
    "patient_path": "examples/pneumonia.cases.json",
    "smt2_path": "generated/test_artifacts/pneumonia.smt2"
  }
}
```

## Comparison Result Shape

Each item in `results` should follow this shape:

```json
{
  "name": "home_treatment_case",
  "ok": true,
  "inputs": {
    "v_age_months": 12,
    "v_resp_rate": 40,
    "v_danger_sign": false
  },
  "missing": [],
  "interpreter_predicates": {
    "p_danger_sign": false,
    "p_fast_breathing": true
  },
  "interpreter_outputs": {
    "o_referral": false,
    "o_home_treatment": true,
    "o_no_action": false
  },
  "interpreter_rule_hits": {
    "r1": false,
    "r2": true,
    "r3": false
  },
  "dmn_predicates": {
    "p_danger_sign": false,
    "p_fast_breathing": true
  },
  "dmn_outputs": {
    "o_referral": false,
    "o_home_treatment": true,
    "o_no_action": false
  },
  "dmn_rule_hits": {
    "r1": false,
    "r2": true,
    "r3": false
  },
  "xlsform_predicates": {
    "p_danger_sign": false,
    "p_fast_breathing": true
  },
  "xlsform_outputs": {
    "o_referral": false,
    "o_home_treatment": true,
    "o_no_action": false
  },
  "xlsform_rule_hits": {
    "r1": false,
    "r2": true,
    "r3": false
  },
  "z3_predicates": {
    "p_danger_sign": false,
    "p_fast_breathing": true
  },
  "z3_outputs": {
    "o_referral": false,
    "o_home_treatment": true,
    "o_no_action": false
  },
  "z3_rule_hits": {
    "r1": false,
    "r2": true,
    "r3": false
  },
  "mismatches": []
}
```

## Mismatch Shape

Recommended mismatch entries:

```json
[
  {
    "field": "o_home_treatment",
    "category": "output",
    "expected_engine": "interpreter",
    "actual_engine": "xlsform",
    "expected_value": true,
    "actual_value": false
  }
]
```

## Z3 Check Result Shape

For `log_type = "z3_checks"`, each `results` item should look like:

```json
{
  "category": "rule_reachability",
  "target": "r2",
  "ok": true,
  "message": "rule is reachable",
  "witness": {
    "values": {
      "v_age_months": 12,
      "v_resp_rate": 40,
      "v_danger_sign": false
    },
    "missing": []
  }
}
```

## Required Semantics

- logs must preserve the case `name` when present
- `ok=false` means at least one clinically relevant mismatch or failure was detected
- `mismatches` should be explicit; do not force readers to diff engine payloads by hand
- missing inputs should be represented in a `missing` list, not by silently coercing values

If a case includes EHR/history-fed values such as `v_weight_kg_h`, the log should preserve them exactly under the normal input payload rather than moving them into a special side channel.

## Provenance

Recommended envelope provenance:

```json
[
  {
    "source_id": "BUNDLE_20260501_1300",
    "kind": "qa_run",
    "note": "comparison run for pneumonia bundle"
  }
]
```
