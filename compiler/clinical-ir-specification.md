# Clinical IR Specification

## Purpose

This document defines the minimum canonical Clinical IR for the compiler. It is the semantic core used to represent clinical decision logic independently of DMN, XLSForm, Z3, or Mermaid.

The Clinical IR is intentionally smaller than full XLSForm and smaller than full DMN. It is designed to be:

- typed
- explicit
- auditable
- provenance-preserving
- easy to interpret deterministically
- easy to lower into multiple backends

## Scope

The Clinical IR represents:

- variables
- constants
- predicates
- decisions
- outputs
- invariants
- provenance

It does not directly represent full form layout, repeats, cosmetic text formatting, or unrestricted XPath behavior. Those belong in Form IR or Source IR.

## Design Principles

### Canonical semantics

The Clinical IR is the ground truth for supported clinical logic.

### Typed nodes

All symbols and expressions are typed.

### Stable identifiers

Every reusable entity has a stable ID.

### Provenance everywhere

Every clinically meaningful node should retain source references.

### Minimality

The IR should not become a general-purpose programming language.

## Top-Level Shape

The canonical representation may be serialized in YAML or JSON. A typical document has the following sections:

- metadata
- variables
- constants
- predicates
- decisions
- outputs
- invariants
- phrase_bindings

## Metadata

Metadata should include:

- IR version
- condition or guideline name
- source artifact identifiers
- compiler version
- generation timestamp

Example:

```yaml
metadata:
  ir_version: 1
  guideline_id: pneumonia
  compiler_version: 0.1.0
  generated_at: "2026-04-30T12:00:00Z"
  sources:
    - id: chw_manual_v1
      kind: manual
      ref: "Chapter 4, page 22"
```

## Identifier Conventions

Recommended prefixes:

- `v_` for variables
- `st_` for state variables carried across steps or visits
- `c_` for constants
- `p_` for predicates
- `d_` for decisions
- `r_` for rules
- `o_` for outputs
- `i_` for invariants
- `m_` for message keys or phrase bindings

These naming conventions help readability and linting, but the compiler should not rely on prefixes alone for semantics.

## Types

Minimum supported scalar types:

- `bool`
- `int`
- `decimal`
- `string`
- `string_key`
- `enum`

Additional meta-properties may include:

- unit
- domain
- nullable or missingness policy

## Variables

Variables represent collected or externally supplied clinical facts.

State variables are represented in the same typed variable section, but should use the `st_` prefix when they represent workflow state, prior module completion, or prior-visit carry-forward values.

Each variable should define:

- `id`
- `type`
- `domain`
- `unit` if applicable
- `allowed_missingness`
- `multivalue` if applicable
- provenance

Current implementation note:

- `st_` variables are supported as ordinary scalar variables today.
- Rich state collections such as "list of completed modules" are not yet a first-class type. For now, model state as scalar flags or enums such as `st_fever_done: bool` or `st_last_completed_module: enum`.

Current implementation note:

- `multivalue: true` is reserved for future repeats and select-many support and is not yet accepted by the current validator/runtime pipeline.

Example:

```yaml
variables:
  st_fever_done:
    type: bool
    allowed_missingness: false
    provenance:
      - source_id: state_catalog
        row: 3

  v_age_months:
    type: int
    domain:
      min: 0
      max: 120
    allowed_missingness: false
    provenance:
      - source_id: variable_catalog
        row: 12

  v_resp_rate:
    type: int
    domain:
      min: 0
      max: 120
    unit: breaths_per_min
    allowed_missingness: true
    provenance:
      - source_id: variable_catalog
        row: 18
```

## Constants

Constants capture named domain values or thresholds that should not be duplicated inside expressions.

Each constant should define:

- `id`
- `type`
- `value`
- provenance

Example:

```yaml
constants:
  c_fast_breathing_under_12m:
    type: int
    value: 50
  c_fast_breathing_12m_plus:
    type: int
    value: 40
```

## Missingness Model

Missingness must be explicit. At minimum, the IR should support these states conceptually:

- present
- missing
- not_applicable

An implementation may encode these with companion state variables or structured values, but predicate semantics must never assume missing equals false unless the rule explicitly says so.

Each variable and predicate should declare or inherit a missingness policy.

## Expressions

Expressions should be stored as normalized typed ASTs, not only as free text.

Supported operations in the initial subset:

- logical: `and`, `or`, `not`
- comparison: `=`, `!=`, `<`, `<=`, `>`, `>=`
- arithmetic: `+`, `-`, `*`, `/`
- conditional: `if(cond, a, b)`
- membership helper: `selected(x, 'choice')`

The serialized format may use either compact strings plus parsed AST cache, or fully structured AST nodes. The implementation should treat the structured AST as authoritative.

Example structured expression:

```yaml
kind: or
args:
  - kind: and
    args:
      - kind: <
        left: { kind: var, id: v_age_months }
        right: { kind: const, id: c_age_12m }
      - kind: >=
        left: { kind: var, id: v_resp_rate }
        right: { kind: const, id: c_fast_breathing_under_12m }
  - kind: and
    args:
      - kind: >=
        left: { kind: var, id: v_age_months }
        right: { kind: const, id: c_age_12m }
      - kind: >=
        left: { kind: var, id: v_resp_rate }
        right: { kind: const, id: c_fast_breathing_12m_plus }
```

## Predicates

Predicates are named Boolean clinical concepts derived from variables and constants.

Each predicate should define:

- `id`
- `inputs_used`
- `expression`
- `missingness_policy`
- optional description
- provenance

Example:

```yaml
predicates:
  p_fast_breathing:
    inputs_used: [v_age_months, v_resp_rate]
    expression:
      kind: or
      args:
        - kind: and
          args:
            - kind: <
              left: { kind: var, id: v_age_months }
              right: { kind: literal, value: 12, type: int }
            - kind: >=
              left: { kind: var, id: v_resp_rate }
              right: { kind: literal, value: 50, type: int }
        - kind: and
          args:
            - kind: >=
              left: { kind: var, id: v_age_months }
              right: { kind: literal, value: 12, type: int }
            - kind: >=
              left: { kind: var, id: v_resp_rate }
              right: { kind: literal, value: 40, type: int }
    missingness_policy: require_inputs
    provenance:
      - source_id: predicate_table
        row: 7
```

Suggested initial missingness policies:

- `require_inputs`
- `treat_missing_as_false`
- `propagate_unknown`

Current implementation note:

- The runtime distinguishes present values from unknown or unresolved values during predicate evaluation, but it does not yet implement a fully first-class `not_applicable` state throughout every backend.

## Decisions

Decisions represent ordered rule evaluation over predicates and constants.

Each decision should define:

- `id`
- `hit_policy`
- ordered `rules`
- provenance

Initial support:

- `FIRST`

`FIRST` applies per decision. Multiple decisions may exist in one document, and their outputs may be combined downstream. The current toolkit does not yet define a first-class action or task-scheduling layer for care-plan aggregation.

Each rule should define:

- `id`
- `when`
- `then`
- optional description
- provenance

Example:

```yaml
decisions:
  d_triage:
    hit_policy: FIRST
    rules:
      - id: r_triage_1
        when:
          kind: pred
          id: p_danger_sign
        then:
          o_referral: true
      - id: r_triage_2
        when:
          kind: and
          args:
            - kind: pred
              id: p_fast_breathing
            - kind: not
              arg:
                kind: pred
                id: p_danger_sign
        then:
          o_home_treatment: true
      - id: r_triage_else
        when:
          kind: else
        then:
          o_no_action: true
    provenance:
      - source_id: dmn_triage
        table: triage
```

## Outputs

Outputs are terminal or intermediate result symbols produced by decisions.

Do not restrict the architecture to Boolean outputs only. Minimum supported output types should include:

- `bool`
- `enum`
- `int`
- `string_key`

Each output should define:

- `id`
- `type`
- optional domain
- optional description
- provenance

Example:

```yaml
outputs:
  o_referral:
    type: bool
    provenance:
      - source_id: dmn_triage
        column: referral

  o_treatment_code:
    type: enum
    domain: [none, home, urgent_referral]
    provenance:
      - source_id: dmn_triage
        column: treatment_code
```

## Invariants

Invariants are assertions that should always hold if the logic is internally consistent.

Examples:

- exactly one terminal disposition is true
- referral implies no home-treatment-only endpoint
- a danger sign must imply urgent action

Each invariant should define:

- `id`
- `expression`
- severity
- provenance

Example:

```yaml
invariants:
  i_single_endpoint:
    severity: error
    expression:
      kind: exactly_one
      args:
        - { kind: output, id: o_referral }
        - { kind: output, id: o_home_treatment }
        - { kind: output, id: o_no_action }
```

If the core expression language does not directly support operators such as `exactly_one`, the invariant may be lowered into primitive Boolean combinations during normalization.

## Phrase Bindings

Phrase text should not live inside core decision logic. The Clinical IR should reference keys that can later be resolved through a phrase bank.

Example:

```yaml
phrase_bindings:
  o_referral:
    message_key: m_referral
    guidance_key: m_referral_followup
```

Current XLSForm mapping:

- `message_key` lowers to an output-gated `note` row
- `guidance_key` lowers to an additional output-gated `note` row intended for clinician guidance

## Provenance Format

Each clinically meaningful entity should support provenance records such as:

- `source_id`
- `kind`
- `location`
- `row`
- `column`
- `page`
- `section`
- `note`

Example:

```yaml
provenance:
  - source_id: chw_manual_v1
    kind: manual_table
    page: 22
    section: "Pneumonia classification"
    note: "Fast breathing threshold"

System-added fail-safes should also be explicit in provenance. Recommended patterns include:

- `source_id: SYSTEM_DEFAULT`
- `kind: system_failsafe`
- `note: "Fail-safe added by system because no MOH-defined path handled this case"`
```

## Validation Rules

The validator for Clinical IR should enforce:

- all IDs are unique in their namespaces
- all referenced symbols exist
- all expressions are type-correct
- all domains are valid
- all rule orderings are explicit
- all decisions use supported hit policies
- dependency graph is acyclic unless cycles are explicitly supported
- missingness policy is defined where required
- provenance is present for required node classes

When a fallback rule is added for safety rather than sourced from the manual, it should still validate normally but must retain explicit technical provenance so auditors can distinguish authored clinical logic from compiler-added fail-safe behavior.

## Evaluation Semantics

The reference interpreter should evaluate in a deterministic order:

1. validate input variable assignments
2. resolve constants
3. evaluate predicates in dependency order
4. evaluate decisions in declared order
5. materialize outputs
6. check invariants

Decision evaluation for `FIRST` means the first satisfied rule wins for that decision.

Current implementation note:

- Later decisions may read outputs from earlier decisions, and state-like carry-forward facts may be modeled as `st_` variables supplied at evaluation time.

## Example Minimal IR

```yaml
metadata:
  ir_version: 1
  guideline_id: pneumonia

variables:
  v_age_months:
    type: int
    domain: { min: 0, max: 120 }
    allowed_missingness: false
  v_resp_rate:
    type: int
    domain: { min: 0, max: 120 }
    allowed_missingness: false
  v_danger_sign:
    type: bool
    allowed_missingness: false

predicates:
  p_danger_sign:
    inputs_used: [v_danger_sign]
    expression:
      kind: var
      id: v_danger_sign
    missingness_policy: require_inputs

  p_fast_breathing:
    inputs_used: [v_age_months, v_resp_rate]
    expression:
      kind: or
      args:
        - kind: and
          args:
            - kind: <
              left: { kind: var, id: v_age_months }
              right: { kind: literal, type: int, value: 12 }
            - kind: >=
              left: { kind: var, id: v_resp_rate }
              right: { kind: literal, type: int, value: 50 }
        - kind: and
          args:
            - kind: >=
              left: { kind: var, id: v_age_months }
              right: { kind: literal, type: int, value: 12 }
            - kind: >=
              left: { kind: var, id: v_resp_rate }
              right: { kind: literal, type: int, value: 40 }
    missingness_policy: require_inputs

outputs:
  o_referral:
    type: bool
  o_home_treatment:
    type: bool
  o_no_action:
    type: bool

decisions:
  d_triage:
    hit_policy: FIRST
    rules:
      - id: r1
        when: { kind: pred, id: p_danger_sign }
        then: { o_referral: true }
      - id: r2
        when:
          kind: and
          args:
            - { kind: pred, id: p_fast_breathing }
            - kind: not
              arg: { kind: pred, id: p_danger_sign }
        then: { o_home_treatment: true }
      - id: r3
        when: { kind: else }
        then: { o_no_action: true }

phrase_bindings:
  o_referral:
    message_key: m_referral
```

## Non-Goals

The Clinical IR should not try to represent:

- arbitrary XPath
- arbitrary FEEL
- external lookup tables without a declared lowering contract
- nonlinear or lookup-backed math that the formal backend cannot model exactly
- full form rendering behavior
- repeats or household-style iteration mechanics in the current implementation
- localization text bodies
- every quirk of every target engine

Those belong in other layers or should be rejected as unsupported.

## Bottom Line

The Clinical IR should be the smallest typed representation that can faithfully express supported clinical logic, preserve provenance, and lower cleanly into Z3, XLSForm, DMN-oriented execution, and Mermaid audit views.
