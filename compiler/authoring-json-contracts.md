# Authoring Contracts

This document defines the current authoring contracts for teams preparing:

- DMN decision tables
- variable catalogs
- predicate catalogs
- phrase banks
- patient case data

It separates:

- what the compiler consumes today
- what upstream teams should author
- what is merely recommended rather than enforced

Authoring model:

- DMN decision tables + predicate catalog + variable catalog + phrase bank are the authored clinical source of truth
- Clinical IR is the canonical compiled representation generated from those sources
- every authoring contract should use structured provenance objects, not free-text provenance blobs
- EHR/history-fed fields should stay in the normal identifier families and may use an `_h` suffix such as `v_weight_kg_h` or `st_prev_referral_h`
- measured numeric variables should usually encode the stored unit in the identifier, such as `v_weight_g`, `v_temp_c_x10`, or `v_height_mm`

## What The Compiler Consumes Today

The current toolkit directly consumes:

- Clinical IR JSON
- variable catalog CSV or JSON
- predicate catalog CSV or JSON
- phrase bank CSV or JSON
- DMN XML
- patient case JSON

## Canonical Clinical IR Contract

The current compiler treats Clinical IR as the canonical compiled semantic contract.

Top-level shape:

```json
{
  "metadata": {},
  "variables": {},
  "constants": {},
  "predicates": {},
  "phrases": {},
  "decisions": {},
  "outputs": {},
  "invariants": {},
  "phrase_bindings": {}
}
```

Key identifier prefixes:

- `v_` for encounter-time variables
- `st_` for workflow or carry-forward state variables
- `c_` for constants
- `p_` for predicates
- `d_` for decisions
- `r...` for rules
- `o_` for outputs
- `i_` for invariants
- `m_` for phrase keys

EHR/history-fed fields can use an `_h` suffix inside the normal variable/state families, for example:

- `v_weight_kg_h`
- `v_last_hb_h`
- `st_prev_referral_h`

## Variable Catalog Contract

Recommended upstream JSON or CSV:

```json
{
  "variables": [
    {
      "id": "v_age_months",
      "type": "int",
      "domain": { "min": 0, "max": 120 },
      "unit": null,
      "measurement_limits": {
        "remeasure_min": 0,
        "remeasure_max": 120,
        "dont_allow_min": 0,
        "dont_allow_max": 3650
      },
      "allowed_missingness": false,
      "multivalue": false,
      "provenance": [
        { "source_id": "variable_catalog", "row": 1 }
      ]
    },
    {
      "id": "st_fever_done",
      "type": "bool",
      "allowed_missingness": false,
      "multivalue": false,
      "provenance": [
        { "source_id": "state_catalog", "row": 8 }
      ]
    }
  ]
}
```

Expected fields:

- `id`: required
- `type`: required
- `domain`: optional except recommended for numeric and enum variables
- `unit`: optional
- `measurement_limits`: optional
- `allowed_missingness`: required
- `multivalue`: required, but currently must be `false`
- `provenance`: required

Recommended optional `measurement_limits` fields for continuous variables:

- `remeasure_min`
- `remeasure_max`
- `dont_allow_min`
- `dont_allow_max`

Use these when MOH provides:

- a narrower "re-measure" band
- a wider "don't allow" hard-stop band

These are authoring/validation thresholds and should stay distinct from the compiler's formal proof domain.

Recommended storage rule for continuous variables:

- prefer scaled integers over floating point for values that drive logic or formal verification
- include the stored unit in the variable name when practical

Examples:

- `v_weight_g`
- `v_weight_kg_x100`
- `v_temp_c_x10`
- `v_waz_x10`

Weight recommendation:

- store internally as grams or `kg x 100`
- allow user entry to two decimal places when needed for infants
- round only for display, not for the stored computational value

Allowed `type` values today:

- `bool`
- `int`
- `decimal`
- `string`
- `string_key`
- `enum`

Current limitations:

- `multivalue: true` is not yet supported end to end
- list-valued state such as "completed modules" is not first-class yet
- use scalar state such as `st_fever_done` or enum state such as `st_last_module`

## Predicate Catalog Contract

Recommended upstream JSON or CSV:

```json
{
  "predicates": [
    {
      "id": "p_fast_breathing",
      "description_clinical": "Fast breathing by age band",
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
                "right": { "kind": "literal", "type": "int", "value": 12 }
              },
              {
                "kind": ">=",
                "left": { "kind": "var", "id": "v_resp_rate" },
                "right": { "kind": "literal", "type": "int", "value": 50 }
              }
            ]
          },
          {
            "kind": "and",
            "args": [
              {
                "kind": ">=",
                "left": { "kind": "var", "id": "v_age_months" },
                "right": { "kind": "literal", "type": "int", "value": 12 }
              },
              {
                "kind": ">=",
                "left": { "kind": "var", "id": "v_resp_rate" },
                "right": { "kind": "literal", "type": "int", "value": 40 }
              }
            ]
          }
        ]
      },
      "formal_definition": "((v_age_months < 12 and v_resp_rate >= 50) or (v_age_months >= 12 and v_resp_rate >= 40))",
      "missingness_policy": "require_inputs",
      "provenance": [
        { "source_id": "predicate_table", "row": 7 }
      ]
    }
  ]
}
```

Important rule:

- the current compiler understands the structured `expression` AST
- `formal_definition` may be kept as an audit string, but it is not sufficient by itself today

Required predicate fields:

- `id`
- `description_clinical`
- `inputs_used`
- `expression`
- `missingness_policy`
- `provenance`

Optional but useful:

- `formal_definition`

Current supported `missingness_policy` values:

- `require_inputs`
- `treat_missing_as_false`
- `propagate_unknown`

Recommended expression grammar for any staging string form:

- identifiers must be `v_`, `st_`, `c_`, `p_`, or `o_`
- operators must be lowercase
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

If you use string expressions upstream, they should be parsed into the AST before compile time.

## Phrase Bank Contract

Recommended upstream CSV or JSON:

```json
{
  "phrases": [
    {
      "key": "m_v_age_months",
      "entity_id": "v_age_months",
      "role": "label",
      "texts": {
        "en": "Child age (months)",
        "fr": "Age de l'enfant (mois)"
      },
      "provenance": [
        { "source_id": "phrase_bank", "row": 2 }
      ]
    }
  ]
}
```

Recommended CSV columns:

- `key`
- `entity_id`
- `role`
- one or more `text_<lang>` columns such as `text_en`, `text_fr`
- provenance columns such as `provenance_source_id`

Convenience alias:

- `variable_name` is accepted as an alias for `entity_id`

Current lowering:

- variable phrases with `role=label` become XLSForm question labels
- output phrases with `role=message` become output-gated `note` rows
- output phrases with `role=guidance` become a second output-gated `note` row
- legacy `phrase_bindings` are still supported, but no longer required for phrase-bank-backed labels and output text

## DMN Contract

DMN is XML, not JSON.

The current supported DMN subset is:

- decision tables only
- `hitPolicy="FIRST"` only
- at least one input, one output, and one rule per decision
- inputs must be a single identifier:
  - `v_...`
  - `st_...`
  - `p_...`
  - `o_...`
- outputs must be named `o_...`
- input cells may contain only:
  - `true`
  - `false`
  - `-`
- output cells may contain only:
  - `true`
  - `false`
  - integer literals
  - decimal literals
  - quoted strings
  - bare identifiers
  - `-`

Authoring guidance:

- use an all-wildcard final row as the explicit else path
- if a safety fallback is added by the system, give it technical provenance such as:
  - `source_id: SYSTEM_DEFAULT`
  - `kind: system_failsafe`

## Patient Case Contract

The current comparison harness accepts:

- a top-level list of cases, or
- an object with a `cases` list

Recommended form:

```json
{
  "cases": [
    {
      "name": "fever_case",
      "values": {
        "v_age_months": 10,
        "v_has_fever": true,
        "v_fever_days": 4
      },
      "missing": []
    },
    {
      "name": "missing_resp_rate_case",
      "values": {
        "v_age_months": 6
      },
      "missing": ["v_resp_rate"]
    }
  ]
}
```

Rules:

- `name`: optional but strongly recommended
- `values`: required object
- `missing`: optional list of variable IDs
- do not use `null` in `values` to mean missing
- if a field is missing, place its ID in `missing`

## Provenance Contract

Use structured provenance objects, not a single string.

Recommended shape:

```json
[
  {
    "source_id": "WHO_2014_manual",
    "kind": "manual_table",
    "page": 22,
    "section": "Pneumonia classification",
    "row": 4,
    "note": "Fast breathing threshold"
  }
]
```

This is much better than a regex-validated free-text string because it remains machine-readable.

## Review Of The Tier-0 Predicate Checker

Short answer:

- useful as a rough pre-lint
- not safe as the canonical validator
- dangerous if the deduper is kept as written

### What is good

- requiring `p_` IDs is reasonable for predicates
- banning `==` is good
- catching uppercase `AND/OR/NOT` as a style rule is fine
- requiring a missingness field is good

### What is wrong

1. The deduper is unsafe.

`p_fever`, `p_has_fever`, and `p_fever_days` are not guaranteed to be duplicates.
`p_fever_days` is usually a duration concept, not the same predicate as presence of fever.
Do not auto-collapse these.

2. The missingness enum does not match the compiler.

Your checker expects:

- `FALSE_IF_MISSING`
- `TRIGGER_REFERRAL`
- `BLOCK_DECISION`
- `ALERT_NO_RULE_SPECIFIED`

The current compiler expects:

- `require_inputs`
- `treat_missing_as_false`
- `propagate_unknown`

If you want richer policy labels upstream, add an explicit normalization map rather than pretending the enums match.

3. The expression checker is too weak and too permissive.

It allows characters for arithmetic and brackets even though the comment says only comparison and Boolean operators are allowed.
It does not validate:

- balanced parentheses
- token order
- valid identifiers
- allowed identifier prefixes
- actual parseability

4. The quoted-string ban conflicts with supported `selected()` syntax.

If you later allow `selected(x, 'choice')`, banning quotes globally is wrong.

5. Provenance should not be a regex string.

Use structured provenance objects instead.

6. Several required fields belong on variables, not predicates.

These are often variable-level, not predicate-level:

- `units`
- `allowed_input_domain`
- `rounding_parsing_rule`

They may be copied into predicate authoring sheets for convenience, but they should not be the canonical predicate contract.

### Recommended use of that checker

Keep it only as:

- a style linter for a staging sheet
- an early warning tool before normalization

Do not let it:

- define canonical semantics
- mutate or deduplicate predicates automatically
- replace AST parsing and semantic validation

## Bottom Line

If you want the least risky team contract:

- use CSV or JSON for variable catalogs and predicate catalogs
- use CSV for phrase banks when you need multiple languages in one table
- use XML DMN for decision tables
- use `compose-ir` to normalize standalone catalogs into Clinical IR before DMN import
- keep predicate strings only as audit text or parser input
- make the AST and structured provenance authoritative
