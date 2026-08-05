# Special-function CHT integration

## Current status

The authoritative Python compiler now emits reviewed technical special-function
artifacts for exactly CHT 4.22.0 and 5.2.0:

- native `z-score('weight-for-age', ...)` for weight-for-age, with no WFA
  JavaScript and mandatory warning `CHT-SPECIAL-001`;
- `extension-libs/gestational-age-from-lmp.js` plus a hidden-calculation XForm
  for gestational age and estimated delivery date.

Both profiles use the same XForm XPath syntax,
`cht:extension-lib('file.js', ...)`, which CHT documents as available from 4.2.
CHT 5.2 additionally supports JavaScript expression-context calls through
`extensionLib(name, ...args)`; the compiler does not substitute that newer syntax
inside XForms.

Official references:

- <https://docs.communityhealthtoolkit.org/building/reference/extension-libs/>
- <https://docs.communityhealthtoolkit.org/building/forms/app/#cht-extension-lib>
- <https://docs.communityhealthtoolkit.org/building/forms/_partial_expression_functions/>

## Compiler entry point

Use the existing CHT plan and request one reviewed target explicitly:

```python
plan = build_cht_lowering_plan(
    document,
    special_function_target_cht_version="4.22.0",
)
artifacts = write_cht_adapter_bundle(plan, output_dir)
```

This emits the two XForms, the dependency-free extension module, and a manifest
with target-profile capabilities, file hashes, and diagnostics. Unreviewed CHT
versions fail closed. Existing divergent files are never overwritten.

The special-function registry is
[`../contracts/special-function-registry.json`](../contracts/special-function-registry.json),
and gestational-age vectors are in
[`../examples/special_functions/gestational-age-vectors.json`](../examples/special_functions/gestational-age-vectors.json).
Both implementation and vector digests are enforced.

## Tests

The normal compiler suite covers:

- the shared versioned clinical vocabulary, including renamed and nested attacks;
- all eight technical statuses and malformed CHT envelopes;
- Python gestational-age vectors and generated CommonJS execution;
- 4.22/5.2 capability separation and unreviewed-version rejection;
- exact generated XML parsing, one compute call, and no WFA JavaScript;
- non-clobbering output and digest drift;
- every declared diagnostic having a source emission and explicit test assertion.

For the near-end-to-end external check, run from `compiler/`:

```powershell
$env:PYTHONPATH='src'; ..\.venv\Scripts\python.exe scripts\run_prompt12_cht_harness.py
```

That command regenerates Python-owned artifacts into a temporary external CHT
project, archives extension libraries with pinned official `cht-conf` 6.4.1, and
runs both profiles through `cht-conf-test-harness` 5.0.4. The browser fills and
submits the generated form through the bundled CHT Core 4.11 engine's real
`cht:extension-lib` XPath implementation and asserts the technical report fields.

## Evidence boundary

This is not yet a live deployment claim. The external gates still are:

- exact CHT 4.22.0 and 5.2.0 target-runtime execution;
- live CouchDB upload and attachment inspection;
- offline device/service-worker behavior;
- equivalence between the deployment-owned native WFA chart and the pinned
  reference version;
- clinical, program, security, and deployment approval.
