# Variable Catalog Contract v1

## Purpose

Defines encounter variables and scalar state variables that may be referenced by predicates, DMN inputs, XLSForm questions, and patient cases.

## Accepted Source Formats

- CSV
- JSON

## Identifier Rules

- encounter variables must start with `v_`
- scalar state variables must start with `st_`
- numeric and measured variables should include the stored unit in the identifier when practical, for example:
  - `v_weight_g`
  - `v_temp_c_x10`
  - `v_height_mm`
  - `v_waz_x10`
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
- `storage_unit`
- `input_decimals`
- `display_decimals`
- `remeasure_min`
- `remeasure_max`
- `dont_allow_min`
- `dont_allow_max`
- `measurement_limits`

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
      "measurement_limits": {
        "remeasure_min": 0,
        "remeasure_max": 120,
        "dont_allow_min": 0,
        "dont_allow_max": 3650,
        "source": "moh_optional"
      },
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
- `storage_unit`
- `input_decimals`
- `display_decimals`
- `remeasure_min`
- `remeasure_max`
- `dont_allow_min`
- `dont_allow_max`
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
id,type,domain_min,domain_max,unit,remeasure_min,remeasure_max,dont_allow_min,dont_allow_max,allowed_missingness,multivalue,provenance_source_id,provenance_kind,provenance_location
v_age_months,int,0,120,months,0,120,0,3650,false,false,MOH_GUIDE_2026,variable_catalog,row:1
v_temp_c_x10,int,250,450,tenths_c,355,400,250,450,false,false,MOH_GUIDE_2026,variable_catalog,row:2
st_fever_done,bool,,,,,,,,false,false,MOH_GUIDE_2026,state_catalog,row:8
```

## Semantics

- `allowed_missingness=false` means the field is expected to be present at collection time unless logic or workflow says otherwise.
- `allowed_missingness=true` means the field may be omitted, but downstream predicate and decision logic must handle that safely.
- `unit` belongs here, not on predicates.
- `domain` defines the proof / representational domain used by the compiler and formal tooling, including Z3.
- `storage_unit` may be used to document the stored unit explicitly when teams want a separate machine-readable field in addition to the unit-bearing identifier.
- `input_decimals` documents how much precision a data-entry UI may accept.
- `display_decimals` documents how much precision summary UIs may display without changing stored logic values.
- `remeasure_*` values are optional MOH-supplied quality thresholds that suggest the user should measure again before trusting the value.
- `dont_allow_*` values are optional wider hard-stop thresholds beyond which the application should reject the entry rather than continue.
- `remeasure_*` and `dont_allow_*` are authoring and validation metadata, not replacements for the compiler's formal proof domain.
- If MOH does not supply these thresholds, the variable catalog may omit them.

## Recommended Z3 / Proof Domains

These are recommended broad domains for formal verification, not tight clinical-normal ranges.

| Variable family | Internal representation | Recommended domain |
| --- | --- | --- |
| temperature | integer tenths °C, e.g. `v_temp_c_x10` | `250..450` |
| respiratory rate | integer breaths/min | `0..250` |
| weight | integer grams | `50..200000` |
| weight | integer `kg x 100` | `5..20000` |
| length/height | integer mm | `200..2500` |
| age | integer days | `0..3650` |
| symptom duration | integer days | `0..3650` |
| stools/day | integer count | `0..100` |
| vomits/day | integer count | `0..100` |
| MUAC | integer mm | `50..300` |
| SpO₂ | integer percent | `0..100` |
| WAZ | integer tenths z-score | `-100..100` |
| HAZ | integer tenths z-score | `-100..100` |
| WHZ/WLZ | integer tenths z-score | `-100..100` |
| BAZ | integer tenths z-score | `-100..100` |

Guidance:

- keep domains broad enough to include bad-but-possible inputs
- do not use WHO re-measurement/data-quality flags as proof-domain limits
- validation limits and clinical decision logic should remain separate from the proof domain

## Measurement Limits

Recommended JSON shape when a variable uses MOH-supplied measurement thresholds:

```json
{
  "measurement_limits": {
    "remeasure_min": 355,
    "remeasure_max": 400,
    "dont_allow_min": 250,
    "dont_allow_max": 450,
    "source": "moh_optional"
  }
}
```

Recommended interpretation:

- values inside `remeasure_*` bounds can proceed normally
- values outside `remeasure_*` but inside `dont_allow_*` should trigger a re-measure prompt or warning
- values outside `dont_allow_*` should be rejected at data-entry time

Cross-cutting rules:

- these thresholds are optional and should be requested from MOH when available
- they should usually be present for continuous measurement variables
- they should not silently narrow the Z3 proof universe unless the formal domain is explicitly changed

## Storage Recommendations

Prefer stable integer storage for continuous clinical measurements used in logic or formal verification.

Examples:

- temperature: `v_temp_c_x10`
- weight: `v_weight_g` or `v_weight_kg_x100`
- length/height: `v_height_mm` or `v_height_cm_x10`
- z-scores: `v_waz_x10`, `v_haz_x10`, `v_whz_x10`
- day-serial dates used in logic: `v_visit_day`, `v_birth_day`

### Weight

Recommended internal storage:

- integer grams, for example `v_weight_g`
- or integer `kg x 100`, for example `v_weight_kg_x100`

Recommended user-input behavior:

- allow two decimal places (`0.01 kg`) for infant assessments when the data-entry interface collects kilograms

Recommended display behavior:

- round to one decimal place (`0.1 kg`) only in summary screens or labels where that rounding does not affect safety

Rationale:

- avoid floating-point drift in Z3 and form runtimes
- keep stored units explicit in the variable identifier
- keep computation precision separate from display precision

### DOB and Visit Date

Recommended current compiled path:

- store DOB and visit/as-of dates used in logic as integer day serials
- examples:
  - `v_birth_day`
  - `v_visit_day`

Recommended use:

- use helper expressions such as `date_diff_days(v_visit_day, v_birth_day)` and `age_months_from_date(v_visit_day, v_birth_day)` in predicates or derived logic
- treat the stored unit as `days` or `day_serial` explicitly in authoring notes if needed

Current limitation:

- the supported compiler path is numeric day serials, not free-form ISO date strings

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
