# Local-data authoring handoff

## What is connected

The compiler accepts a versioned CHT local-data registry together with canonical
Clinical IR. An IR action names an exact reviewed binding, for example:

```json
{
  "kind": "read_local_data",
  "source": "patient.date_of_birth@1.0.0",
  "mapping": {"record_key": "date_of_birth"},
  "outputs": ["date_of_birth"],
  "failure_mode": "ask_if_missing"
}
```

The compiler, not the LLM, owns the binding's CHT version, adapter kind, storage
path, type, unit, freshness policy, and allowed form contexts. It rejects unknown
bindings and mismatches, then lowers accepted reads into CHT form inputs and an
executable XForm.

This deliberately gives the LLM a small capability surface: it may select a
binding ID and map its value into a declared IR variable. It may not invent a
PouchDB query, XPath, document field, or extension-library call.

## Intended authoring pipeline

1. The authoring run receives the CHW manual, a reviewed local-data registry,
   and an exact target CHT profile.
2. The LLM emits canonical Clinical IR and uses `read_local_data` only with
   binding IDs present in that registry.
3. Deterministic Clinical IR and registry validation rejects invented,
   unavailable, stale-policy-incompatible, type-incompatible, or
   unit-incompatible reads.
4. The CHT backend generates the form source, executable XForm, task rules when
   requested, a lowering plan, and a hashed bundle manifest.
5. The generated bundle is tested with the official CHT harness and the exact
   deployment CHT version before release.

## Boundary that is not yet connected

The current Product Gen7/Gen8 extraction pipeline emits its own seven-part
`clinical_logic` object: supplies, variables, predicates, modules, router,
phrase bank, and integrative rules. That object is not the compiler's canonical
Clinical IR, and the Product naming codebook is not the reviewed CHT local-data
registry.

Therefore the repository does not yet provide an end-to-end
manual-plus-registry to deployable-CHT run. The next integration slice must add
and test an explicit Product `clinical_logic` to Clinical IR adapter (or change
Product to emit canonical Clinical IR), then pass the registry and target
profile through that boundary. Prompt-only changes would create output that no
current deterministic consumer enforces, so they should land with the adapter
and contract tests rather than independently.
