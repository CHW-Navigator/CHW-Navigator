# History, Freshness, and Staged Decisions

This note turns two emerging requirements into concrete IR guidance:

1. staged DMN chaining
2. history-backed values from CHT

This is the canonical operational note for:

- how `st_` and `h_` variables should be used in practice
- how freshness should be modeled
- when codebook-driven generation should emit history variables automatically

Other project documents should summarize these rules briefly and point back here, rather than restating them in full.

## 1. Staged DMN chaining

Target workflow:

- if diagnosis DMN emits `o_dx_pneumonia`, run the pneumonia treatment DMN
- if treatment DMN emits `o_tx_amox`, run the amoxicillin dosage DMN

Recommended modeling rule:

- predicates stay clinical and do not read outputs
- decisions may read outputs from earlier decisions

Recommended prefixes:

- `o_dx_...` diagnosis outputs
- `o_tx_...` treatment outputs
- `o_dose_...` dosage outputs

Recommended decision fields:

- `stage`
- `inputs_used`
- `depends_on`

Example:

```yaml
decisions:
  d_dx_pneumonia:
    stage: 1
    inputs_used: [p_fast_breathing, p_danger_sign]
    hit_policy: FIRST
    rules: [...]

  d_tx_pneumonia:
    stage: 2
    inputs_used: [o_dx_pneumonia, p_can_take_oral]
    depends_on: [d_dx_pneumonia]
    hit_policy: FIRST
    rules: [...]

  d_dose_amox:
    stage: 3
    inputs_used: [o_tx_amox, st_weight_kg_effective]
    depends_on: [d_tx_pneumonia]
    hit_policy: FIRST
    rules: [...]
```

## 2. History-backed values

Target workflow:

- if a prior value exists in CHT and is fresh enough, use it
- otherwise collect a fresh value
- some clinical items, such as date of birth, should be derived from stable history rather than treated as stale snapshots

Recommended variable pattern:

- `v_x` fresh encounter value
- `h_x` history value from CHT
- `h_x_recorded_at` timestamp/date of history value
- `st_x_effective` resolved value used by downstream logic
- `st_x_source` enum such as `history` or `fresh`

### Example: weight

```text
if need_fresh_weight == true
  ask weight
  st_weight_kg_effective = v_weight_kg
else if h_weight_kg is missing
  ask weight
  st_weight_kg_effective = v_weight_kg
else if date_diff_days(now, h_weight_kg_recorded_at) > 30
  ask weight
  st_weight_kg_effective = v_weight_kg
else
  st_weight_kg_effective = h_weight_kg
```

### Example: age from date of birth

Prefer:

```text
st_age_months_effective = age_months_from_date(h_date_of_birth)
```

instead of carrying a stale `h_age_months`.

## 3. Registered local-data read action

Add an explicit action to the IR:

```yaml
actions:
  a_read_date_of_birth:
    kind: read_local_data
    source: local.person.date_of_birth@1.0.0
    outputs: [st_date_of_birth_h]
    mappings:
      - record_key: value
        target_var: st_date_of_birth_h
    fail_mode: ask_if_missing
```

Intent:

- select one exact entry from the deployment's versioned local-data registry
- populate the corresponding history variable without exposing deployment XPath to the LLM
- ask, leave missing, or block according to the declared failure mode

`read_history` remains a supported legacy spelling. With no registry, it produces a
plan-only request. With a registry, it obeys the same binding and lowering rules as
`read_local_data`.

## 4. `ask` and `compute` actions

To keep freshness logic explicit, also allow:

- `ask`
- `compute`

Example resolution step:

```yaml
actions:
  a_resolve_weight:
    kind: compute
    outputs: [st_weight_kg_effective]
    expression:
      kind: if
      cond:
        kind: or
        args:
          - { kind: pred, id: p_need_fresh_weight }
          - { kind: call, fn: is_missing, args: [{ kind: var, id: h_weight_kg }] }
          - kind: >
            left:
              kind: call
              fn: date_diff_days
              args:
                - { kind: literal, value: now }
                - { kind: var, id: h_weight_kg_recorded_at }
            right: { kind: literal, value: 30, type: int }
      then: { kind: var, id: v_weight_kg }
      else: { kind: var, id: h_weight_kg }
```

## 5. Codebook-driven generation and manual authoring

The codebook is a machine-validated `cht-local-data-bindings@1.0.0` registry. It
defines which CHT fields are legal in the current deployment, their meaning and type,
their launch contexts, and their freshness contract.

Automation rule:

- if you are using the codebook-driven variable generator, it should create the history variables automatically where permitted
- if you are hand-authoring IR or catalogs, you should declare the same `h_...`, `h_..._recorded_at`, and `history_binding` fields manually where applicable

So "automatic" refers to generator behavior, not to a hidden compiler side effect.

When the deployment permits it, the generator should emit:

- `h_x`
- `h_x_recorded_at` when available
- `history_binding`

This is better than leaving CHT history availability implicit.

## 6. Compiler implications

### Pydantic / IR layer

Add support for:

- `h_` variables
- `actions`
- optional decision `stage`, `inputs_used`, `depends_on`
- optional variable `source_kind` and `history_binding`

### Validator

Validate:

- predicates do not reference outputs
- decisions may reference only prior outputs
- `read_history` outputs are `h_` variables
- `recorded_at_target_var` points to a real variable

### Lint

Warn or error on:

- missing freshness policy for time-sensitive history values
- decision cycles
- decision reading its own output
- history variable declared without legal codebook binding

### Z3

Later use Z3 for:

- reachable chained-decision conflicts
- loop detection if iterative execution is ever introduced

For now, a graph-based acyclic rule is the right default.

## 7. Recommended first implementation order

1. document the IR additions
2. add decision dependency graph lint
3. add `h_` and `history_binding` to variable-generation contracts
4. add `read_history` to the IR
5. lower registered reads into CHT-specific form inputs and calculations
6. later add Z3 analysis for chained workflow hazards
