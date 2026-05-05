# DMN Contract v1

## Purpose

Defines the supported DMN authoring subset for decision-table import.

Within the toolchain, DMN plus the predicate catalog are part of the authored clinical source of truth. Clinical IR is the compiled representation produced from them.

## Format

- XML DMN

## Supported Scope

- decision tables only
- `hitPolicy="FIRST"` only
- one or more decisions per file
- each decision must define:
  - at least one input
  - at least one output
  - at least one rule

## Identifier Rules

Input expressions must be a single identifier with one of these prefixes:

- `v_`
- `st_`
- `p_`
- `o_`

EHR/history-fed fields should stay in those same families and may use an `_h` suffix, for example `v_weight_kg_h` or `st_prev_referral_h`.

Output identifiers must start with:

- `o_`

Rule IDs should start with:

- `r`

Decision IDs should start with:

- `d_`

## Supported Input Cell Values

- `true`
- `false`
- `-`

## Supported Output Cell Values

- `true`
- `false`
- integer literals
- decimal literals
- quoted strings
- bare identifiers
- `-`

## Required Authoring Pattern

- final rule should be the catch-all else path
- in table form that usually means every input entry on the final row is `-`

## Example

```xml
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="defs_pneumonia" name="pneumonia">
  <decision id="d_triage" name="Triage">
    <decisionTable hitPolicy="FIRST">
      <input id="input_danger">
        <inputExpression id="ie_danger" typeRef="boolean">
          <text>p_danger_sign</text>
        </inputExpression>
      </input>
      <input id="input_fast_breathing">
        <inputExpression id="ie_fast_breathing" typeRef="boolean">
          <text>p_fast_breathing</text>
        </inputExpression>
      </input>
      <output id="out_referral" name="o_referral" typeRef="boolean" />
      <output id="out_home_treatment" name="o_home_treatment" typeRef="boolean" />
      <output id="out_no_action" name="o_no_action" typeRef="boolean" />
      <rule id="r1">
        <inputEntry id="r1_i1"><text>true</text></inputEntry>
        <inputEntry id="r1_i2"><text>-</text></inputEntry>
        <outputEntry id="r1_o1"><text>true</text></outputEntry>
        <outputEntry id="r1_o2"><text>false</text></outputEntry>
        <outputEntry id="r1_o3"><text>false</text></outputEntry>
      </rule>
      <rule id="r2">
        <inputEntry id="r2_i1"><text>false</text></inputEntry>
        <inputEntry id="r2_i2"><text>true</text></inputEntry>
        <outputEntry id="r2_o1"><text>false</text></outputEntry>
        <outputEntry id="r2_o2"><text>true</text></outputEntry>
        <outputEntry id="r2_o3"><text>false</text></outputEntry>
      </rule>
      <rule id="r3">
        <inputEntry id="r3_i1"><text>-</text></inputEntry>
        <inputEntry id="r3_i2"><text>-</text></inputEntry>
        <outputEntry id="r3_o1"><text>false</text></outputEntry>
        <outputEntry id="r3_o2"><text>false</text></outputEntry>
        <outputEntry id="r3_o3"><text>true</text></outputEntry>
      </rule>
    </decisionTable>
  </decision>
</definitions>
```

## Fail-Loud Rules

The compiler should reject:

- unsupported hit policies
- missing input expressions
- compound input expressions like `p_a and p_b`
- missing or unprefixed output names
- unsupported input cell formulas such as `>= 50`
- unsupported output expressions such as `1 + 2`

## Safety Guidance

- if a system fail-safe rule is added, mark it with explicit provenance such as `source_id: SYSTEM_DEFAULT`
- do not silently approximate unsupported DMN features

## Provenance

DMN import must preserve structured provenance on:

- each decision
- each rule
- generated outputs where their source table/column is known

At minimum, imported provenance should capture `source_id`, `kind`, and row/table-level location when available. If richer source provenance exists outside raw DMN XML, keep it in a companion structured manifest rather than a free-text note.
