# Authoring Contracts

These contracts define the recommended upstream authoring formats for:

- variable catalogs
- predicate catalogs
- phrase banks
- DMN tables

The directory also contains versioned platform registries that are not clinical
authoring inputs:

- `registry-set.schema.json`, `capability-registry.schema.json`, and
  `target-profile.schema.json` define the minimal WS1 content-addressed contract;
- `registry-set-v2.schema.json`, `data-dictionary.schema.json`,
  `capability-governance.schema.json`, `approval-attestation.schema.json`, and
  `registry-release.schema.json` define the WS3 governed-release layer;
- `special-function-registry.json`
- `identity-providers.json` and `identity-providers.schema.json`
- `conflict-policies.json` and `conflict-policies.schema.json`
- `cht-task-bindings.schema.json`

Identity resolution and correction policy remain platform services outside Clinical
IR. Their presence here does not authorize candidate lists or mutable clinical
evidence in decision tables.

Use them together with [authoring-json-contracts.md](../authoring-json-contracts.md).

Authoring model:

- variable catalog + predicate catalog + DMN + phrase bank are the authored clinical source of truth
- Clinical IR is the canonical compiled representation generated from those sources

Cross-cutting rules:

- all contracts require structured provenance objects rather than free-text provenance strings
- EHR/history-fed fields should remain in the normal identifier families and may use an `_h` suffix, for example `v_weight_kg_h` or `st_prev_referral_h`
- continuous variables may optionally carry MOH-supplied `remeasure_*` and `dont_allow_*` thresholds in the variable catalog

Files:

- `registry-set.schema.json`
- `capability-registry.schema.json`
- `target-profile.schema.json`
- `registry-set-v2.schema.json`
- `data-dictionary.schema.json`
- `capability-governance.schema.json`
- `approval-attestation.schema.json`
- `registry-release.schema.json`
- `examples/tracer/valid-registry-set.json` and `negative-cases.json`
- `variable-catalog.contract.md`
- `predicate-catalog.contract.md`
- `phrase-bank.contract.md`
- `dmn.contract.md`
- `simulated-patient-data.contract.md`
- `engine-log.contract.md`
- `special-function-registry.json`
- `identity-providers.json`
- `identity-providers.schema.json`
- `conflict-policies.json`
- `conflict-policies.schema.json`
- `cht-task-bindings.schema.json`

The CHT task-binding contract is deployment-owned. It maps a Clinical IR `task_type`
to the exact CHT follow-up form, translation, permission, timing window, role, icon,
and priority. CHT lowering fails closed when a `create_task` action has no matching
binding; the compiler does not infer deployment values from clinical text.

WS1 capability `evidence_status` is deliberately limited to `candidate` and
`tracer_enabled`. `tracer_enabled` permits the hand-written WS2 technical tracer
to resolve; it is not approval, clinical evidence, deployment readiness, or proof
that the planned implementation binding already exists. WS2 must supply and test
that binding before it can earn executable evidence.

WS3 does not add approval fields to the executable capability. A governed v2
set binds data concepts and capability-governance entries to exact v1 content
digests. Activation is a separate operation requiring distinct clinical,
data-governance, and technical attestations whose detached signatures verify
against the exact set. The committed fixture uses only `synthetic-test-*`
identities; it is test evidence, never a ministry approval record.

Supporting guidance:

- `../docs/authoring-guide.md`
- `../docs/source-of-truth-editing-policy.md`
