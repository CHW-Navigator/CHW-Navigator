# Predicate Catalog Contract v1

## Purpose

Defines normalized clinical Boolean logic over variables and previously defined predicates.

## Accepted Source Formats

- CSV
- JSON

## Identifier Rules

- predicate IDs must start with `p_`
- `inputs_used` should list only variable IDs
- expressions may reference:
  - `v_`
  - `st_`
  - `c_`
  - `p_`
  - `o_`

EHR/history-fed variables should still use the normal variable families and may carry an `_h` suffix, for example:

- `v_weight_kg_h`
- `v_last_hb_h`
- `st_prev_referral_h`

## Required Fields

- `id`
- `description`
- `inputs_used`
- `expression`
- `missingness_policy`
- `provenance`

## Optional Fields

- `formal_definition`

## Missingness Policies

- `require_inputs`
- `treat_missing_as_false`
- `propagate_unknown`

## Canonical Expression Contract

The compiler treats the structured AST as authoritative.

Supported expression kinds:

- `literal`
- `var`
- `const`
- `pred`
- `output`
- `and`
- `or`
- `not`
- `if`
- `=`
- `!=`
- `<`
- `<=`
- `>`
- `>=`
- `+`
- `-`
- `*`
- `/`
- `selected`
- `else`

## JSON Shape

```json
{
  "predicates": [
    {
      "id": "p_fast_breathing",
      "description": "Fast breathing by age band",
      "inputs_used": ["v_age_months", "v_resp_rate"],
      "expression": {
        "kind": "or",
        "args": [
          {
            "kind": "and",
            "args": [
              {
                "kind": "<",
                "left": { "kind": "var", "id": "v_age_months" },
                "right": { "kind": "literal", "value": 12 }
              },
              {
                "kind": ">=",
                "left": { "kind": "var", "id": "v_resp_rate" },
                "right": { "kind": "literal", "value": 50 }
              }
            ]
          },
          {
            "kind": "and",
            "args": [
              {
                "kind": ">=",
                "left": { "kind": "var", "id": "v_age_months" },
                "right": { "kind": "literal", "value": 12 }
              },
              {
                "kind": ">=",
                "left": { "kind": "var", "id": "v_resp_rate" },
                "right": { "kind": "literal", "value": 40 }
              }
            ]
          }
        ]
      },
      "formal_definition": "((v_age_months < 12 and v_resp_rate >= 50) or (v_age_months >= 12 and v_resp_rate >= 40))",
      "missingness_policy": "require_inputs",
      "provenance": [
        {
          "source_id": "MOH_GUIDE_2026",
          "kind": "predicate_table",
          "location": "row:7"
        }
      ]
    }
  ]
}
```

## CSV Columns

Required columns:

- `id`
- `description`
- `inputs_used`
- `expression_json`
- `missingness_policy`
- `provenance_source_id`

Optional columns:

- `formal_definition`
- `provenance_kind`
- `provenance_location`
- `provenance_row`
- `provenance_column`
- `provenance_table`
- `provenance_page`
- `provenance_section`
- `provenance_note`

## CSV Example

```csv
id,description,inputs_used,expression_json,missingness_policy,formal_definition,provenance_source_id,provenance_kind,provenance_location
p_danger_sign,Danger sign present,"[""v_danger_sign""]","{""kind"": ""var"", ""id"": ""v_danger_sign""}",require_inputs,v_danger_sign,MOH_GUIDE_2026,predicate_table,row:1
```

## Provenance

Predicate rows must use structured provenance objects or structured provenance columns, not a free-text citation blob. The required shape matches the `ProvenanceRecord` pattern used across the compiler:

```json
[
  {
    "source_id": "MOH_GUIDE_2026",
    "kind": "predicate_table",
    "page": 18,
    "section": "Respiratory assessment",
    "row": 7,
    "note": "Fast-breathing threshold by age band"
  }
]
```

## Staging String Grammar

If teams maintain a human-readable string grammar upstream, keep it as audit text or parser input only.

Recommended string subset:

- lowercase operators only
- identifiers must use approved prefixes
- support only:
  - `and`
  - `or`
  - `not`
  - `=`
  - `!=`
  - `<`
  - `<=`
  - `>`
  - `>=`
  - `+`
  - `-`
  - `*`
  - `/`
  - `if(cond, a, b)`
  - `selected(x, 'choice')`

## Important Non-Rules

- do not auto-deduplicate predicates by name shape
- do not treat `formal_definition` as executable semantics
- do not put variable units or variable domains here as canonical fields
