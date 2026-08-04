# Authoring Contracts

These contracts define the recommended upstream authoring formats for:

- variable catalogs
- predicate catalogs
- phrase banks
- DMN tables

The directory also contains versioned platform registries that are not clinical
authoring inputs:

- `special-function-registry.json`
- `identity-providers.json` and `identity-providers.schema.json`
- `conflict-policies.json` and `conflict-policies.schema.json`

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

Supporting guidance:

- `../docs/authoring-guide.md`
- `../docs/source-of-truth-editing-policy.md`
