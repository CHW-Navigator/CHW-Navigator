# Variable Catalog Contract v1

## Purpose

Defines encounter variables and scalar state variables that may be referenced by predicates, DMN inputs, XLSForm questions, and patient cases.

## Accepted Source Formats

- CSV
- JSON

## Identifier Rules

- encounter variables must start with `v_`
- scalar state variables must start with `st_`
- EHR/history-fed values may use an `_h` suffix inside those same families, for example:
  - `v_weight_kg_h`
  - `v_last_hb_h`
  - `st_prev_referral_h`

## Required Fields

- `id`
- `type`
- `allowed_missingness`
- `multivalue`
- `provenance`

## Optional Fields

- `domain`
- `domain_min`
- `domain_max`
- `domain_values`
- `unit`

## Allowed Types

- `bool`
- `int`
- `decimal`
- `string`
- `string_key`
- `enum`

## Current Constraints

- `multivalue` must currently be `false`
- `enum` variables should define `domain.values`

## JSON Shape

```json
{
  "variables": [
    {
      "id": "v_age_months",
      "type": "int",
      "domain": { "min": 0, "max": 120 },
      "unit": "months",
      "allowed_missingness": false,
      "multivalue": false,
      "provenance": [
        {
          "source_id": "MOH_GUIDE_2026",
          "kind": "variable_catalog",
          "location": "row:1"
        }
      ]
    }
  ]
}
```

## CSV Columns

Required columns:

- `id`
- `type`
- `allowed_missingness`
- `multivalue`
- `provenance_source_id`

Optional columns:

- `domain`
- `domain_min`
- `domain_max`
- `domain_values`
- `unit`
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
id,type,domain_min,domain_max,unit,allowed_missingness,multivalue,provenance_source_id,provenance_kind,provenance_location
v_age_months,int,0,120,months,false,false,MOH_GUIDE_2026,variable_catalog,row:1
st_fever_done,bool,,,,false,false,MOH_GUIDE_2026,state_catalog,row:8
```

## Semantics

- `allowed_missingness=false` means the field is expected to be present at collection time unless logic or workflow says otherwise.
- `allowed_missingness=true` means the field may be omitted, but downstream predicate and decision logic must handle that safely.
- `unit` belongs here, not on predicates.

## Provenance

Use structured provenance, not free text:

```json
[
  {
    "source_id": "MOH_GUIDE_2026",
    "kind": "variable_catalog",
    "page": 12,
    "section": "Assessment variables",
    "row": 4
  }
]
```

Every variable row must carry structured provenance. Do not replace this with a single free-text citation field.
